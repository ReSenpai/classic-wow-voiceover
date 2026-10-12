from pathlib import Path

import pytest

from voru.jobs.queue import MAX_ATTEMPTS, JobQueue
from voru.jobs.runner import enqueue_synthesis, run_worker
from voru.providers.base import SynthesisRequest, VoiceRef
from voru.providers.mock import MockProvider


def req(text="Привет, путник.", voice_id="nightelf-male-calm", reference=None, **overrides):
    base = dict(
        text=text, locale="ruRU", player_gender=None,
        voice=VoiceRef(voice_id, "1", reference, "Пример речи." if reference else None),
        delivery_profile="neutral", generation_config={"seed": 1}, output_path=None,
    )
    base.update(overrides)
    return SynthesisRequest(**base)


@pytest.fixture
def queue(tmp_path):
    return JobQueue(tmp_path / "jobs.sqlite")


@pytest.fixture
def masters(tmp_path):
    return tmp_path / "masters"


def test_empty_queue(queue, masters):
    """Регрессия legacy: пустая выборка не должна ронять генерацию."""
    assert run_worker(queue, MockProvider(), "w1", masters) == {"generated": 0, "failed": 0, "retried": 0, "qa_failed": 0, "review_required": 0}


def test_jobs_are_synthesized_into_masters(queue, masters):
    provider = MockProvider()
    ids = [enqueue_synthesis(queue, f"slot-{i}", provider, req(text=f"Реплика номер {i}."), 1) for i in range(3)]

    stats = run_worker(queue, provider, "w1", masters)

    assert stats == {"generated": 3, "failed": 0, "retried": 0, "qa_failed": 0, "review_required": 0}
    for job_id in ids:
        job = queue.get(job_id)
        assert job.state == "generated"
        path = Path(job.result["output_path"])
        assert path == masters / f"{job.fingerprint}.wav"
        assert path.exists()
        assert job.result["duration_ms"] > 0
        assert job.result["model_revision"] == provider.model_revision()


def test_enqueue_is_idempotent_and_detects_changes(queue):
    provider = MockProvider()
    a = enqueue_synthesis(queue, "slot-a", provider, req(), 1)
    b = enqueue_synthesis(queue, "slot-a", provider, req(), 1)
    c = enqueue_synthesis(queue, "slot-a", provider, req(text="Привет, странник."), 1)

    assert a == b
    assert c != a
    assert queue.get(a).state == "superseded"


def test_voice_change_requeues_only_affected_slot(queue, masters):
    provider = MockProvider()
    enqueue_synthesis(queue, "slot-a", provider, req(voice_id="v1"), 1)
    enqueue_synthesis(queue, "slot-b", provider, req(voice_id="v2"), 1)
    run_worker(queue, provider, "w1", masters)

    enqueue_synthesis(queue, "slot-a", provider, req(voice_id="v1"), 1)
    enqueue_synthesis(queue, "slot-b", provider, req(voice_id="v2-new"), 1)

    assert run_worker(queue, provider, "w1", masters)["generated"] == 1


def test_unsupported_option_fails_without_retry(queue, masters):
    provider = MockProvider()
    job_id = enqueue_synthesis(queue, "slot-a", provider, req(locale="deDE"), 1, validate=False)

    stats = run_worker(queue, provider, "w1", masters)

    assert stats == {"generated": 0, "failed": 1, "retried": 0, "qa_failed": 0, "review_required": 0}
    job = queue.get(job_id)
    assert job.attempts == 1
    assert "unsupported_language" in job.last_error


def test_enqueue_validates_by_default(queue):
    from voru.providers.base import UnsupportedOption

    with pytest.raises(UnsupportedOption):
        enqueue_synthesis(queue, "slot-a", MockProvider(), req(locale="deDE"), 1)


class Flaky(MockProvider):
    def __init__(self, failures):
        super().__init__()
        self.failures = failures

    def _generate(self, model_text, request):
        if self.failures > 0:
            self.failures -= 1
            raise RuntimeError("CUDA out of memory")
        return super()._generate(model_text, request)


def test_transient_error_is_retried(queue, masters):
    job_id = enqueue_synthesis(queue, "slot-a", MockProvider(), req(), 1)

    stats = run_worker(queue, Flaky(failures=1), "w1", masters)

    assert stats == {"generated": 1, "failed": 0, "retried": 1, "qa_failed": 0, "review_required": 0}
    assert queue.get(job_id).attempts == 2


def test_persistent_error_ends_in_failed(queue, masters):
    job_id = enqueue_synthesis(queue, "slot-a", MockProvider(), req(), 1)

    stats = run_worker(queue, Flaky(failures=99), "w1", masters)

    assert stats == {"generated": 0, "failed": 1, "retried": MAX_ATTEMPTS - 1, "qa_failed": 0, "review_required": 0}
    assert "CUDA out of memory" in queue.get(job_id).last_error


def test_jobs_of_other_provider_are_not_taken(queue, masters):
    class Other(MockProvider):
        name = "other"

    enqueue_synthesis(queue, "slot-a", Other(), req(), 1)

    assert run_worker(queue, MockProvider(), "w1", masters)["generated"] == 0
    assert queue.summary() == {"pending": 1}


class Silent(MockProvider):
    def _generate(self, model_text, request):
        samples, sr = super()._generate(model_text, request)
        return [0.0] * len(samples), sr


class Dragging(MockProvider):
    """Тянет звук втрое дольше нормы — как зациклившаяся модель."""
    def _generate(self, model_text, request):
        samples, sr = super()._generate(model_text, request)
        return samples * 5, sr


def test_qa_marks_silent_audio_as_failed(queue, masters):
    job_id = enqueue_synthesis(queue, "slot-a", Silent(), req(text="Привет, путник, как твои дела сегодня?"), 1)

    stats = run_worker(queue, Silent(), "w1", masters)

    job = queue.get(job_id)
    assert job.state == "qa_failed"
    assert "silent" in job.last_error
    assert stats["qa_failed"] == 1 and stats["generated"] == 0


def test_qa_marks_dragging_audio_as_failed(queue, masters):
    job_id = enqueue_synthesis(queue, "slot-a", Dragging(), req(text="Привет, путник, как твои дела сегодня?"), 1)

    run_worker(queue, Dragging(), "w1", masters)

    assert queue.get(job_id).state == "qa_failed"
    assert "too_slow" in queue.get(job_id).last_error


def test_clean_mock_audio_passes_qa(queue, masters):
    job_id = enqueue_synthesis(queue, "slot-a", MockProvider(), req(text="Привет, путник, как твои дела сегодня?"), 1)

    stats = run_worker(queue, MockProvider(), "w1", masters)

    assert queue.get(job_id).state == "generated"
    assert stats == {"generated": 1, "failed": 0, "retried": 0, "qa_failed": 0, "review_required": 0}


class SilentOnBaseSeed(MockProvider):
    """Брак только на базовом seed — как неудачный дубль модели."""
    def _generate(self, model_text, request):
        samples, sr = super()._generate(model_text, request)
        return ([0.0] * len(samples) if request.generation_config["seed"] == 1 else samples), sr


def test_qa_failure_is_retried_with_another_seed(queue, masters):
    from voru.jobs.runner import QA_SEED_STEP

    job_id = enqueue_synthesis(queue, "slot-a", SilentOnBaseSeed(),
                               req(text="Привет, путник, как твои дела сегодня?"), 1)

    stats = run_worker(queue, SilentOnBaseSeed(), "w1", masters)

    job = queue.get(job_id)
    assert job.state == "generated"
    assert job.result["seed_used"] == 1 + QA_SEED_STEP
    assert job.result["qa_attempts"] == 2
    assert "silent" in job.result["qa_history"][0]
    assert stats["generated"] == 1 and stats["qa_failed"] == 0


def test_qa_retries_are_limited(queue, masters):
    from voru.jobs.runner import MAX_QA_RETRIES

    job_id = enqueue_synthesis(queue, "slot-a", Silent(), req(text="Привет, путник, как твои дела сегодня?"), 1)

    run_worker(queue, Silent(), "w1", masters)

    job = queue.get(job_id)
    assert job.state == "qa_failed"
    assert job.result["qa_attempts"] == 1 + MAX_QA_RETRIES
    assert len(job.result["qa_history"]) == 1 + MAX_QA_RETRIES


def test_clean_first_attempt_records_base_seed(queue, masters):
    job_id = enqueue_synthesis(queue, "slot-a", MockProvider(), req(text="Привет, путник, как твои дела сегодня?"), 1)

    run_worker(queue, MockProvider(), "w1", masters)

    result = queue.get(job_id).result
    assert (result["seed_used"], result["qa_attempts"], result["qa_history"]) == (1, 1, [])


def test_transient_error_is_kept_after_success(queue, masters):
    job_id = enqueue_synthesis(queue, "slot-a", MockProvider(), req(), 1)

    run_worker(queue, Flaky(failures=1), "w1", masters)

    assert "CUDA out of memory" in queue.get(job_id).last_error


def test_text_changed_during_synthesis_does_not_break_qa(queue, masters):
    class ChangesTextMidway(Silent):
        def _generate(self, model_text, request):
            enqueue_synthesis(queue, "slot-a", MockProvider(), req(text="Совсем другой текст реплики."), 1)
            return super()._generate(model_text, request)

    old = enqueue_synthesis(queue, "slot-a", MockProvider(), req(text="Привет, путник, как твои дела сегодня?"), 1)

    run_worker(queue, ChangesTextMidway(), "w1", masters)

    assert queue.get(old).state == "superseded"


def test_reference_changed_after_enqueue_is_not_synthesized(queue, masters, tmp_path):
    ref = tmp_path / "ref.wav"
    ref.write_bytes(b"old voice")
    job_id = enqueue_synthesis(queue, "slot-a", MockProvider(), req(reference=ref), 1)
    ref.write_bytes(b"new voice")

    stats = run_worker(queue, MockProvider(), "w1", masters)

    assert stats["failed"] == 1
    assert "fingerprint_mismatch" in queue.get(job_id).last_error
    assert not masters.exists() or not any(masters.iterdir())

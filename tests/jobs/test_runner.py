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
    assert run_worker(queue, MockProvider(), "w1", masters) == {"generated": 0, "failed": 0, "retried": 0}


def test_jobs_are_synthesized_into_masters(queue, masters):
    provider = MockProvider()
    ids = [enqueue_synthesis(queue, f"slot-{i}", provider, req(text=f"Реплика номер {i}."), 1) for i in range(3)]

    stats = run_worker(queue, provider, "w1", masters)

    assert stats == {"generated": 3, "failed": 0, "retried": 0}
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

    assert stats == {"generated": 0, "failed": 1, "retried": 0}
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

    assert stats == {"generated": 1, "failed": 0, "retried": 1}
    assert queue.get(job_id).attempts == 2


def test_persistent_error_ends_in_failed(queue, masters):
    job_id = enqueue_synthesis(queue, "slot-a", MockProvider(), req(), 1)

    stats = run_worker(queue, Flaky(failures=99), "w1", masters)

    assert stats == {"generated": 0, "failed": 1, "retried": MAX_ATTEMPTS - 1}
    assert "CUDA out of memory" in queue.get(job_id).last_error


def test_jobs_of_other_provider_are_not_taken(queue, masters):
    class Other(MockProvider):
        name = "other"

    enqueue_synthesis(queue, "slot-a", Other(), req(), 1)

    assert run_worker(queue, MockProvider(), "w1", masters)["generated"] == 0
    assert queue.summary() == {"pending": 1}


def test_reference_changed_after_enqueue_is_not_synthesized(queue, masters, tmp_path):
    ref = tmp_path / "ref.wav"
    ref.write_bytes(b"old voice")
    job_id = enqueue_synthesis(queue, "slot-a", MockProvider(), req(reference=ref), 1)
    ref.write_bytes(b"new voice")

    stats = run_worker(queue, MockProvider(), "w1", masters)

    assert stats["failed"] == 1
    assert "fingerprint_mismatch" in queue.get(job_id).last_error
    assert not masters.exists() or not any(masters.iterdir())

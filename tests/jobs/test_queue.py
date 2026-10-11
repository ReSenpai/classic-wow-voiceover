import threading

import pytest

from voru.jobs.queue import MAX_ATTEMPTS, JobQueue, LeaseLost


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def queue(tmp_path, clock):
    return JobQueue(tmp_path / "jobs.sqlite", clock=clock)


PAYLOAD = {"text": "Привет.", "provider": "mock"}
RESULT = {"output_path": "masters/fp1.wav", "duration_ms": 1200, "sample_rate": 22050,
          "model_revision": "mock-tone-1", "elapsed_s": 0.1}


def test_empty_queue_has_nothing_to_claim(queue):
    """Регрессия legacy: при пустой выборке chunk_size становился нулём."""
    assert queue.claim("w1") is None


def test_enqueue_and_claim(queue):
    job_id = queue.enqueue("slot-a", "fp1", PAYLOAD)

    job = queue.claim("w1")

    assert job.job_id == job_id
    assert job.slot == "slot-a"
    assert job.fingerprint == "fp1"
    assert job.payload == PAYLOAD
    assert job.state == "running"
    assert job.attempts == 1
    assert queue.claim("w2") is None  # уже в работе


def test_enqueue_same_fingerprint_is_idempotent(queue):
    first = queue.enqueue("slot-a", "fp1", PAYLOAD)
    second = queue.enqueue("slot-a", "fp1", PAYLOAD)

    assert first == second
    assert queue.summary() == {"pending": 1}


def test_completed_work_is_not_redone_after_restart(tmp_path, clock):
    q1 = JobQueue(tmp_path / "jobs.sqlite", clock=clock)
    q1.enqueue("slot-a", "fp1", PAYLOAD)
    job = q1.claim("w1")
    q1.complete(job.job_id, "w1", RESULT)

    q2 = JobQueue(tmp_path / "jobs.sqlite", clock=clock)  # «перезапуск»
    q2.enqueue("slot-a", "fp1", PAYLOAD)

    assert q2.claim("w1") is None
    assert q2.summary() == {"generated": 1}


def test_complete_stores_result(queue):
    queue.enqueue("slot-a", "fp1", PAYLOAD)
    job = queue.claim("w1")

    queue.complete(job.job_id, "w1", RESULT)

    stored = queue.get(job.job_id)
    assert stored.state == "generated"
    assert stored.result == RESULT
    assert stored.lease_owner is None


def test_failure_is_retried_then_marked_failed(queue):
    queue.enqueue("slot-a", "fp1", PAYLOAD)

    for attempt in range(1, MAX_ATTEMPTS + 1):
        job = queue.claim("w1")
        assert job.attempts == attempt
        queue.fail(job.job_id, "w1", f"boom {attempt}")

    assert queue.claim("w1") is None
    failed = queue.get(job.job_id)
    assert failed.state == "failed"
    assert failed.last_error == f"boom {MAX_ATTEMPTS}"


def test_permanent_failure_is_not_retried(queue):
    queue.enqueue("slot-a", "fp1", PAYLOAD)
    job = queue.claim("w1")

    queue.fail(job.job_id, "w1", "unsupported_language", permanent=True)

    assert queue.get(job.job_id).state == "failed"
    assert queue.claim("w1") is None


def test_expired_lease_returns_job_to_queue(queue, clock):
    queue.enqueue("slot-a", "fp1", PAYLOAD)
    crashed = queue.claim("w1", lease_s=60)

    clock.now += 61
    job = queue.claim("w2")

    assert job.job_id == crashed.job_id
    assert job.attempts == 2
    assert job.lease_owner == "w2"


def test_live_lease_is_not_stolen(queue, clock):
    queue.enqueue("slot-a", "fp1", PAYLOAD)
    queue.claim("w1", lease_s=60)

    clock.now += 59

    assert queue.claim("w2") is None


def test_heartbeat_extends_lease(queue, clock):
    queue.enqueue("slot-a", "fp1", PAYLOAD)
    job = queue.claim("w1", lease_s=60)

    clock.now += 50
    queue.heartbeat(job.job_id, "w1", lease_s=60)
    clock.now += 50

    assert queue.claim("w2") is None


def test_repeated_crashes_end_in_failed(queue, clock):
    queue.enqueue("slot-a", "fp1", PAYLOAD)
    for _ in range(MAX_ATTEMPTS):
        assert queue.claim("w", lease_s=10) is not None
        clock.now += 11

    assert queue.claim("w") is None
    (job,) = queue.jobs_for_slot("slot-a")
    assert job.state == "failed"
    assert "lease expired" in job.last_error


def test_worker_that_lost_lease_cannot_complete(queue, clock):
    queue.enqueue("slot-a", "fp1", PAYLOAD)
    slow = queue.claim("w1", lease_s=10)
    clock.now += 11
    queue.claim("w2")

    with pytest.raises(LeaseLost):
        queue.complete(slow.job_id, "w1", RESULT)


def test_new_fingerprint_supersedes_unfinished_old_jobs(queue):
    old = queue.enqueue("slot-a", "fp1", PAYLOAD)
    new = queue.enqueue("slot-a", "fp2", PAYLOAD)

    assert queue.get(old).state == "superseded"
    assert queue.get(new).state == "pending"


def test_accepted_result_survives_until_new_one_is_accepted(queue):
    queue.enqueue("slot-a", "fp1", PAYLOAD)
    job = queue.claim("w1")
    queue.complete(job.job_id, "w1", RESULT)
    queue.accept(job.job_id)

    new = queue.enqueue("slot-a", "fp2", PAYLOAD)
    assert queue.get(job.job_id).state == "accepted"
    assert queue.accepted("slot-a").job_id == job.job_id

    retry = queue.claim("w1")
    queue.fail(retry.job_id, "w1", "boom", permanent=True)
    assert queue.accepted("slot-a").job_id == job.job_id  # неудача не трогает принятое

    queue.enqueue("slot-a", "fp3", PAYLOAD)
    third = queue.claim("w1")
    queue.complete(third.job_id, "w1", RESULT)
    queue.accept(third.job_id)

    assert queue.accepted("slot-a").job_id == third.job_id
    assert queue.get(job.job_id).state == "superseded"
    assert queue.get(new).state in ("failed", "superseded")


def test_result_of_stale_running_job_is_superseded(queue):
    queue.enqueue("slot-a", "fp1", PAYLOAD)
    running = queue.claim("w1")
    queue.enqueue("slot-a", "fp2", PAYLOAD)  # текст изменился, пока шёл синтез

    queue.complete(running.job_id, "w1", RESULT)

    assert queue.get(running.job_id).state == "superseded"


def test_only_generated_or_review_jobs_can_be_accepted(queue):
    job_id = queue.enqueue("slot-a", "fp1", PAYLOAD)

    with pytest.raises(ValueError, match="pending"):
        queue.accept(job_id)


@pytest.mark.parametrize("state", ["qa_failed", "review_required"])
def test_qa_states(queue, state):
    queue.enqueue("slot-a", "fp1", PAYLOAD)
    job = queue.claim("w1")
    queue.complete(job.job_id, "w1", RESULT)

    queue.set_qa_state(job.job_id, state, "тишина 4 с")

    stored = queue.get(job.job_id)
    assert stored.state == state
    assert stored.last_error == "тишина 4 с"


def test_fewer_jobs_than_workers_each_job_runs_once(tmp_path):
    """Регрессия legacy: задач меньше, чем worker'ов."""
    path = tmp_path / "jobs.sqlite"
    JobQueue(path).enqueue("slot-a", "fp1", PAYLOAD)
    claimed = []

    def worker(name):
        q = JobQueue(path)
        job = q.claim(name)
        if job:
            claimed.append(job.job_id)
            q.complete(job.job_id, name, RESULT)

    threads = [threading.Thread(target=worker, args=(f"w{i}",)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(claimed) == 1
    assert JobQueue(path).summary() == {"generated": 1}


def test_many_jobs_many_workers_no_double_claims(tmp_path):
    path = tmp_path / "jobs.sqlite"
    q = JobQueue(path)
    for i in range(30):
        q.enqueue(f"slot-{i}", f"fp{i}", PAYLOAD)
    claimed = []
    lock = threading.Lock()

    def worker(name):
        wq = JobQueue(path)
        while (job := wq.claim(name)) is not None:
            with lock:
                claimed.append(job.job_id)
            wq.complete(job.job_id, name, RESULT)

    threads = [threading.Thread(target=worker, args=(f"w{i}",)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert sorted(claimed) == sorted(set(claimed)) and len(claimed) == 30

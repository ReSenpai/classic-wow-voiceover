"""Приёмка реплик модели-победителя: страница прослушивания → decisions.json → accepted в очереди."""
import json

import pytest

from voru.config import REPO_ROOT
from voru.corpus.record import read_jsonl, write_jsonl
from voru.jobs.queue import JobQueue
from voru.pipeline import build_pilot
from voru.review.acceptance import apply_decisions, build_acceptance_page


@pytest.fixture
def corpus(tmp_path):
    records = {r.text_key: r for r in read_jsonl(REPO_ROOT / "corpus" / "pilot" / "teldrassil.jsonl")}
    path = tmp_path / "corpus.jsonl"
    write_jsonl([records[k] for k in ("quest:489:accept", "quest:997:accept", "quest:488:complete")], path)
    return path


@pytest.fixture
def work(corpus, tmp_path):
    build_pilot([corpus], "mock", work_dir=tmp_path / "work", pack=False)
    return tmp_path / "work"


def page_items(out):
    return json.loads((out / "items.json").read_text(encoding="utf-8"))


def test_page_lists_every_generated_slot_with_its_fingerprint(corpus, work, tmp_path):
    out = build_acceptance_page([corpus], "mock", work, tmp_path / "acc")

    items = page_items(out)
    queue = JobQueue(work / "jobs.sqlite")
    assert len(items) == 5
    for slot, item in items.items():
        (job,) = queue.jobs_for_slot(slot)
        assert item["fingerprint"] == job.fingerprint
        assert (out / "audio" / item["audio"]).exists()
    html = (out / "index.html").read_text(encoding="utf-8")
    assert "Зенн" in html and "decisions.json" in html


def decisions(items, verdict="accept", **override):
    result = {slot: {"fingerprint": item["fingerprint"], "verdict": verdict, "comment": ""}
              for slot, item in items.items()}
    result.update(override)
    return {"items": result}


def test_accepted_decisions_mark_jobs_accepted(corpus, work, tmp_path):
    items = page_items(build_acceptance_page([corpus], "mock", work, tmp_path / "acc"))
    rejected_slot = sorted(items)[0]
    data = decisions(items, **{rejected_slot: {"fingerprint": items[rejected_slot]["fingerprint"],
                                               "verdict": "reject", "comment": "обрыв слова"}})

    summary = apply_decisions(work, data)

    queue = JobQueue(work / "jobs.sqlite")
    assert summary.accepted == 4
    assert summary.rejected == {rejected_slot: "обрыв слова"}
    assert queue.accepted(rejected_slot) is None
    assert all(queue.accepted(s) for s in items if s != rejected_slot)


def test_decision_for_outdated_audio_is_not_applied(corpus, work, tmp_path):
    """Реплику пересинтезировали после прослушивания — старое «принять» не относится к новому звуку."""
    items = page_items(build_acceptance_page([corpus], "mock", work, tmp_path / "acc"))
    slot = sorted(items)[0]
    data = decisions(items, **{slot: {"fingerprint": "0" * 64, "verdict": "accept", "comment": ""}})

    summary = apply_decisions(work, data)

    assert summary.stale == [slot]
    assert JobQueue(work / "jobs.sqlite").accepted(slot) is None


def test_reapplying_is_idempotent(corpus, work, tmp_path):
    items = page_items(build_acceptance_page([corpus], "mock", work, tmp_path / "acc"))

    apply_decisions(work, decisions(items))
    summary = apply_decisions(work, decisions(items))

    assert summary.accepted == 0 and summary.already == 5


def test_already_accepted_slots_are_hidden_by_default(corpus, work, tmp_path):
    items = page_items(build_acceptance_page([corpus], "mock", work, tmp_path / "acc"))
    apply_decisions(work, decisions(items))

    with pytest.raises(ValueError, match="нечего слушать"):
        build_acceptance_page([corpus], "mock", work, tmp_path / "acc2")
    assert len(page_items(build_acceptance_page([corpus], "mock", work, tmp_path / "acc3", include_accepted=True))) == 5


def test_unknown_verdict_rejected(corpus, work, tmp_path):
    items = page_items(build_acceptance_page([corpus], "mock", work, tmp_path / "acc"))
    slot = sorted(items)[0]

    with pytest.raises(ValueError, match="verdict"):
        apply_decisions(work, decisions(items, **{slot: {"fingerprint": items[slot]["fingerprint"],
                                                          "verdict": "maybe", "comment": ""}}))

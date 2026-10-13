"""Страница ревью спорных сопоставлений и применение решений (дизайн CQ §7)."""
import json

import pytest

from tests.catquest.test_match import rec
from voru.catquest.match import load_overrides, match_pack
from voru.catquest.reader import read_pack
from voru.catquest.review import apply_review, build_review_page, review_key

RECORDS = [rec(900001, "accept", "Привет, путник. Лес ждет."), rec(900001, "complete", "Спасибо, $N.", sex=1),
           rec(900002, "accept", "Ты $Gготов:готова;?"), rec(900002, "complete", "Отлично. Иди.")]


@pytest.fixture
def reviewed(pack_dir, tmp_path):
    pack = read_pack(pack_dir)
    decisions = match_pack(pack, RECORDS)
    out = build_review_page(pack, pack_dir, RECORDS, decisions, tmp_path / "review")
    return pack, decisions, out


def test_page_lists_only_disputed_lines_with_audio(reviewed, pack_dir):
    _, _, out = reviewed

    items = json.loads((out / "items.json").read_text(encoding="utf-8"))
    assert list(items) == ["900002:complete:x"]
    item = items["900002:complete:x"]
    assert (item["source_text"], item["target_text"]) == ("Отлично.", "Отлично. Иди.")
    assert (out / "audio" / item["audio"]).read_bytes() == (pack_dir / "Sounds" / "q" / "900002_t.ogg").read_bytes()
    assert "Отлично. <mark>Иди</mark>." in (out / "index.html").read_text(encoding="utf-8")  # различие подсвечено


def test_nothing_to_review_is_an_error(pack_dir, tmp_path):
    pack = read_pack(pack_dir)
    exact_only = [d for d in match_pack(pack, RECORDS) if d.status == "exact"]

    with pytest.raises(ValueError):
        build_review_page(pack, pack_dir, RECORDS, exact_only, tmp_path / "review")


def decisions_for(out, verdict, comment=""):
    items = json.loads((out / "items.json").read_text(encoding="utf-8"))
    return {"items": {k: {**{h: v[h] for h in ("source_text_sha256", "target_text_sha256", "source_audio_sha256")},
                          "verdict": verdict, "comment": comment} for k, v in items.items()}}


@pytest.mark.parametrize("verdict, status", [("approve", "approved_variant"), ("reject", "content_mismatch")])
def test_applied_decision_changes_match_status(reviewed, tmp_path, verdict, status):
    pack, _, out = reviewed
    overrides = tmp_path / "overrides.yaml"
    overrides.write_text("# шапка остаётся\n[]\n", encoding="utf-8")

    summary = apply_review(decisions_for(out, verdict, "так в клиенте"), out, overrides, reviewer="тест")

    after = {d.key: d for d in match_pack(pack, RECORDS, load_overrides(overrides))}
    assert after[(900002, "complete", None)].status == status
    assert summary == {"applied": 1, "stale": [], "undecided": 0}
    assert overrides.read_text(encoding="utf-8").startswith("# шапка остаётся\n")
    assert load_overrides(overrides)[(900002, "complete", None)]["reason"] == "так в клиенте"


def test_decision_about_other_audio_is_stale(reviewed, tmp_path):
    _, _, out = reviewed
    decisions = decisions_for(out, "approve")
    decisions["items"]["900002:complete:x"]["source_audio_sha256"] = "0" * 64
    overrides = tmp_path / "overrides.yaml"

    summary = apply_review(decisions, out, overrides, reviewer="тест")

    assert summary["stale"] == ["900002:complete:x"]
    assert load_overrides(overrides) == {}


def test_new_decision_replaces_old_one(reviewed, tmp_path):
    _, _, out = reviewed
    overrides = tmp_path / "overrides.yaml"
    apply_review(decisions_for(out, "reject"), out, overrides, reviewer="тест")

    apply_review(decisions_for(out, "approve"), out, overrides, reviewer="тест")

    assert load_overrides(overrides)[(900002, "complete", None)]["decision"] == "approved_variant"


def test_undecided_are_counted(reviewed, tmp_path):
    _, _, out = reviewed

    summary = apply_review(decisions_for(out, None), out, tmp_path / "o.yaml", reviewer="тест")

    assert summary == {"applied": 0, "stale": [], "undecided": 1}


def test_key_format():
    assert review_key(1, "accept", None) == "1:accept:x"
    assert review_key(1, "complete", "f") == "1:complete:f"

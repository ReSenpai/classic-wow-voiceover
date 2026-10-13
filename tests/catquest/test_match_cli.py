"""Ручные решения (mapping-overrides.yaml) и CLI match (дизайн CQ §7, §13)."""
import json

import pytest

from tests.catquest.test_match import rec
from voru.catquest.match import OVERRIDES_PATH, load_overrides, main
from voru.corpus.record import write_jsonl

ENTRY = """- quest_id: 1
  stage: accept
  player_gender: null
  source_text_sha256: a
  target_text_sha256: b
  source_audio_sha256: c
  decision: approved_variant
  reason: клиент пишет «Дарнасс»
  reviewer: пользователь
"""


def test_overrides_load(tmp_path):
    path = tmp_path / "o.yaml"
    path.write_text(ENTRY, encoding="utf-8")

    assert load_overrides(path)[(1, "accept", None)]["decision"] == "approved_variant"


@pytest.mark.parametrize("body", [
    ENTRY + ENTRY,
    ENTRY.replace("approved_variant", "exact"),
    ENTRY.replace("  reviewer: пользователь\n", ""),
])
def test_bad_overrides_rejected(tmp_path, body):
    path = tmp_path / "o.yaml"
    path.write_text(body, encoding="utf-8")

    with pytest.raises(ValueError):
        load_overrides(path)


def test_repo_overrides_are_valid():
    assert isinstance(load_overrides(OVERRIDES_PATH), dict)


@pytest.fixture
def target(tmp_path):
    path = tmp_path / "target.jsonl"
    write_jsonl([rec(900001, "accept", "Привет, путник. Лес ждет."), rec(900001, "complete", "Спасибо, $N.", sex=1),
                 rec(900002, "accept", "Ты $Gготов:готова;?"), rec(900002, "complete", "Отлично. Иди.")], path)
    return path


def test_cli_writes_mapping_and_summary(pack_zip, target, tmp_path, capsys):
    out = tmp_path / "report"

    main(["--source", str(pack_zip), "--target", str(target), "--report", str(out), "--no-lock",
          "--overrides", str(tmp_path / "none.yaml")])

    mapping = [json.loads(l) for l in (out / "mapping.jsonl").read_text(encoding="utf-8").splitlines()]
    summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    by_key = {(m["quest_id"], m["stage"], m["player_gender"]): m for m in mapping}
    assert by_key[(900001, "accept", None)]["status"] == "exact"
    assert by_key[(900002, "accept", "f")]["status"] == "exact"
    assert by_key[(900002, "complete", None)]["status"] == "needs_review"
    assert by_key[(900002, "complete", None)]["diff"] == [["иди", ""]]
    assert by_key[(900003, "complete", "m")]["status"] == "target_missing"
    assert summary["by_status"] == {"exact": 4, "needs_review": 1, "target_missing": 2}
    assert summary["target_quests"] == 2
    assert "exact: 4" in capsys.readouterr().out


def test_cli_can_limit_to_target_quests(pack_zip, target, tmp_path):
    out = tmp_path / "report"

    main(["--source", str(pack_zip), "--target", str(target), "--report", str(out), "--no-lock", "--target-only",
          "--overrides", str(tmp_path / "none.yaml")])

    summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert summary["by_status"] == {"exact": 4, "needs_review": 1}

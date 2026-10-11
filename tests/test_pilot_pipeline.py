"""Интеграция: корпус → подготовка → кастинг → очередь → mock TTS → пак (дизайн §14)."""
import dataclasses
import json

import pytest

from voru.config import REPO_ROOT
from voru.corpus.record import read_jsonl, write_jsonl
from voru.pipeline import MODULE_NAME, build_pilot

PILOT = REPO_ROOT / "corpus" / "pilot" / "teldrassil.jsonl"


@pytest.fixture
def subset(tmp_path):
    """Несколько реплик пилота: варианты пола, правка из overrides, разные голоса."""
    records = {r.text_key: r for r in read_jsonl(PILOT)}
    keys = ["quest:489:accept", "quest:997:accept", "quest:488:complete"]
    path = tmp_path / "corpus.jsonl"
    write_jsonl([records[k] for k in keys], path)
    return path


def run(corpus, tmp_path, **kwargs):
    return build_pilot(corpus, provider_name="mock", work_dir=tmp_path / "work",
                       out_dir=tmp_path / "packs", version="0.0.1-test", **kwargs)


def test_subset_builds_pack(subset, tmp_path):
    report = run(subset, tmp_path, allow_unreviewed=True)

    pack = tmp_path / "packs" / MODULE_NAME
    manifest = json.loads((pack / "manifest.json").read_text(encoding="utf-8"))
    names = sorted(p.stem for p in (pack / "generated" / "sounds" / "quests").iterdir())

    assert report.blocked == {}
    assert report.casting_errors == {}
    assert names == ["488-complete", "f-489-accept", "f-997-accept", "m-489-accept", "m-997-accept"]
    assert manifest["coverage"]["files"] == 5
    assert {v for v in manifest["voices"]} == {"nightelf-female-calm", "satyr-male"}
    assert report.stats["generated"] == 5


def test_rerun_does_not_resynthesize(subset, tmp_path):
    run(subset, tmp_path, allow_unreviewed=True)

    report = run(subset, tmp_path, allow_unreviewed=True)

    assert report.stats["generated"] == 0
    assert report.files == 5


def test_blocked_and_uncast_lines_are_reported_not_dropped_silently(subset, tmp_path):
    records = read_jsonl(subset)
    satyr = next(r for r in records if r.npc_id == 2150)
    unknown = dataclasses.replace(satyr, content_id="quest:1:accept:creature:99999", text_key="quest:1:accept",
                                  quest_id=1, stage="accept", npc_id=99999, npc_name="Лесной огонек",
                                  raw_text="Ш-ш-ш... лес слушает.")
    broken = dataclasses.replace(satyr, content_id="quest:2:accept:creature:2150", text_key="quest:2:accept",
                                 quest_id=2, stage="accept", raw_text="Ты похож на $c.")
    path = tmp_path / "corpus2.jsonl"
    write_jsonl([*records, unknown, broken], path)

    report = run(path, tmp_path, allow_unreviewed=True)

    assert report.casting_errors == {"quest:1:accept:creature:99999": "no_voice"}
    assert report.blocked == {"quest:2:accept": "needs_override"}
    assert report.files == 5


def test_several_corpora_in_one_pack_with_shared_lines(subset, tmp_path):
    records = read_jsonl(subset)
    other = tmp_path / "other.jsonl"
    write_jsonl(records[:1], other)  # та же реплика в двух корпусах — не дубль и не коллизия

    report = build_pilot([subset, other], provider_name="mock", work_dir=tmp_path / "work",
                         out_dir=tmp_path / "packs", version="0.0.1-test", allow_unreviewed=True)

    assert report.files == 5


def test_unreviewed_audio_is_not_exported_by_default(subset, tmp_path):
    report = run(subset, tmp_path)

    assert report.files == 0
    assert report.pack_dir is None
    assert not (tmp_path / "packs" / MODULE_NAME).exists()

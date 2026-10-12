"""Интеграция: корпус → подготовка → кастинг → очередь → mock TTS → пак (дизайн §14)."""
import dataclasses
import json

import pytest

from voru.config import REPO_ROOT
from voru.corpus.record import read_jsonl, write_jsonl
from voru.pipeline import MODULE_NAME, build_pilot
from voru.providers.mock import MockProvider

PILOT = REPO_ROOT / "corpus" / "pilot" / "teldrassil.jsonl"


@pytest.fixture
def subset(tmp_path):
    """Несколько реплик пилота: варианты пола, правка из overrides, разные голоса."""
    records = {r.text_key: r for r in read_jsonl(PILOT)}
    keys = ["quest:489:accept", "quest:997:accept", "quest:488:complete"]
    path = tmp_path / "corpus.jsonl"
    write_jsonl([records[k] for k in keys], path)
    return path


def run(corpus, tmp_path, provider_name="mock", **kwargs):
    return build_pilot(corpus, provider_name=provider_name, work_dir=tmp_path / "work",
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

    report = run(path, tmp_path, allow_unreviewed=True, accent=False)  # синтетические тексты не в кэше

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


class MockB(MockProvider):
    name = "mock-b"


@pytest.fixture
def two_providers(monkeypatch):
    import voru.providers

    monkeypatch.setitem(voru.providers._REGISTRY, "mock-b", f"{__name__}:MockB")


def test_two_providers_do_not_supersede_each_other(subset, tmp_path, two_providers):
    from voru.jobs.queue import JobQueue

    run(subset, tmp_path, pack=False)
    report = run(subset, tmp_path, pack=False, provider_name="mock-b")

    assert report.stats["generated"] == 5
    assert JobQueue(tmp_path / "work" / "jobs.sqlite").summary() == {"generated": 10}


def test_take_reseeds_only_listed_slot(subset, tmp_path):
    """Брак модели, найденный на слух (обрыв слова, пропуск), лечится новым дублем одного слота."""
    from voru.pipeline import TAKE_SEED_STEP, Report, plan

    takes = tmp_path / "takes.yaml"
    takes.write_text("- slot: mock:quest:489:accept:creature:2083|f\n  take: 2\n  reason: обрыв слова\n",
                     encoding="utf-8")

    before = {p.slot: p.request.generation_config["seed"] for p in plan(subset, "mock", Report())}
    after = {p.slot: p.request.generation_config["seed"] for p in plan(subset, "mock", Report(), takes=takes)}

    changed = {slot for slot in before if before[slot] != after[slot]}
    assert changed == {"mock:quest:489:accept:creature:2083|f"}
    assert after["mock:quest:489:accept:creature:2083|f"] == before["mock:quest:489:accept:creature:2083|f"] \
        + 2 * TAKE_SEED_STEP


def test_unused_takes_of_this_provider_are_reported(subset, tmp_path):
    """Опечатка в слоте не должна молча ничего не делать; дубли других моделей не мешают."""
    from voru.pipeline import Report, plan

    takes = tmp_path / "takes.yaml"
    takes.write_text("- slot: mock:quest:1:accept:creature:1|-\n  take: 1\n  reason: опечатка\n"
                     "- slot: other:quest:489:accept:creature:2083|f\n  take: 1\n  reason: другая модель\n",
                     encoding="utf-8")
    report = Report()

    plan(subset, "mock", report, takes=takes)

    assert report.unused_takes == ["mock:quest:1:accept:creature:1|-"]


@pytest.mark.parametrize("body", [
    "- slot: mock:q|f\n  take: 0\n  reason: x\n",
    "- slot: mock:q|f\n  take: 1\n",
    "- slot: mock:q|f\n  take: 1\n  reason: x\n- slot: mock:q|f\n  take: 2\n  reason: y\n",
])
def test_invalid_takes_rejected(tmp_path, body):
    from voru.pipeline import load_takes

    path = tmp_path / "takes.yaml"
    path.write_text(body, encoding="utf-8")

    with pytest.raises(ValueError):
        load_takes(path)


def test_repo_takes_file_is_valid():
    from voru.pipeline import TAKES, load_takes

    assert isinstance(load_takes(TAKES), dict)


# --- реплики, записанные человеком (преобразование голоса) ---

class MockVc(MockProvider):
    """Как seed-vc: принимает запись в generation_config."""
    name = "mock-vc"
    default_capabilities = dataclasses.replace(
        MockProvider.default_capabilities,
        config_keys=MockProvider.default_capabilities.config_keys | {"source_audio", "source_sha256"})


@pytest.fixture
def recorded(tmp_path, monkeypatch):
    """Сатир (2150) записан человеком: 488-complete есть, 488-accept-m/f — нет.
    Записи лежат в <рабочая папка>/recordings/satyr-male, как у настоящего запуска."""
    import voru.pipeline
    import voru.providers
    from voru.casting import load_casting

    monkeypatch.setitem(voru.providers._REGISTRY, "mock-vc", f"{__name__}:MockVc")
    monkeypatch.setattr(voru.pipeline, "RECORDED_PROVIDERS", {"seed-vc", "mock-vc"})
    rec = tmp_path / "work" / "recordings" / "satyr-male"
    rec.parent.mkdir(parents=True)
    rec.mkdir()
    import wave
    with wave.open(str(rec / "488-complete.wav"), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(24000)
        w.writeframes(b"\x00\x20" * 24000)
    casting = load_casting()
    satyr = dataclasses.replace(casting.voices["satyr-male"], recordings="satyr-male")
    return dataclasses.replace(casting, voices={**casting.voices, "satyr-male": satyr}), rec


def test_recordings_are_ignored_without_recordings_root(subset, recorded):
    from voru.pipeline import Report, plan

    casting, _ = recorded

    assert len(plan(subset, "mock", Report(), casting)) == 5
    assert plan(subset, "mock-vc", Report(), casting) == []


def test_recorded_lines_go_to_voice_conversion(subset, recorded):
    import hashlib

    from voru.pipeline import Report, plan

    casting, rec = recorded
    report = Report()

    items = plan(subset, "mock-vc", report, casting, recordings_root=rec.parent)

    assert [i.slot for i in items] == ["mock-vc:quest:488:complete:creature:2150|-"]
    config = items[0].request.generation_config
    assert config["source_audio"] == str(rec / "488-complete.wav")
    assert config["source_sha256"] == hashlib.sha256((rec / "488-complete.wav").read_bytes()).hexdigest()
    assert report.missing_recordings == []  # в subset у сатира только 488-complete


def test_tts_skips_recorded_lines_but_keeps_the_rest(subset, recorded):
    from voru.pipeline import Report, plan

    casting, rec = recorded
    report = Report()

    slots = [i.slot for i in plan(subset, "mock", report, casting, recordings_root=rec.parent)]

    assert "mock:quest:488:complete:creature:2150|-" not in slots
    assert len(slots) == 4
    assert report.recorded == ["quest:488:complete:creature:2150|-"]


def test_voice_with_recordings_reports_missing_ones(subset, recorded, tmp_path):
    from voru.corpus.record import read_jsonl, write_jsonl
    from voru.pipeline import PILOT_CORPUS, Report, plan

    casting, rec = recorded
    satyr_lines = [r for r in read_jsonl(PILOT_CORPUS) if r.npc_id == 2150]
    path = tmp_path / "satyr.jsonl"
    write_jsonl(satyr_lines, path)
    report = Report()

    plan(path, "mock-vc", report, casting, recordings_root=rec.parent)

    assert report.missing_recordings == ["488-accept-f", "488-accept-m", "489-complete"]


def test_pack_combines_tts_and_recorded_lines(subset, recorded, tmp_path, monkeypatch):
    import voru.pipeline

    casting, _ = recorded
    monkeypatch.setattr(voru.pipeline, "load_casting", lambda: casting)
    for name in ("mock", "mock-vc"):
        run(subset, tmp_path, provider_name=name, pack=False)

    report = voru.pipeline.assemble_pack([subset], ["mock", "mock-vc"], work_dir=tmp_path / "work",
                                         out_dir=tmp_path / "packs", version="0.0.1-test", allow_unreviewed=True)

    assert report.files == 5
    manifest = json.loads((tmp_path / "packs" / MODULE_NAME / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["coverage"]["files"] == 5


def test_synthesis_without_pack(subset, tmp_path):
    report = run(subset, tmp_path, pack=False, allow_unreviewed=True)

    assert report.stats["generated"] == 5
    assert report.pack_dir is None
    assert not (tmp_path / "packs").exists()

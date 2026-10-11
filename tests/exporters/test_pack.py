import hashlib
import json
from pathlib import Path

import pytest

from voru.config import load_client_profile
from voru.exporters.pack import CollisionError, PackEntry, PackInfo, build_pack, file_key
from voru.providers.base import SynthesisRequest, VoiceRef
from voru.providers.mock import MockProvider
from tests.lua.wow import WowLua, parse_toc

MODULE = "AI_VoiceOverData_Vanilla_RU"
INFO = PackInfo(module_name=MODULE, title="VoiceOver Data - Vanilla (RU)", version="0.1.0-pilot",
                client=load_client_profile(), priority=200)
CREDITS = {
    "nightelf-male-calm": {"provenance": "mock", "license": "test"},
    "nightelf-female-calm": {"provenance": "mock", "license": "test"},
}


def master(tmp_path, name, text, voice_id="nightelf-male-calm"):
    request = SynthesisRequest(text=text, locale="ruRU", player_gender=None,
                               voice=VoiceRef(voice_id, "1", None, None), delivery_profile="neutral",
                               generation_config={"seed": 1}, output_path=tmp_path / "masters" / f"{name}.wav")
    return MockProvider().synthesize(request).path


def entry(tmp_path, quest_id, stage, gender=None, npc_id=3693, npc_name="Баритас Лунный Сумрак",
          npc_type="creature", voice_id="nightelf-male-calm", fingerprint=None, text="Текст реплики."):
    key = f"{quest_id}-{stage}"
    fk = f"{gender}-{key}" if gender else key
    fp = fingerprint or hashlib.sha256(f"{fk}|{npc_id}|{text}".encode()).hexdigest()
    return PackEntry(
        content_id=f"quest:{quest_id}:{stage}:{npc_type}:{npc_id}", text_key=f"quest:{quest_id}:{stage}",
        file_key=fk, quest_id=quest_id, stage=stage, npc_type=npc_type, npc_id=npc_id, npc_name=npc_name,
        voice_id=voice_id, fingerprint=fp, master_path=master(tmp_path, fp[:12], text, voice_id),
    )


@pytest.fixture
def entries(tmp_path):
    return [
        entry(tmp_path, 947, "accept"),
        entry(tmp_path, 476, "accept", "m", npc_id=2080, npc_name="Деналан", text="Ты готов?"),
        entry(tmp_path, 476, "accept", "f", npc_id=2080, npc_name="Деналан", text="Ты готова?"),
        entry(tmp_path, 476, "complete", npc_id=2078, npc_name="Атридас Медвежья Шкура"),
        entry(tmp_path, 4, "accept", npc_type="item", npc_id=5179, npc_name="Сердце, поросшее мхом"),
    ]


@pytest.fixture
def pack(tmp_path, entries):
    build_pack(entries, tmp_path / "out", INFO, CREDITS)
    return tmp_path / "out" / MODULE


def lua_table(path: Path, wow=None):
    """Исполняет файл таблицы в Lua и возвращает её как dict."""
    wow = wow or WowLua()
    wow.lua.execute(f"{MODULE} = {{}}")
    wow.lua.execute(path.read_text(encoding="utf-8"))
    return wow.lua.globals()[MODULE]


def to_py(t):
    return {k: to_py(v) if hasattr(v, "items") else v for k, v in t.items()}


def test_file_key():
    assert file_key("947-accept", None) == "947-accept"
    assert file_key("947-accept", "m") == "m-947-accept"
    assert file_key("947-accept", "f") == "f-947-accept"


def test_layout(pack):
    sounds = sorted(p.name for p in (pack / "generated" / "sounds" / "quests").iterdir())

    assert sounds == ["4-accept.ogg", "476-complete.ogg", "947-accept.ogg", "f-476-accept.ogg", "m-476-accept.ogg"]
    assert (pack / f"{MODULE}.toc").exists()
    assert (pack / "Module.lua").exists()
    assert (pack / "manifest.json").exists()


def test_toc_metadata(pack):
    metadata, files = parse_toc(pack / f"{MODULE}.toc")

    assert metadata["Interface"] == "11509"
    assert metadata["Version"] == "0.1.0-pilot"
    assert metadata["LoadOnDemand"] == "1"
    assert metadata["RequiredDeps"] == "AI_VoiceOver"
    assert metadata["X-VoiceOver-DataModule-Version"] == "1"
    assert metadata["X-VoiceOver-DataModule-Priority"] == "200"
    assert files[0] == "Module.lua"
    for relative in files:
        assert (pack / relative.replace("\\", "/")).exists(), relative


def test_toc_notes_describe_real_rollback(pack):
    """VoiceOver грузит data-модули даже выключенными (FORCE_ENABLE_DISABLED_MODULES) —
    откат только удалением папки; описание не должно обещать «просто отключите»."""
    metadata, _ = parse_toc(pack / f"{MODULE}.toc")

    assert "удалите папку" in metadata["Notes"]
    assert "Можно отключить" not in metadata["Notes"]


def test_sound_length_table_matches_manifest(pack):
    lengths = to_py(lua_table(pack / "generated" / "sound_length_table.lua").SoundLengthLookupByFileName)
    manifest = json.loads((pack / "manifest.json").read_text(encoding="utf-8"))

    assert set(lengths) == {"947-accept", "m-476-accept", "f-476-accept", "476-complete", "4-accept"}
    for name, info in manifest["files"].items():
        key = Path(name).stem
        assert lengths[key] == pytest.approx(info["duration_s"], abs=0.001)


def test_questlog_and_name_lookups(pack):
    module = lua_table(pack / "generated" / "questlog_npc_lookups.lua")
    names = lua_table(pack / "generated" / "npc_name_lookups.lua")

    assert to_py(module.NPCIDLookupByQuestID) == {947: 3693, 476: 2080}
    assert to_py(module.ItemIDLookupByQuestID) == {4: 5179}
    assert to_py(module.ObjectIDLookupByQuestID) == {}
    assert to_py(names.NPCNameLookupByNPCID) == {3693: "Баритас Лунный Сумрак", 2080: "Деналан",
                                                2078: "Атридас Медвежья Шкура"}
    assert to_py(names.ItemNameLookupByItemID) == {5179: "Сердце, поросшее мхом"}


def test_manifest(pack, entries):
    manifest = json.loads((pack / "manifest.json").read_text(encoding="utf-8"))

    assert manifest["module"] == MODULE
    assert manifest["locale"] == "ruRU"
    assert manifest["client_build"] == 70003
    assert manifest["priority"] == 200
    assert manifest["coverage"] == {"files": 5, "quests": 3, "accept": 4, "complete": 1}
    assert manifest["voices"] == {"nightelf-male-calm": {"provenance": "mock", "license": "test"}}
    for name, info in manifest["files"].items():
        assert hashlib.sha256((pack / name).read_bytes()).hexdigest() == info["sha256"]
        assert info["fingerprint"] in {e.fingerprint for e in entries}


def test_build_is_deterministic(tmp_path, entries):
    build_pack(entries, tmp_path / "a", INFO, CREDITS)
    build_pack(entries, tmp_path / "b", INFO, CREDITS)

    for path in (tmp_path / "a" / MODULE).rglob("*"):
        if path.is_file():
            other = tmp_path / "b" / MODULE / path.relative_to(tmp_path / "a" / MODULE)
            assert path.read_bytes() == other.read_bytes(), path.name


def test_rebuild_removes_stale_files(tmp_path, entries):
    build_pack(entries, tmp_path / "out", INFO, CREDITS)
    build_pack(entries[:1], tmp_path / "out", INFO, CREDITS)

    sounds = [p.name for p in (tmp_path / "out" / MODULE / "generated" / "sounds" / "quests").iterdir()]
    assert sounds == ["947-accept.ogg"]
    assert [p.name for p in (tmp_path / "out").iterdir()] == [MODULE]


def test_failed_build_keeps_previous_pack(tmp_path, entries):
    build_pack(entries, tmp_path / "out", INFO, CREDITS)
    broken = entries[0].__class__(**{**entries[0].__dict__, "master_path": tmp_path / "missing.wav"})

    with pytest.raises(Exception):
        build_pack([broken], tmp_path / "out", INFO, CREDITS)

    assert (tmp_path / "out" / MODULE / "generated" / "sounds" / "quests" / "m-476-accept.ogg").exists()


def test_unknown_voice_credit_is_an_error(tmp_path, entries):
    with pytest.raises(ValueError, match="nightelf-male-calm"):
        build_pack(entries, tmp_path / "out", INFO, {})


# --- коллизии quest-stage между NPC (дизайн §11) ---

def test_collision_between_speakers_is_detected(tmp_path):
    a = entry(tmp_path, 100, "accept", npc_id=1, npc_name="A")
    b = entry(tmp_path, 100, "accept", npc_id=2, npc_name="B", voice_id="nightelf-female-calm")

    with pytest.raises(CollisionError) as err:
        build_pack([a, b], tmp_path / "out", INFO, CREDITS)

    assert "100-accept" in str(err.value)
    assert a.content_id in str(err.value) and b.content_id in str(err.value)


def test_collision_resolved_explicitly(tmp_path):
    a = entry(tmp_path, 100, "accept", npc_id=1, npc_name="A")
    b = entry(tmp_path, 100, "accept", npc_id=2, npc_name="B", voice_id="nightelf-female-calm")

    manifest = build_pack([a, b], tmp_path / "out", INFO, CREDITS, resolutions={"100-accept": b.content_id})

    info = manifest["files"]["generated/sounds/quests/100-accept.ogg"]
    assert info["content_id"] == b.content_id
    assert manifest["collisions"] == {"100-accept": {"chosen": b.content_id, "dropped": [a.content_id]}}


def test_identical_audio_is_not_a_collision(tmp_path):
    a = entry(tmp_path, 100, "accept", npc_id=1, fingerprint="f" * 64)
    b = entry(tmp_path, 100, "accept", npc_id=2, fingerprint="f" * 64)

    manifest = build_pack([a, b], tmp_path / "out", INFO, CREDITS)

    assert len(manifest["files"]) == 1


# --- как в игре: новый пак поверх старого ---

def test_new_pack_overrides_legacy_pack_in_addon(pack):
    wow = WowLua()
    wow.register_legacy_module("AI_VoiceOverData_Vanilla", 100, {"476-accept": 20.0, "10-accept": 5.0})
    wow.install_addon(pack)
    wow.set_player_sex(3)  # женский персонаж

    found, sound = wow.prepare_quest_sound("QuestAccept", 476)
    assert found
    assert sound.filePath == rf"Interface\AddOns\{MODULE}\generated\sounds\quests\f-476-accept.ogg"

    found, sound = wow.prepare_quest_sound("QuestAccept", 10)  # нет в пилоте — старый пак
    assert found
    assert sound.module.METADATA.AddonName == "AI_VoiceOverData_Vanilla"

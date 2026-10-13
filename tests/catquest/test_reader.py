"""Reader пака CatQuest Voices 0.6.x (дизайн CQ §5–6)."""
import hashlib
import zipfile

import pytest

from tests.catquest.conftest import FILES, INDEX, INDEX_JSON, write_pack, zip_dir
from voru.catquest.reader import UnsupportedSchema, read_pack


def lines_by_key(pack):
    return {(l.quest_id, l.stage, l.player_gender): l for l in pack.lines}


@pytest.mark.parametrize("source", ["pack_dir", "pack_zip"])
def test_reads_directory_and_zip_the_same(source, request):
    pack = read_pack(request.getfixturevalue(source))

    assert pack.version == "0.6.1"
    assert sorted(lines_by_key(pack)) == [
        (900001, "accept", None), (900001, "complete", None),
        (900002, "accept", "f"), (900002, "accept", "m"), (900002, "complete", None),
        (900003, "complete", "f"), (900003, "complete", "m"),
    ]


def test_file_names_follow_catquest_player_gender_rules(pack_dir):
    lines = lines_by_key(read_pack(pack_dir))

    assert lines[(900001, "accept", None)].source_path == "Sounds/q/900001.ogg"
    assert lines[(900001, "complete", None)].source_path == "Sounds/q/900001_t.ogg"
    assert lines[(900002, "accept", "m")].source_path == "Sounds/q/900002_m.ogg"
    assert lines[(900003, "complete", "f")].source_path == "Sounds/q/900003_t_f.ogg"


def test_complete_has_its_own_metadata(pack_dir):
    lines = lines_by_key(read_pack(pack_dir))
    accept, complete = lines[(900001, "accept", None)], lines[(900001, "complete", None)]

    assert (accept.voice, accept.index_duration, accept.model) == ("nightelf-male", 3.5, "eleven_v4")
    assert (complete.voice, complete.index_duration, complete.model) == ("nightelf-female", 2.0, None)


def test_text_is_joined_from_cues_of_its_variant(pack_dir):
    lines = lines_by_key(read_pack(pack_dir))

    assert lines[(900001, "accept", None)].text == "Привет, путник. Лес ждёт."
    assert lines[(900002, "accept", "f")].text == "Ты готова?"
    assert lines[(900003, "complete", "m")].text == "Молодец."


def test_audio_hash_is_recorded(pack_dir):
    line = lines_by_key(read_pack(pack_dir))[(900001, "accept", None)]

    assert line.audio_sha256 == hashlib.sha256(b"OggS900001.ogg").hexdigest()


def test_missing_and_unused_audio_are_reported(tmp_path):
    src = write_pack(tmp_path, files=[f for f in FILES if f != "900002_f.ogg"], extra=["777.ogg"])

    pack = read_pack(src)
    missing = lines_by_key(pack)[(900002, "accept", "f")]

    assert missing.audio_sha256 is None
    assert pack.missing_audio == ["Sounds/q/900002_f.ogg"]
    assert pack.unused_audio == ["Sounds/q/777.ogg", "Sounds/q/900004_t.ogg"]


def test_index_lua_is_what_plays_json_only_quests_are_reported(pack_dir):
    """CatQuest играет только Index.lua: записи из одного index.json не переносим, но показываем."""
    pack = read_pack(pack_dir)

    assert 900004 not in {l.quest_id for l in pack.lines}
    assert pack.json_only_quests == [900004]


def test_index_json_disagreeing_with_index_lua_is_rejected(tmp_path):
    broken = {**INDEX_JSON, "900001": {**INDEX_JSON["900001"], "d": 9.9}}

    with pytest.raises(UnsupportedSchema, match="index.json.*900001"):
        read_pack(write_pack(tmp_path, index_json=broken))


def test_index_json_is_required(tmp_path):
    with pytest.raises(UnsupportedSchema, match="index.json"):
        read_pack(write_pack(tmp_path, index_json=None))


def test_archive_hash_is_recorded_for_zip(pack_zip):
    pack = read_pack(pack_zip)

    assert pack.source_sha256 == hashlib.sha256(pack_zip.read_bytes()).hexdigest()


@pytest.mark.parametrize("version", ["0.5.9", "0.7.0", "1.0"])
def test_unknown_version_is_rejected(tmp_path, version):
    with pytest.raises(UnsupportedSchema, match=version):
        read_pack(write_pack(tmp_path, version=version))


@pytest.mark.parametrize("old, new, reason", [
    ("n = { x = 20 },", "n = { x = 20 }, zz = 1,", "zz"),
    ("[900001] =", '["abc"] =', "quest id"),
    ("d = 3.5,", 'd = "3.5",', "d"),
    ("g = 1, v", "g = 2, v", "g"),
    ('c = { m = { { 0.00, "Ты готов?" } }, f', 'c = { x = { { 0.00, "Ты готов?" } }, f', "c"),
    ("CatQuestVoicePack.quests = {", "CatQuestVoicePack.other = {", "quests"),
])
def test_unexpected_schema_is_rejected_not_partially_read(tmp_path, old, new, reason):
    assert old in INDEX

    with pytest.raises(UnsupportedSchema, match=reason):
        read_pack(write_pack(tmp_path, index=INDEX.replace(old, new, 1)))


def test_zip_paths_must_stay_inside(tmp_path, pack_dir):
    archive = zip_dir(pack_dir, tmp_path / "evil.zip")
    with zipfile.ZipFile(archive, "a") as z:
        z.writestr("CatQuest_Voices/../../escape.ogg", b"x")

    with pytest.raises(UnsupportedSchema, match="escape.ogg"):
        read_pack(archive)

import pytest

from tests.lua.wow import WowLua


@pytest.fixture
def wow():
    return WowLua()


@pytest.mark.parametrize("sex, expected", [(2, "m-947-accept"), (3, "f-947-accept"), (1, "947-accept")])
def test_player_gender_prefix(wow, sex, expected):
    wow.set_player_sex(sex)

    assert wow.vo.DataModules.AddPlayerGenderToFilename(wow.vo.DataModules, "947-accept") == expected


def test_prepare_sound_prefers_gendered_file(wow):
    wow.set_player_sex(3)
    wow.register_module("TestPack", {"947-accept": 34.6, "f-947-accept": 30.0})

    found, sound = wow.prepare_quest_sound("QuestAccept", 947)

    assert found
    assert sound.fileName == "f-947-accept"
    assert sound.filePath == r"Interface\AddOns\TestPack\f-947-accept.ogg"
    assert sound.length == 30.0


def test_prepare_sound_falls_back_to_neutral_file(wow):
    wow.set_player_sex(2)
    wow.register_module("TestPack", {"947-accept": 34.6})

    found, sound = wow.prepare_quest_sound("QuestAccept", 947)

    assert found
    assert sound.fileName == "947-accept"


def test_prepare_sound_reports_missing(wow):
    wow.set_player_sex(2)
    wow.register_module("TestPack", {})

    found, _ = wow.prepare_quest_sound("QuestAccept", 947)

    assert not found

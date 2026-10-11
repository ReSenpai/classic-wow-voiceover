import json

import pytest

from voru.config import ClientProfile
from voru.corpus.record import (
    SCHEMA_VERSION,
    SourceRecord,
    addon_key,
    read_jsonl,
    record_from_row,
    write_jsonl,
)

CLIENT = ClientProfile(flavor="vanilla", version="1.15.9", build=70003, interface=11509, locale="ruRU")
REVISION = "vmangos-db-4641790"


def row(**overrides):
    base = {
        "quest_id": 947,
        "quest_title_en": "Cave Mushrooms",
        "quest_title_ru": "Грибы из пещеры",
        "zone_id": 148,
        "stage": "accept",
        "npc_type": "creature",
        "npc_id": 3693,
        "npc_name_en": "Barithras Moonshade",
        "npc_name_ru": "Баритас Лунный Сумрак",
        "npc_race_id": 4,
        "npc_sex_id": 0,
        "text_en": "Please, $N, gather these mushrooms.",
        "text_ru": "Прошу вас, $N, соберите для меня эти грибы.",
    }
    base.update(overrides)
    return base


def test_record_from_row():
    record = record_from_row(row(), CLIENT, REVISION)

    assert record == SourceRecord(
        schema_version=SCHEMA_VERSION,
        content_id="quest:947:accept:creature:3693",
        text_key="quest:947:accept",
        client_flavor="vanilla",
        client_build=70003,
        locale="ruRU",
        quest_id=947,
        quest_title="Грибы из пещеры",
        zone_id=148,
        stage="accept",
        npc_type="creature",
        npc_id=3693,
        npc_name="Баритас Лунный Сумрак",
        npc_race_id=4,
        npc_sex_id=0,
        speaker_type="npc",
        raw_text="Прошу вас, $N, соберите для меня эти грибы.",
        raw_text_en="Please, $N, gather these mushrooms.",
        source_ref="quest_template.Details / locales_quest.Details_loc8",
        source_revision=REVISION,
        locale_status="ok",
    )


@pytest.mark.parametrize("text_ru", [None, "", "  "])
def test_missing_russian_text_is_not_replaced_by_english(text_ru):
    record = record_from_row(row(text_ru=text_ru), CLIENT, REVISION)

    assert record.raw_text is None
    assert record.locale_status == "missing_locale"
    assert record.raw_text_en == "Please, $N, gather these mushrooms."


def test_missing_russian_names_stay_empty():
    record = record_from_row(row(npc_name_ru=None, quest_title_ru=""), CLIENT, REVISION)

    assert record.npc_name is None
    assert record.quest_title is None


@pytest.mark.parametrize("stage, ref", [
    ("accept", "quest_template.Details / locales_quest.Details_loc8"),
    ("progress", "quest_template.RequestItemsText / locales_quest.RequestItemsText_loc8"),
    ("complete", "quest_template.OfferRewardText / locales_quest.OfferRewardText_loc8"),
])
def test_source_ref_names_exact_columns(stage, ref):
    assert record_from_row(row(stage=stage), CLIENT, REVISION).source_ref == ref


@pytest.mark.parametrize("npc_type, speaker", [("creature", "npc"), ("gameobject", "narrator"), ("item", "narrator")])
def test_speaker_type(npc_type, speaker):
    assert record_from_row(row(npc_type=npc_type), CLIENT, REVISION).speaker_type == speaker


def test_invalid_stage_rejected():
    with pytest.raises(ValueError, match="stage"):
        record_from_row(row(stage="gossip"), CLIENT, REVISION)


def test_invalid_npc_type_rejected():
    with pytest.raises(ValueError, match="npc_type"):
        record_from_row(row(npc_type="player"), CLIENT, REVISION)


def test_addon_key_matches_lua_file_name():
    """AI_VoiceOver/DataModules.lua: format("%d-%s", questID, "accept")."""
    assert addon_key(record_from_row(row(), CLIENT, REVISION)) == "947-accept"


def test_jsonl_roundtrip(tmp_path):
    records = [record_from_row(row(), CLIENT, REVISION),
               record_from_row(row(stage="complete", text_ru=None), CLIENT, REVISION)]
    path = tmp_path / "corpus.jsonl"

    write_jsonl(records, path)

    assert read_jsonl(path) == records
    assert "Прошу вас" in path.read_text(encoding="utf-8")  # без \u-экранирования — читаемо в ревью


def test_jsonl_is_sorted_by_content_id(tmp_path):
    a = record_from_row(row(quest_id=10), CLIENT, REVISION)
    b = record_from_row(row(quest_id=9), CLIENT, REVISION)
    path = tmp_path / "corpus.jsonl"

    write_jsonl([a, b], path)

    assert [r.quest_id for r in read_jsonl(path)] == [10, 9]  # строковая сортировка content_id


def test_read_rejects_other_schema_version(tmp_path):
    path = tmp_path / "corpus.jsonl"
    data = record_from_row(row(), CLIENT, REVISION).__dict__ | {"schema_version": SCHEMA_VERSION + 1}
    path.write_text(json.dumps(data, ensure_ascii=False) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="schema_version"):
        read_jsonl(path)


def test_read_rejects_duplicate_content_id(tmp_path):
    record = record_from_row(row(), CLIENT, REVISION)
    path = tmp_path / "corpus.jsonl"
    line = json.dumps(record.__dict__, ensure_ascii=False)
    path.write_text(line + "\n" + line + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="quest:947:accept:creature:3693"):
        read_jsonl(path)

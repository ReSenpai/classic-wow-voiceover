"""Интеграция с локальной MySQL (vmangos). Запуск: pytest -m db (нужен docker compose up -d mysql)."""
import pytest

from voru.config import load_client_profile

pytestmark = pytest.mark.db

REVISION = "vmangos-db-test"


@pytest.fixture(scope="module")
def records():
    from voru.corpus.legacy_mysql import connect, fetch_quest_records

    try:
        connection = connect()
    except Exception as err:  # noqa: BLE001 — нет базы: тест не про это
        pytest.skip(f"MySQL недоступна: {err}")
    with connection:
        return fetch_quest_records(connection, load_client_profile(), REVISION)


def by_id(records):
    return {r.content_id: r for r in records}


def test_quest_947_accept_is_russian(records):
    accept = [r for r in records if r.text_key == "quest:947:accept"]

    assert len(accept) == 1
    (record,) = accept
    assert "Прошу вас, $N, соберите для меня эти грибы." in record.raw_text
    assert record.quest_title == "Грибы из пещеры"
    assert record.npc_name == "Баритас Лунный Сумрак"
    assert record.npc_race_id == 4  # ночной эльф


def test_all_stages_present(records):
    assert {r.stage for r in records} == {"accept", "progress", "complete"}


def test_content_ids_unique(records):
    assert len(by_id(records)) == len(records)


def test_no_english_fallback_in_raw_text(records):
    for r in records:
        if r.raw_text is not None:
            assert r.raw_text != r.raw_text_en or not any("a" <= ch.lower() <= "z" for ch in r.raw_text), r.content_id


def test_speakers_without_race_model_are_kept(records):
    """Legacy-SQL терял NPC без DisplayInfoExtra (звери, существа) — их голос решает кастинг."""
    assert any(r.npc_type == "creature" and r.npc_race_id is None for r in records)


def test_item_and_object_speakers_present(records):
    assert {"creature", "gameobject", "item"} <= {r.npc_type for r in records}

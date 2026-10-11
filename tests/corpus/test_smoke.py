"""Смоук-корпус Тенистой долины: стартовые квесты для быстрой проверки пака в игре (1–5 уровень)."""
import pytest

from voru.casting import cast, load_casting
from voru.config import REPO_ROOT
from voru.corpus.record import read_jsonl
from voru.normalize.prepare import Blocked, load_overrides, prepare_text
from voru.normalize.pronunciation import load_dictionary

SMOKE_PATH = REPO_ROOT / "corpus" / "smoke" / "shadowglen.jsonl"
SHADOWGLEN_QUESTS = {456, 457, 458, 459, 916, 917, 920, 921, 928, 2159, 3519, 3521, 3522, 4495,
                     3116, 3117, 3118, 3119, 3120}


@pytest.fixture(scope="module")
def smoke():
    return read_jsonl(SMOKE_PATH)


def test_covers_starting_quests_without_item_welcome_quest(smoke):
    assert {r.quest_id for r in smoke} == SHADOWGLEN_QUESTS
    assert {r.stage for r in smoke} == {"accept", "complete"}


def test_every_line_prepares_with_repo_overrides(smoke):
    overrides, dictionary = load_overrides(), load_dictionary()
    blocked = {r.text_key: res.reason for r in smoke
               if isinstance(res := prepare_text(r.text_key, r.raw_text, overrides, dictionary), Blocked)}

    assert blocked == {}


def test_every_speaker_has_a_voice(smoke):
    casting = load_casting()

    voices = {r.npc_name: cast(r, casting).voice_id for r in smoke}

    assert voices["Тариндрелла"] == "dryad-female"
    assert voices["Дирания Серебряное Сияние"] == "nightelf-female-calm"

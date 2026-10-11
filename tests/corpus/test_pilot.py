"""Критерии пилотного корпуса Тельдрассила (дизайн §3) на зафиксированном файле."""
import collections
import re

import pytest

from voru.corpus.record import read_jsonl
from voru.config import REPO_ROOT

PILOT_PATH = REPO_ROOT / "corpus" / "pilot" / "teldrassil.jsonl"
TELDRASSIL_ZONE = 141


@pytest.fixture(scope="module")
def pilot():
    return read_jsonl(PILOT_PATH)


def test_forty_unique_lines(pilot):
    assert len({r.text_key for r in pilot}) == 40


def test_every_record_is_teldrassil_accept_or_complete(pilot):
    assert {r.zone_id for r in pilot} == {TELDRASSIL_ZONE}
    assert {r.stage for r in pilot} == {"accept", "complete"}


def test_eight_to_twelve_speakers(pilot):
    assert 8 <= len({(r.npc_type, r.npc_id) for r in pilot}) <= 12


def test_both_npc_sexes_present(pilot):
    assert {0, 1} <= {r.npc_sex_id for r in pilot}


def test_speaker_without_race_model_present(pilot):
    """Проверка кастинга: неизвестная раса не должна молча стать «человеком-мужчиной»."""
    assert any(r.npc_race_id is None for r in pilot)


@pytest.mark.parametrize("token", [r"\$[nN]", r"\$[cC]", r"\$[rR]", r"\$[gG]"])
def test_markup_coverage(pilot, token):
    assert any(re.search(token, r.raw_text) for r in pilot)


def test_short_and_long_lines(pilot):
    lengths = [len(r.raw_text) for r in pilot]
    assert min(lengths) < 150
    assert max(lengths) > 450


def test_quests_with_different_accept_and_complete_speakers(pilot):
    speakers = collections.defaultdict(dict)
    for r in pilot:
        speakers[r.quest_id][r.stage] = (r.npc_type, r.npc_id)
    differing = [q for q, s in speakers.items() if len(s) == 2 and s["accept"] != s["complete"]]
    assert len(differing) >= 3


def test_all_lines_have_russian_text(pilot):
    assert all(r.locale_status == "ok" for r in pilot)


def test_all_pilot_lines_prepare_with_repo_overrides(pilot):
    from voru.normalize.prepare import Blocked, load_overrides, prepare_text
    from voru.normalize.pronunciation import load_dictionary

    overrides, dictionary = load_overrides(), load_dictionary()
    blocked = {}
    for r in pilot:
        result = prepare_text(r.text_key, r.raw_text, overrides, dictionary)
        if isinstance(result, Blocked):
            blocked[r.text_key] = result.reason

    assert blocked == {}

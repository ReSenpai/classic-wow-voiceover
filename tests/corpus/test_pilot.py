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


@pytest.fixture(scope="module")
def spoken_pilot(pilot):
    """Устный текст пилота с ударениями из кэша RUAccent и словарём — как его получит F5."""
    from voru.normalize.accent import Accentuator
    from voru.normalize.prepare import load_overrides, prepare_text
    from voru.normalize.pronunciation import load_dictionary

    accentuator, overrides, dictionary = Accentuator(), load_overrides(), load_dictionary()
    return "\n".join(v.spoken_text for r in pilot
                     for v in prepare_text(r.text_key, r.raw_text, overrides, dictionary, accentuator))


# Замечания из слепого прослушивания F5 v2/v4 (11.10.2026): ошибка модели → правильная форма.
@pytest.mark.parametrize("wrong, right", [
    ("кр+ивой", "крив+ой"), ("С+осны", "Сосн+ы"), ("вс+е ", "вс+ё"), ("з+ападню", "западн+ю"), ("н+айди", "найд+и"),
    ("хр+анят", "хран+ят"), ("р+остки", "ростк+и"), ("р+осток", "рост+ок"), ("выр+астить", "в+ырастить"),
    ("п+оражено", "поражен+о"), ("с+уществ", "сущ+еств"), ("н+абери", "набер+и"), ("пр+одолжу", "прод+олжу"),
    ("жив+ет", "жив+ёт"), ("замысл+ы", "з+амыслы"),
    ("межд+у", "м+ежду"), ("саженц+ах", "с+аженцах"),  # норма по решению пользователя
    # A/B F5 v4 против Qwen (12.10.2026): ошибки разметки RUAccent и слова без ударения
    ("сов+ет лес+а", "сов+ет л+еса"), ("зв+ёздного ветр+а", "зв+ёздного в+етра"), ("нордр+ассил", "нордрасс+ил"),
    ("гонца", "гонц+а"), ("порча", "п+орча"),
    # приёмка F5 v4 (12.10.2026)
    ("дух+и", "д+ухи"), ("но вест+и", "но в+ести"), ("в н+ем", "в н+ём"), ("изер+ой", "из+ерой"),
    ("дру+идами-в+оронами", "дру+идами, в+оронами"), ("+ах, так, зн+ачит", "+ах, так зн+ачит"),
    # второй круг приёмки F5 (12.10.2026): произношение пользователя вместо нормы
    ("добыл+а", "доб+ыла"), ("лес+у", "л+есу"),
    ("а, рост+ок", "а... рост+ок"),  # пауза после «А»: F5 не держит её на запятой
    ("бо+юсь", "боюсь"),  # F5 дважды обрывал «Бо+юсь» на «Бо» — знак снят, ударение по модели
])
def test_user_reported_stress_errors_are_fixed(spoken_pilot, wrong, right):
    lower = spoken_pilot.lower()
    assert wrong.lower() not in lower
    assert right.lower() in lower

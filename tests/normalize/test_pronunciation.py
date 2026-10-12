from pathlib import Path

import pytest

from voru.normalize.pronunciation import Entry, apply_dictionary, load_dictionary, model_input


def entries(*pairs):
    return {w.lower(): Entry(written=w, spoken=s, source="test") for w, s in pairs}


def test_restores_yo():
    d = entries(("еще", "ещё"), ("ее", "её"))

    assert apply_dictionary("Еще раз отдай ее мне.", d) == "Ещё раз отдай её мне."


def test_adds_stress_mark_and_keeps_capital():
    d = entries(("Дарнас", "Дарн+ас"), ("тельдрассил", "Тельдр+ассил"))

    assert apply_dictionary("В Дарнас, на тельдрассил.", d) == "В Дарн+ас, на тельдр+ассил."


def test_matches_whole_words_only():
    d = entries(("ее", "её"))

    assert apply_dictionary("Мне нужнее всего.", d) == "Мне нужнее всего."


def test_multiword_entry_wins_over_single_word():
    d = entries(("Роща", "Р+оща"), ("Роща Древних", "Р+оща Др+евних"))

    assert apply_dictionary("В Роще? Нет, в Роща Древних.", d) == "В Роще? Нет, в Р+оща Др+евних."


def test_entry_applied_once_not_twice():
    d = entries(("ещё", "ещё"), ("еще", "ещё"))

    assert apply_dictionary("еще", d) == "ещё"


@pytest.mark.parametrize("text, expected", [
    ("Его прервал Т+енарон.", "Его прервал Тен+арон."),         # имя: словарь сильнее RUAccent
    ("Тельдрасс+ил ждёт.", "Тельдр+ассил ждёт."),
    ("М+ежду нами.", "Межд+у нами."),                            # исправление поверх RUAccent
    ("Между нами.", "Межд+у нами."),                              # RUAccent не поставил ударение
])
def test_dictionary_overrides_existing_stress_marks(text, expected):
    d = entries(("Тенарон", "Тен+арон"), ("Тельдрассил", "Тельдр+ассил"), ("между", "межд+у"))

    assert apply_dictionary(text, d) == expected


def test_dictionary_matches_yo_and_e_equally():
    d = entries(("еще", "ещ+ё"))

    assert apply_dictionary("Ещ+ё раз, ещё раз, еще раз.", d) == "Ещ+ё раз, ещ+ё раз, ещ+ё раз."


@pytest.mark.parametrize("text, stress, expected", [
    ("Тельдр+ассил, ещё.", True, "Тельдр+ассил, ещё."),
    ("Тельдр+ассил, ещё.", False, "Тельдрассил, ещё."),
])
def test_model_input_depends_on_stress_support(text, stress, expected):
    assert model_input(text, stress_marks=stress) == expected


def _write(tmp_path, body):
    path = tmp_path / "pronunciation.yaml"
    path.write_text(body, encoding="utf-8")
    return path


def test_load_dictionary(tmp_path: Path):
    path = _write(tmp_path, "- written: еще\n  spoken: ещё\n  source: ё-словарь\n")

    assert load_dictionary(path) == {"еще": Entry("еще", "ещё", "ё-словарь")}


def test_entry_may_only_add_stress_and_yo(tmp_path: Path):
    path = _write(tmp_path, "- written: Тралл\n  spoken: Трал\n  source: x\n")

    with pytest.raises(ValueError, match="Тралл"):
        load_dictionary(path)


def test_respelling_must_be_explicit(tmp_path: Path):
    path = _write(tmp_path, "- written: Тралл\n  spoken: Трал\n  source: x\n  respell: true\n")

    assert load_dictionary(path)["тралл"].spoken == "Трал"


def test_duplicate_entries_rejected(tmp_path: Path):
    path = _write(tmp_path, "- {written: еще, spoken: ещё, source: a}\n- {written: Еще, spoken: Ещё, source: b}\n")

    with pytest.raises(ValueError, match="еще"):
        load_dictionary(path)


def test_repo_dictionary_is_valid():
    assert "еще" in load_dictionary()

import pytest

from voru.normalize.accent import AccentAlignmentError, AccentMissing, Accentuator, transfer_accents


# --- перенос ударений из RUAccent на исходный текст ---

def test_punctuation_of_source_is_preserved():
    """RUAccent съедает тире и сдваивает пробелы — берём из него только «+» и «ё»."""
    assert transfer_accents("Сна – они даже", "Сн+а  он+и д+аже") == "Сн+а – он+и д+аже"


def test_yo_from_engine_is_kept_and_case_of_source_too():
    assert transfer_accents("Все, Еще раз!", "вс+ё, ещ+ё р+аз") == "Вс+ё, Ещ+ё р+аз!"


def test_words_without_stress_stay_as_is():
    assert transfer_accents("Между нами", "Между н+ами") == "Между н+ами"


def test_paragraphs_and_newlines_are_preserved():
    assert transfer_accents("Да.\n\nНет.", "Д+а. Н+ет.") == "Д+а.\n\nН+ет."


def test_misaligned_words_raise():
    with pytest.raises(AccentAlignmentError):
        transfer_accents("Сна они", "Сн+а он+и д+аже")


def test_engine_changing_a_word_raises():
    with pytest.raises(AccentAlignmentError):
        transfer_accents("Мы пошли", "Мы п+ошли домой")


# --- кэш ударений ---

class Engine:
    def __init__(self):
        self.calls = []

    def __call__(self, text):
        self.calls.append(text)
        return text.replace("лес", "л+ес")


def test_engine_called_once_per_text_and_cached(tmp_path):
    engine = Engine()
    acc = Accentuator(tmp_path / "accents.jsonl", engine=engine)

    assert acc("лес шумит") == "л+ес шумит"
    assert acc("лес шумит") == "л+ес шумит"
    assert engine.calls == ["лес шумит"]


def test_cache_roundtrip_without_engine(tmp_path):
    path = tmp_path / "accents.jsonl"
    acc = Accentuator(path, engine=Engine())
    acc("лес шумит")
    acc.save()

    reloaded = Accentuator(path)  # окружение модели: RUAccent не установлен

    assert reloaded("лес шумит") == "л+ес шумит"


def test_missing_text_without_engine_raises(tmp_path):
    with pytest.raises(AccentMissing):
        Accentuator(tmp_path / "accents.jsonl")("новый текст")


def test_cache_file_is_sorted_and_readable(tmp_path):
    path = tmp_path / "accents.jsonl"
    acc = Accentuator(path, engine=Engine())
    acc("лес б")
    acc("лес а")
    acc.save()

    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2 and "л+ес а" in lines[0]  # кириллица без экранирования, по порядку текста

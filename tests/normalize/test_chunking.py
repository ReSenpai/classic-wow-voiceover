import pytest

from voru.normalize.chunking import PARAGRAPH_PAUSE_S, SENTENCE_PAUSE_S, Chunk, chunk_text


def size(text):
    return len(text.encode("utf-8"))


def test_short_text_is_one_chunk():
    assert chunk_text("Привет, путник.", max_bytes=200) == [Chunk("Привет, путник.", 0.0)]


def test_sentences_are_grouped_up_to_limit_and_never_split_midway():
    text = "Первое предложение. Второе предложение! Третье?"

    chunks = chunk_text(text, max_bytes=size("Первое предложение. Второе предложение!"))

    assert [c.text for c in chunks] == ["Первое предложение. Второе предложение!", "Третье?"]
    assert chunks[0].pause_after_s == SENTENCE_PAUSE_S
    assert chunks[-1].pause_after_s == 0.0


def test_paragraph_boundary_always_splits_with_longer_pause():
    chunks = chunk_text("Готово.\n\nТеперь иди.", max_bytes=1000)

    assert chunks == [Chunk("Готово.", PARAGRAPH_PAUSE_S), Chunk("Теперь иди.", 0.0)]


def test_regression_comma_inside_sentence_is_not_a_boundary():
    """Обрыв «Может, … позже ты ещё увидишь результаты!» — F5 резал по запятой."""
    text = "Принеси мне ростки. Может, позже ты ещё увидишь результаты!"

    chunks = chunk_text(text, max_bytes=size("Может, позже ты ещё увидишь результаты!") + 4)

    assert "Может, позже ты ещё увидишь результаты!" in [c.text for c in chunks]


def test_overlong_sentence_is_split_at_comma_nearest_to_middle():
    sentence = "Один два три четыре, пять шесть семь восемь, девять десять одиннадцать двенадцать."

    chunks = chunk_text(sentence, max_bytes=size(sentence) - 10)

    assert [c.text for c in chunks] == ["Один два три четыре, пять шесть семь восемь,",
                                        "девять десять одиннадцать двенадцать."]
    assert all(size(c.text) <= size(sentence) - 10 for c in chunks)


def test_sentence_without_commas_is_split_at_spaces():
    sentence = "Слово " * 30 + "конец."

    chunks = chunk_text(sentence.strip(), max_bytes=80)

    assert all(size(c.text) <= 80 for c in chunks)
    assert " ".join(c.text for c in chunks) == sentence.strip()


def test_stress_marks_and_ellipsis_are_kept():
    chunks = chunk_text("Л+ес ждёт… Ид+и.", max_bytes=1000)

    assert chunks == [Chunk("Л+ес ждёт… Ид+и.", 0.0)]


@pytest.mark.parametrize("max_bytes", [0, -5])
def test_invalid_limit(max_bytes):
    with pytest.raises(ValueError):
        chunk_text("Текст.", max_bytes=max_bytes)

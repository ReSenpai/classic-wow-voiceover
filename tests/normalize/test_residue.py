import pytest

from voru.normalize.address import NeedsOverride
from voru.normalize.residue import check_residue, fix_homoglyphs


@pytest.mark.parametrize("text, expected", [
    ("из Изумрудного Cна", "из Изумрудного Сна"),          # латинская C
    ("Телcамар и Телcамара", "Телсамар и Телсамара"),
    ("в тюрьмe", "в тюрьме"),
    ("Tанариса, Aзероте", "Танариса, Азероте"),
    ("Cамые лучшие", "Самые лучшие"),
])
def test_latin_lookalikes_inside_russian_words_are_fixed(text, expected):
    assert fix_homoglyphs(text) == expected


@pytest.mark.parametrize("text", [
    "BНо так нельзя",      # сломанный $B — не «ВНо», пусть блокируется
    "IЯ",
    "World of Warcraft",   # чисто латинские слова не трогаем
    "Перфограф B",
])
def test_homoglyph_fix_leaves_suspicious_words(text):
    assert fix_homoglyphs(text) == text


@pytest.mark.parametrize("text", [
    "Прошу вас, соберите для меня эти грибы.",
    "Первое.\n\nВторое — «третье»: (да); ну… «ещё» – 'Торготрон'?! \"Да\"",
])
def test_clean_russian_text_passes(text):
    assert check_residue(text) == text


@pytest.mark.parametrize("text, reason", [
    ("Greetings, traveler.", "latin_text"),
    ("Перфограф 3005 тире B.", "latin_text"),
    ("Осталось 5 дней.", "unexpected_symbol"),     # цифры должны быть развернуты раньше
    ("Цена ¥ и ©.", "unexpected_symbol"),
    ("Он ░▒▓ пришел.", "unexpected_symbol"),
    ("Это +ударение из исходника.", "unexpected_symbol"),
    ("Остался $ на месте.", "unexpected_symbol"),
    ("a/b", "latin_text"),
])
def test_residue_blocks(text, reason):
    with pytest.raises(NeedsOverride) as err:
        check_residue(text)

    assert err.value.reason == reason

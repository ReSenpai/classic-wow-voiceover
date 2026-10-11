import pytest

from voru.normalize.address import NeedsOverride
from voru.normalize.numbers import expand_numbers, number_to_words


@pytest.mark.parametrize("n, expected", [
    (0, "ноль"),
    (7, "семь"),
    (11, "одиннадцать"),
    (21, "двадцать один"),
    (40, "сорок"),
    (100, "сто"),
    (180, "сто восемьдесят"),
    (680, "шестьсот восемьдесят"),
    (1000, "тысяча"),
    (1200, "тысяча двести"),
    (2000, "две тысячи"),
    (3005, "три тысячи пять"),
    (5000, "пять тысяч"),
    (10000, "десять тысяч"),
    (21000, "двадцать одна тысяча"),
    (1000000, "миллион"),
    (1001000, "миллион одна тысяча"),
    (2500000, "два миллиона пятьсот тысяч"),
])
def test_number_to_words(n, expected):
    assert number_to_words(n) == expected


@pytest.mark.parametrize("text, expected", [
    ("Принесите 5 ножек струпника.", "Принесите пять ножек струпника."),
    ("Принесите 1 мертвянку.", "Принесите одну мертвянку."),
    ("Мне нужна 1 шкура.", "Мне нужна одна шкура."),
    ("Мне нужен 21 клык.", "Мне нужен двадцать один клык."),
    ("Убей 1 волка.", "Убей одного волка."),
    ("Дай мне 2 монеты.", "Дай мне две монеты."),
    ("Дай мне 2 клыка.", "Дай мне два клыка."),
    ("10 000 лет назад.", "Десять тысяч лет назад."),
    ("Прошло 10 000 лет.", "Прошло десять тысяч лет."),
    ("В 6 вечера.", "В шесть вечера."),
    ("Это Ультрапушка 5000!", "Это Ультрапушка пять тысяч!"),
    ("Без цифр.", "Без цифр."),
])
def test_expand_numbers_in_text(text, expected):
    assert expand_numbers(text) == expected


@pytest.mark.parametrize("text, reason", [
    ("Это займет около 5 дней.", "needs_override"),   # косвенный падеж: «около пяти»
    ("Вернись через 3-й час.", "needs_override"),      # порядковое
    ("Добавь 1,5 унции.", "needs_override"),            # дробь
    ("Встречаемся в 6:30.", "needs_override"),          # время
    ("Код 01010100 01100101.", "unspeakable_number"),  # «двоичные» строки гномов
    ("Целых 1000000000000 монет.", "unspeakable_number"),
])
def test_numbers_that_cannot_be_expanded_safely(text, reason):
    with pytest.raises(NeedsOverride) as err:
        expand_numbers(text)

    assert err.value.reason == reason

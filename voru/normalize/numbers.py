"""Числа → слова с согласованием 1/2 по роду и падежу следующего слова.

Числительное в косвенном падеже («около пяти дней»), порядковые, дроби и время
не разворачиваются автоматически — нужна точечная правка.
"""
import re
from functools import lru_cache

from voru.normalize.address import NeedsOverride

_UNITS = {
    "masc": ["", "один", "два", "три", "четыре", "пять", "шесть", "семь", "восемь", "девять"],
    "femn": ["", "одна", "две", "три", "четыре", "пять", "шесть", "семь", "восемь", "девять"],
}
_TEENS = ["десять", "одиннадцать", "двенадцать", "тринадцать", "четырнадцать", "пятнадцать",
          "шестнадцать", "семнадцать", "восемнадцать", "девятнадцать"]
_TENS = ["", "", "двадцать", "тридцать", "сорок", "пятьдесят", "шестьдесят", "семьдесят",
         "восемьдесят", "девяносто"]
_HUNDREDS = ["", "сто", "двести", "триста", "четыреста", "пятьсот", "шестьсот", "семьсот",
             "восемьсот", "девятьсот"]
# (порог, род, формы для 1 / 2–4 / 5+)
_SCALES = [
    (10 ** 9, "masc", ("миллиард", "миллиарда", "миллиардов")),
    (10 ** 6, "masc", ("миллион", "миллиона", "миллионов")),
    (10 ** 3, "femn", ("тысяча", "тысячи", "тысяч")),
]
MAX_NUMBER = 10 ** 12 - 1

# Предлоги, после которых числительное стоит в косвенном падеже.
_OBLIQUE_PREPOSITIONS = {
    "из", "до", "от", "у", "около", "без", "для", "течение", "к", "ко", "по", "с", "со", "о", "об",
    "при", "после", "более", "менее", "свыше", "между", "против", "кроме", "вокруг", "среди",
}

_TIME = re.compile(r"\d+:\d+")
_FRACTION = re.compile(r"\d+[.,]\d+")
_ORDINAL = re.compile(r"\d+-(?:й|я|е|го|му|м|ми|х|ю|ое|ая|ой|ый|ий|ую|ые|ых)\b")
_NUMBER = re.compile(r"\d{1,3}(?:[  ]\d{3})+(?!\d)|\d+")
_NEXT_WORD = re.compile(r"\s+([А-Яа-яЁё]+)")
_PREV_WORD = re.compile(r"([А-Яа-яЁё]+)\s+$")
_SENTENCE_START = re.compile(r"(?:^|[.!?…]\s+|\n\s*)$")


def number_to_words(n: int, gender: str = "masc") -> str:
    if n == 0:
        return "ноль"
    if n > MAX_NUMBER:
        raise ValueError(n)
    words = []
    for scale, scale_gender, forms in _SCALES:
        count, n = divmod(n, scale)
        if count:
            # «тысяча лет», а не «одна тысяча лет» — только для старшего разряда
            leading = [] if count == 1 and not words else _below_thousand(count, scale_gender)
            words += leading + [_plural(count, forms)]
    return " ".join(words + _below_thousand(n, gender))


def _below_thousand(n, gender):
    hundreds, rest = divmod(n, 100)
    words = [_HUNDREDS[hundreds]]
    if 10 <= rest < 20:
        words.append(_TEENS[rest - 10])
    else:
        words += [_TENS[rest // 10], _UNITS[gender][rest % 10]]
    return [w for w in words if w]


def _plural(n, forms):
    if n % 10 == 1 and n % 100 != 11:
        return forms[0]
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return forms[1]
    return forms[2]


@lru_cache(maxsize=1)
def _morph():
    import pymorphy3

    return pymorphy3.MorphAnalyzer()


def _agree(n, words, next_word):
    """Согласует последнее «один/два» с существительным или прилагательным после числа."""
    if not next_word or n % 1000 == 0:
        return words
    parse = next((p for p in _morph().parse(next_word) if p.tag.POS in ("NOUN", "ADJF")), None)
    if parse is None:
        return words
    head, _, last = words.rpartition(" ")
    if n % 10 == 1 and n % 100 != 11 and parse.tag.number == "sing":
        grammemes = {g for g in (parse.tag.gender, parse.tag.case) if g}
        if parse.tag.case == "accs" and parse.tag.gender == "masc" and parse.tag.animacy:
            grammemes.add(parse.tag.animacy)  # «одного волка», но «один клык»
        inflected = _morph().parse("один")[0].inflect(grammemes)
        last = inflected.word if inflected else last
    elif n % 10 == 2 and n % 100 != 12 and parse.tag.gender == "femn":
        last = "две"
    return f"{head} {last}".strip()


def expand_numbers(text: str) -> str:
    for pattern, reason in ((_TIME, "needs_override"),
                            (_FRACTION, "needs_override"), (_ORDINAL, "needs_override")):
        found = pattern.search(text)
        if found:
            raise NeedsOverride(reason, found.group())

    def replace(m):
        digits = re.sub(r"\D", "", m.group())
        n = int(digits)
        if n > MAX_NUMBER or (digits.startswith("0") and len(digits) > 1):
            raise NeedsOverride("unspeakable_number", m.group())
        before = text[:m.start()]
        prev = _PREV_WORD.search(before)
        if prev and prev.group(1).lower() in _OBLIQUE_PREPOSITIONS:
            raise NeedsOverride("needs_override", f"{prev.group(1)} {m.group()}")
        next_word = _NEXT_WORD.match(text, m.end())
        words = _agree(n, number_to_words(n), next_word.group(1) if next_word else None)
        if _SENTENCE_START.search(before):
            words = words[0].upper() + words[1:]
        return words

    return _NUMBER.sub(replace, text)

"""Финальная проверка устного текста: в синтез уходит только кириллица и пунктуация.

Латиница — почти всегда непереведённая реплика (английский не озвучиваем молча).
Остальное (цифры, $, +, битая кодировка) — следы необработанной разметки.
"""
import re

from voru.normalize.address import NeedsOverride

_LATIN = re.compile(r"[A-Za-z]+")
_ALLOWED = re.compile(r"[А-Яа-яЁё \n.,!?…:;\-–—«»\"'()„“”]")


def check_residue(text: str) -> str:
    latin = _LATIN.search(text)
    if latin:
        raise NeedsOverride("latin_text", latin.group())
    for ch in text:
        if not _ALLOWED.match(ch):
            raise NeedsOverride("unexpected_symbol", repr(ch))
    return text


# Латинские буквы, неотличимые на глаз от кириллических (опечатки локализации: «Изумрудного Cна»).
_LOOKALIKES = str.maketrans("ABCEHKMOPTXacepoxy", "АВСЕНКМОРТХасеорху")
_MIXED_WORD = re.compile(r"[A-Za-zА-Яа-яЁё]+")
_RUSSIAN_WORD = re.compile(r"[А-ЯЁ]?[а-яё]+")


def fix_homoglyphs(text: str) -> str:
    """Меняет латинских двойников на кириллицу, только если получается обычное русское слово."""
    def fix(m):
        word = m.group()
        if not (re.search("[A-Za-z]", word) and re.search("[А-Яа-яЁё]", word)):
            return word
        fixed = word.translate(_LOOKALIKES)
        return fixed if _RUSSIAN_WORD.fullmatch(fixed) else word

    return _MIXED_WORD.sub(fix, text)

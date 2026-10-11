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

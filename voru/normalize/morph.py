"""Общий морфологический анализатор (pymorphy3), загружается лениво."""
from functools import lru_cache


@lru_cache(maxsize=1)
def morph():
    import pymorphy3

    return pymorphy3.MorphAnalyzer()


def is_adjective_nominative(word: str) -> bool:
    return any(p.tag.POS == "ADJF" and p.tag.case == "nomn" for p in morph().parse(word))

"""Транскрипт референса не должен совпадать с репликами корпуса.

Регрессия (приёмка 12.10.2026): референс сатира начинался с «Ха-ха! Хорошая работёнка», а это
дословно его реплика квеста 488 — F5 сбивался на знакомой фразе и пропускал «работёнку».
"""
import re

import pytest

from voru.casting import load_casting
from voru.pipeline import PILOT_CORPUS, SMOKE_CORPUS, read_corpora

# Известные совпадения, ждут нового референса
PENDING = {"dryad-female": "референс повторяет реплику Тариндреллы 458 (смоук); переделать до озвучки смоука"}


def _phrases(text: str) -> set:
    """Фразы от двух слов: куски между знаками препинания, без регистра и «ё»."""
    text = text.lower().replace("ё", "е")
    return {" ".join(p.split()) for p in re.split(r"[.!?…,;:–—\n$]+", text) if len(p.split()) >= 2}


@pytest.fixture(scope="module")
def corpus_phrases():
    return set().union(*(_phrases(r.raw_text) for r in read_corpora([PILOT_CORPUS, SMOKE_CORPUS])))


@pytest.mark.parametrize("voice_id", [
    pytest.param(v, marks=pytest.mark.xfail(strict=True, reason=PENDING[v])) if v in PENDING else v
    for v in sorted(load_casting().voices)
])
def test_reference_text_does_not_repeat_corpus_lines(voice_id, corpus_phrases):
    profile = load_casting().voices[voice_id]

    assert sorted(_phrases(profile.reference_text or "") & corpus_phrases) == []

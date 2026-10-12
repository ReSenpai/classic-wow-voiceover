"""Нарезка длинной реплики для синтеза по смысловым границам (дизайн §7).

Абзац — всегда граница с длинной паузой; предложения собираются в куски до лимита и не
рвутся посередине. Предложение длиннее лимита режется по запятой/точке с запятой/тире,
ближайшей к середине, а без них — по пробелам. Лимит в байтах UTF-8 — так считает F5
(кириллица — 2 байта на символ), чтобы внутри модели куски больше не резались.
"""
import re
from dataclasses import dataclass

SENTENCE_PAUSE_S = 0.25
PARAGRAPH_PAUSE_S = 0.6
_SENTENCE_END = re.compile(r"(?<=[.!?…])\s+")
_SOFT_BREAK = re.compile(r"(?<=[,;:])\s+|\s+(?=[–—]\s)")


@dataclass(frozen=True)
class Chunk:
    text: str
    pause_after_s: float


def _size(text: str) -> int:
    return len(text.encode("utf-8"))


def _split_words(sentence: str, max_bytes: int) -> list:
    pieces, current = [], ""
    for word in sentence.split():
        candidate = f"{current} {word}" if current else word
        if current and _size(candidate) > max_bytes:
            pieces.append(current)
            current = word
        else:
            current = candidate
    return pieces + ([current] if current else [])


def _split_long(sentence: str, max_bytes: int) -> list:
    if _size(sentence) <= max_bytes:
        return [sentence]
    cuts = [m for m in _SOFT_BREAK.finditer(sentence)]
    if not cuts:
        return _split_words(sentence, max_bytes)
    middle = len(sentence) / 2
    cut = min(cuts, key=lambda m: abs(m.start() - middle))
    left, right = sentence[:cut.start()].strip(), sentence[cut.end():].strip()
    return _split_long(left, max_bytes) + _split_long(right, max_bytes)


def chunk_text(text: str, max_bytes: int) -> list:
    if max_bytes <= 0:
        raise ValueError(f"max_bytes must be positive, got {max_bytes}")
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks = []
    for p_index, paragraph in enumerate(paragraphs):
        sentences = [s.strip() for s in _SENTENCE_END.split(paragraph.replace("\n", " ")) if s.strip()]
        pieces = [piece for s in sentences for piece in _split_long(s, max_bytes)]
        grouped, current = [], ""
        for piece in pieces:
            candidate = f"{current} {piece}" if current else piece
            if current and _size(candidate) > max_bytes:
                grouped.append(current)
                current = piece
            else:
                current = candidate
        grouped.append(current)
        last_paragraph = p_index == len(paragraphs) - 1
        for g_index, group in enumerate(grouped):
            if g_index < len(grouped) - 1:
                pause = SENTENCE_PAUSE_S
            else:
                pause = 0.0 if last_paragraph else PARAGRAPH_PAUSE_S
            chunks.append(Chunk(group, pause))
    return chunks

"""Автопроверки WAV-мастера (дизайн §10): декодируется, не пустой, не тишина, без длинных пауз
и клиппинга, темп в разумных границах.

Флаги делятся на жёсткие (брак → qa_failed) и мягкие (послушать человеком → review_required).
Пороги — стартовые, уточняются по данным пилота. Только стандартная библиотека.
"""
import array
import math
import re
import wave
from dataclasses import dataclass

HARD = {"unreadable", "empty", "silent", "clipping", "too_fast", "too_slow", "long_pause"}


@dataclass(frozen=True)
class Flag:
    reason: str
    detail: str


@dataclass(frozen=True)
class QaThresholds:
    window_s: float = 0.02
    silence_rms: float = 0.01  # ≈ -40 dBFS
    max_pause_s: float = 1.5  # тишина внутри речи
    max_edge_silence_s: float = 1.0  # тишина в начале/конце
    clip_level: float = 0.999
    max_clip_fraction: float = 0.001
    min_chars_per_s: float = 5.0  # буквы в секунду речи
    max_chars_per_s: float = 25.0
    min_letters_for_tempo: int = 10  # на очень коротких репликах темп ненадёжен


def _read_mono(path):
    with wave.open(str(path), "rb") as w:
        if w.getsampwidth() != 2:
            raise ValueError(f"expected 16-bit PCM, got {8 * w.getsampwidth()}-bit")
        channels, rate = w.getnchannels(), w.getframerate()
        pcm = array.array("h", w.readframes(w.getnframes()))
    if channels > 1:
        pcm = array.array("h", (sum(pcm[i:i + channels]) // channels for i in range(0, len(pcm), channels)))
    return [s / 32768 for s in pcm], rate


def _window_rms(samples, size):
    return [math.sqrt(sum(s * s for s in samples[i:i + size]) / len(samples[i:i + size]))
            for i in range(0, len(samples), size)]


def _letters(text: str) -> int:
    return len(re.findall(r"[A-Za-zА-Яа-яЁё]", text))


def check_audio(path, text: str, t: QaThresholds = QaThresholds()) -> list:
    try:
        samples, rate = _read_mono(path)
    except (wave.Error, EOFError, ValueError) as err:
        return [Flag("unreadable", str(err))]
    if not samples:
        return [Flag("empty", "0 сэмплов")]

    size = max(1, int(rate * t.window_s))
    rms = _window_rms(samples, size)
    voiced = [i for i, v in enumerate(rms) if v >= t.silence_rms]
    if not voiced:
        return [Flag("silent", f"максимальный RMS {max(rms):.4f}")]

    flags = []
    first, last = voiced[0], voiced[-1]
    lead, trail = first * t.window_s, (len(rms) - 1 - last) * t.window_s
    for where, seconds in (("в начале", lead), ("в конце", trail)):
        if seconds > t.max_edge_silence_s:
            flags.append(Flag("edge_silence", f"{seconds:.1f} с {where}"))

    longest_gap = max((b - a - 1 for a, b in zip(voiced, voiced[1:])), default=0) * t.window_s
    if longest_gap > t.max_pause_s:
        flags.append(Flag("long_pause", f"пауза {longest_gap:.1f} с внутри речи"))

    clipped = sum(1 for s in samples if abs(s) >= t.clip_level) / len(samples)
    if clipped > t.max_clip_fraction:
        flags.append(Flag("clipping", f"{clipped:.2%} сэмплов на пределе"))

    letters = _letters(text)
    speech_s = (last - first + 1) * t.window_s
    if letters >= t.min_letters_for_tempo:
        tempo = letters / speech_s
        if tempo > t.max_chars_per_s:
            flags.append(Flag("too_fast", f"{tempo:.1f} букв/с — вероятно, пропущен текст"))
        elif tempo < t.min_chars_per_s:
            flags.append(Flag("too_slow", f"{tempo:.1f} букв/с — вероятно, повтор или затягивание"))
    return flags


def verdict(flags) -> tuple:
    """Состояние задания после QA: generated (чисто) / review_required / qa_failed."""
    if not flags:
        return "generated", ""
    reason = "; ".join(f"{f.reason}: {f.detail}" for f in flags)
    return ("qa_failed" if any(f.reason in HARD for f in flags) else "review_required"), reason

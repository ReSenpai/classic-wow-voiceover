"""Словарь произношения: восстановление «ё» и ударения (дизайн §6).

Внутренняя форма: «+» перед ударной гласной (синтаксис F5-TTS Russian). Для моделей без
поддержки ударений «+» снимается в model_input(). Запись словаря по умолчанию может только
добавить «+» и «ё»; другое написание требует явного respell: true.
"""
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from voru.config import REPO_ROOT

PRONUNCIATION_PATH = REPO_ROOT / "corpus" / "pronunciation.yaml"
STRESS = "+"


@dataclass(frozen=True)
class Entry:
    written: str
    spoken: str
    source: str
    note: str = ""
    respell: bool = False


def _skeleton(word: str) -> str:
    return word.replace(STRESS, "").lower().replace("ё", "е")


def load_dictionary(path=PRONUNCIATION_PATH) -> dict:
    entries = {}
    for raw in yaml.safe_load(Path(path).read_text(encoding="utf-8")) or []:
        entry = Entry(**raw)
        key = entry.written.lower()
        if key in entries:
            raise ValueError(f"{path}: duplicate entry {key}")
        if not entry.respell and _skeleton(entry.spoken) != _skeleton(entry.written):
            raise ValueError(f"{path}: {entry.written} → {entry.spoken} changes spelling; set respell: true")
        entries[key] = entry
    return entries


def apply_dictionary(text: str, entries: dict) -> str:
    if not entries:
        return text
    keys = sorted(entries, key=len, reverse=True)
    pattern = re.compile(r"(?<![\w+])(" + "|".join(map(re.escape, keys)) + r")(?!\w)", re.IGNORECASE)

    def replace(m):
        spoken = entries[m.group().lower()].spoken
        first = spoken[0].upper() if m.group()[0].isupper() else spoken[0].lower()
        return first + spoken[1:]

    return pattern.sub(replace, text)


def model_input(text: str, stress_marks: bool) -> str:
    return text if stress_marks else text.replace(STRESS, "")

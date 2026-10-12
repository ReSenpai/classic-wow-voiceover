"""Подготовка текста реплики: локаль → override → разметка → варианты пола → обращения →
латинские двойники → числа → проверка остатков → ударения RUAccent → словарь произношения.

Ничего не подставляется молча: нет русского текста, сломанная разметка, обращение внутри
фразы или устаревшая правка дают Blocked с причиной (дизайн §5–6).
"""
import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

from voru.config import REPO_ROOT
from voru.normalize.accent import AccentAlignmentError, AccentMissing
from voru.normalize.address import NeedsOverride, speak
from voru.normalize.markup import MarkupError, expand_player_gender, parse
from voru.normalize.numbers import expand_numbers
from voru.normalize.pronunciation import apply_dictionary
from voru.normalize.residue import check_residue, fix_homoglyphs

OVERRIDES_PATH = REPO_ROOT / "corpus" / "overrides.yaml"


@dataclass(frozen=True)
class Variant:
    player_gender: Optional[str]  # "m" / "f" / None — пол игрока, не NPC
    spoken_text: str


@dataclass(frozen=True)
class Blocked:
    reason: str
    detail: str = field(default="", compare=False)


@dataclass(frozen=True)
class Override:
    """Точечная правка: заменяет исходный текст целиком, пока исходник не изменился."""
    source_sha256: str
    text: str
    reason: str


def source_hash(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def load_overrides(path=OVERRIDES_PATH) -> dict:
    entries = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or []
    overrides = {}
    for entry in entries:
        key = entry["key"]
        if key in overrides:
            raise ValueError(f"{path}: duplicate override key {key}")
        overrides[key] = Override(str(entry["source_sha256"]), entry["text"], entry["reason"])
    return overrides


def prepare_text(content_key: str, raw_text: Optional[str], overrides: Optional[dict] = None,
                 dictionary: Optional[dict] = None, accentuator=None):
    """Возвращает кортеж Variant либо Blocked."""
    if raw_text is None or not raw_text.strip():
        return Blocked("missing_locale")

    source = raw_text
    override = (overrides or {}).get(content_key)
    if override:
        if override.source_sha256 != source_hash(raw_text):
            return Blocked("stale_override", content_key)
        source = override.text

    try:
        variants = expand_player_gender(parse(source))
        return tuple(Variant(gender, _spoken(tokens, dictionary, accentuator)) for gender, tokens in variants.items())
    except (MarkupError, NeedsOverride) as err:
        return Blocked(err.reason, str(err))
    except AccentMissing as err:
        return Blocked("accent_missing", str(err))
    except AccentAlignmentError as err:
        return Blocked("accent_alignment", str(err))


def _spoken(tokens, dictionary, accentuator=None):
    text = check_residue(expand_numbers(fix_homoglyphs(speak(tokens))))
    if accentuator is not None:
        text = accentuator(text)  # ударения и «ё» RUAccent
    return apply_dictionary(text, dictionary or {})  # словарь — последнее слово

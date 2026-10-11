"""Разбор служебной разметки игровых текстов в токены.

Разбор отделён от очистки: исходник не меняется, неизвестная или сломанная разметка
не вычищается регулярками, а блокирует запись с причиной (дизайн §6).
"""
import re
from dataclasses import dataclass
from typing import Optional, Union


@dataclass(frozen=True)
class Text:
    value: str


@dataclass(frozen=True)
class Break:
    """$b / $B — перенос строки; два подряд — граница абзаца."""


@dataclass(frozen=True)
class PlayerName:
    capital: bool


@dataclass(frozen=True)
class PlayerClass:
    capital: bool


@dataclass(frozen=True)
class PlayerRace:
    capital: bool


@dataclass(frozen=True)
class GenderChoice:
    """$gмужская:женская; — форма по полу игрока (не NPC).

    qualifier (c / r) в русской локализации — согласование с названием класса / расы.
    """
    male: str
    female: str
    qualifier: Optional[str] = None


@dataclass(frozen=True)
class StageDirection:
    """<...> или *...* — ремарка («Ева плачет.», «ик») или служебная заглушка (<NYI>)."""
    text: str


@dataclass(frozen=True)
class WorldState:
    """$NNNNw — число, которое игра подставляет на лету (например, счётчики Ан'Киража)."""
    id: int


Token = Union[Text, Break, PlayerName, PlayerClass, PlayerRace, GenderChoice, StageDirection, WorldState]


class MarkupError(ValueError):
    def __init__(self, reason, raw, position):
        self.reason = reason
        self.raw = raw
        self.position = position
        super().__init__(f"{reason} at {position}: {raw[position:position + 40]!r}")


_SIMPLE = {
    "b": Break(), "B": Break(),
    "n": PlayerName(False), "N": PlayerName(True),
    "c": PlayerClass(False), "C": PlayerClass(True),
    "r": PlayerRace(False), "R": PlayerRace(True),
}
_STAGE_CLOSE = {"<": ">", "*": "*"}
_GENDER_BODY =re.compile(r"([^;$<>]*);")
_WORLD_STATE = re.compile(r"\$(\d+)w")


def parse(raw: str) -> tuple:
    tokens = []
    text_start = 0
    i = 0

    def flush(end):
        if end > text_start:
            tokens.append(Text(raw[text_start:end]))

    while i < len(raw):
        ch = raw[i]
        if ch in _STAGE_CLOSE:
            close = raw.find(_STAGE_CLOSE[ch], i + 1)
            if close == -1 or any(c in raw[i + 1:close] for c in "<>*"):
                raise MarkupError("unclosed_stage_direction", raw, i)
            flush(i)
            tokens.append(StageDirection(raw[i + 1:close]))
            i = text_start = close + 1
        elif ch == ">":
            raise MarkupError("stray_stage_direction_end", raw, i)
        elif ch == "$":
            flush(i)
            token, i = _parse_dollar(raw, i)
            tokens.append(token)
            text_start = i
        else:
            i += 1
    flush(len(raw))
    return tuple(tokens)


def _parse_dollar(raw, i):
    code = raw[i + 1:i + 2]
    if code in _SIMPLE:
        return _SIMPLE[code], i + 2
    if code in ("g", "G"):
        return _parse_gender(raw, i)
    world_state = _WORLD_STATE.match(raw, i)
    if world_state:
        return WorldState(int(world_state.group(1))), world_state.end()
    raise MarkupError("unknown_token", raw, i)


def _parse_gender(raw, i):
    body = _GENDER_BODY.match(raw, i + 2)
    parts = [p.strip() for p in body.group(1).split(":")] if body else []
    if len(parts) not in (2, 3):
        raise MarkupError("malformed_gender", raw, i)
    qualifier = parts[2] if len(parts) == 3 else None
    return GenderChoice(parts[0], parts[1], qualifier), body.end()


def expand_player_gender(tokens: tuple) -> dict:
    """Варианты по полу игрока: {"m": ..., "f": ...} или {None: tokens}, если пол не влияет."""
    if not any(isinstance(t, GenderChoice) for t in tokens):
        return {None: tokens}
    return {
        "m": tuple(Text(t.male) if isinstance(t, GenderChoice) else t for t in tokens),
        "f": tuple(Text(t.female) if isinstance(t, GenderChoice) else t for t in tokens),
    }

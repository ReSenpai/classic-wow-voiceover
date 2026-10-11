"""Сборка устного текста из токенов и политика обращений $N / $C / $R.

Ник игрока в общем паке не озвучивается. Обращение, выделенное пунктуацией
(«Прошу вас, $N, соберите…»), по умолчанию убирается. Если токен стоит внутри фразы
(«Ты похож на $c»), удаление ломает смысл — запись требует точечной правки (override).
"""
import re

from voru.normalize.markup import (
    Break,
    GenderChoice,
    PlayerClass,
    PlayerName,
    PlayerRace,
    StageDirection,
    Text,
    WorldState,
)
from voru.normalize.morph import is_adjective_nominative

ADDRESS = "\x00"  # временная метка на месте обращения

_RULES = (
    # «Прошу вас, $N, соберите» → «Прошу вас, соберите»
    (re.compile(rf", *{ADDRESS} *, *"), lambda m: ", "),
    # «Привет, $N.» / «Спасибо, $N» в конце строки → «Привет.» / «Спасибо»
    (re.compile(rf" *, *{ADDRESS} *(?=[.!?…;:]|\n|$)"), lambda m: ""),
    # «$N, послушай» в начале предложения → «Послушай»
    (re.compile(rf"(^|[.!?…] |\n){ADDRESS} *, *(\w)"), lambda m: m.group(1) + m.group(2).upper()),
    # «Вот так. $N! Иди.» → «Вот так. Иди.»
    (re.compile(rf"(^|[.!?…] |\n){ADDRESS} *[.!?…]+ ?"), lambda m: m.group(1)),
    # опечатка локализации: «Спасибо тебе, $N Прости…» — после обращения нет точки
    (re.compile(rf" *, *{ADDRESS} +(?=[А-ЯЁ])"), lambda m: ". "),
)
# «, юный $c» / «Юный $c,» — прилагательное входит в обращение и убирается вместе с ним
_ADJECTIVE_BEFORE_ADDRESS = re.compile(rf"(^|, |[.!?…] |\n)([А-Яа-яЁё]+) {ADDRESS}")


class NeedsOverride(ValueError):
    def __init__(self, reason, detail=""):
        self.reason = reason
        self.detail = detail
        super().__init__(f"{reason}: {detail}" if detail else reason)


def speak(tokens) -> str:
    """Устная форма одного варианта (после expand_player_gender)."""
    text = "".join(_render(t) for t in tokens)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    had_address = ADDRESS in text
    text = _ADJECTIVE_BEFORE_ADDRESS.sub(
        lambda m: m.group(1) + ADDRESS if is_adjective_nominative(m.group(2)) else m.group(), text)

    changed = True
    while changed:
        changed = False
        for pattern, repl in _RULES:
            text, n = pattern.subn(repl, text)
            changed = changed or n > 0

    if ADDRESS in text:
        at = text.index(ADDRESS)
        raise NeedsOverride("needs_override", text[max(0, at - 30):at + 30].replace(ADDRESS, "<обращение>"))
    text = text.strip()
    if not text:
        raise NeedsOverride("empty_after_address_removal" if had_address else "empty_spoken_text")
    return text


def _render(token) -> str:
    if isinstance(token, Text):
        return token.value
    if isinstance(token, Break):
        return "\n"
    if isinstance(token, (PlayerName, PlayerClass, PlayerRace)):
        return ADDRESS
    if isinstance(token, StageDirection):
        return ""
    if isinstance(token, WorldState):
        raise NeedsOverride("dynamic_value", f"${token.id}w")
    if isinstance(token, GenderChoice):
        raise ValueError("GenderChoice must be expanded by expand_player_gender() before speak()")
    raise TypeError(f"unknown token {token!r}")

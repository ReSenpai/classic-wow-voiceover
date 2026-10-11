"""Детерминированная сериализация данных в Lua 5.1 (таблицы data-модуля).

Ключи сортируются (сначала числа, затем строки) — одинаковые данные дают байт-в-байт
одинаковый файл. Кириллица пишется как есть (UTF-8), управляющие символы — десятичные escape-последовательности Lua.
"""
import math

_ESCAPES = {"\\": "\\\\", '"': '\\"', "\n": "\\n", "\r": "\\r", "\t": "\\t"}


def _string(s: str) -> str:
    out = []
    for ch in s:
        if ch in _ESCAPES:
            out.append(_ESCAPES[ch])
        elif ord(ch) < 32 or ord(ch) == 127:
            out.append(f"\{ord(ch):03d}")
        else:
            out.append(ch)
    return '"' + "".join(out) + '"'


def _key(k) -> str:
    if isinstance(k, bool) or not isinstance(k, (int, str)):
        raise TypeError(f"unsupported Lua table key: {k!r}")
    return f"[{k}]" if isinstance(k, int) else f"[{_string(k)}]"


def _sort_key(k):
    return (0, k, "") if isinstance(k, int) and not isinstance(k, bool) else (1, 0, str(k))


def lua_value(value, indent: int = 0) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"non-finite number: {value}")
        return repr(round(value, 3))
    if isinstance(value, str):
        return _string(value)
    if isinstance(value, dict):
        if not value:
            return "{}"
        pad = "    " * (indent + 1)
        items = [f"{pad}{_key(k)} = {lua_value(value[k], indent + 1)}," for k in sorted(value, key=_sort_key)]
        return "{\n" + "\n".join(items) + "\n" + "    " * indent + "}"
    raise TypeError(f"unsupported Lua value: {value!r}")

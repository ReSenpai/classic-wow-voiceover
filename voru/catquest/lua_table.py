"""Ограниченный парсер Lua-данных (дизайн CQ §6): Lua не исполняется.

Допустимы только операторы `Имя = Имя or {}` и `Имя[.поле…] = <литерал>`, где литерал — число,
строка в кавычках, true/false/nil или конструктор таблицы. Таблица только из позиционных значений → list,
только из ключей → dict. Всё остальное (вызовы, конкатенация, local, функции, длинные строки…) —
LuaSchemaError с файлом и строкой: частично прочитанный индекс хуже отказа.
"""
import re

_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "\\": "\\", '"': '"', "'": "'", "\n": "\n", "a": "\a", "b": "\b",
            "f": "\f", "v": "\v"}
_NUMBER = re.compile(r"0[xX][0-9a-fA-F]+|(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?")
_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_KEYWORDS = {"local", "function", "return", "if", "for", "while", "do", "end", "repeat", "goto", "and", "or", "not"}


class LuaSchemaError(ValueError):
    pass


class _Parser:
    def __init__(self, text: str, name: str):
        self.text, self.name, self.pos = text, name, 0

    # --- лексика ---
    def error(self, what: str):
        line = self.text.count("\n", 0, self.pos) + 1
        return LuaSchemaError(f"{self.name}:{line}: неподдерживаемая конструкция: {what}")

    def skip(self):
        while True:
            m = re.compile(r"\s+").match(self.text, self.pos)
            if m:
                self.pos = m.end()
            if self.text.startswith("--[[", self.pos) or self.text.startswith("--[=", self.pos):
                raise self.error("--[[")
            if self.text.startswith("--", self.pos):
                end = self.text.find("\n", self.pos)
                self.pos = len(self.text) if end < 0 else end
                continue
            return

    def peek(self, token: str) -> bool:
        self.skip()
        return self.text.startswith(token, self.pos)

    def eat(self, token: str) -> bool:
        if self.peek(token):
            self.pos += len(token)
            return True
        return False

    def expect(self, token: str):
        if not self.eat(token):
            raise self.error(self._describe())

    def name_token(self):
        self.skip()
        m = _NAME.match(self.text, self.pos)
        if not m or m.group() in _KEYWORDS:
            return None
        self.pos = m.end()
        return m.group()

    def _describe(self) -> str:
        self.skip()
        rest = self.text[self.pos:self.pos + 12]
        m = _NAME.match(rest)
        if m and m.group() in _KEYWORDS:
            return m.group()
        if m and self.text.startswith("(", self.pos + m.end()) or rest.startswith("("):
            return "вызов функции"
        return repr(rest.split("\n")[0]) if rest else "конец файла"

    # --- синтаксис ---
    def statements(self) -> dict:
        env = {}
        while True:
            self.skip()
            if self.pos >= len(self.text):
                return env
            start = self.pos
            target = self.name_token()
            if target is None:
                raise self.error(self._describe())
            path = [target]
            while self.eat("."):
                field = self.name_token()
                if field is None:
                    raise self.error(self._describe())
                path.append(field)
            if self.peek("("):
                raise self.error("вызов функции")
            self.expect("=")
            if len(path) == 1 and self._namespace_init(target):
                env.setdefault(target, {})
                continue
            value = self.value()
            if self.peek("..") or self.peek("("):
                raise self.error(".." if self.peek("..") else "вызов функции")
            self._assign(env, path, value, start)
            self.eat(";")

    def _namespace_init(self, target: str) -> bool:
        """`X = X or {}` — единственная допустимая форма с or."""
        save = self.pos
        name = self.name_token()
        if name is None or name in ("true", "false", "nil"):
            self.pos = save
            return False
        if not self.eat("or"):
            if self.peek("("):
                raise self.error("вызов функции")
            raise self.error(self._describe() if name in _KEYWORDS else name)
        if name != target or not (self.eat("{") and self.eat("}")):
            raise self.error("or")
        return True

    def _assign(self, env, path, value, start):
        if len(path) == 1:
            env[path[0]] = value
            return
        node = env.get(path[0])
        if not isinstance(node, dict):
            self.pos = start
            raise self.error(f"неизвестная таблица {path[0]}")
        for field in path[1:-1]:
            node = node.setdefault(field, {})
        node[path[-1]] = value

    def value(self):
        self.skip()
        ch = self.text[self.pos:self.pos + 1]
        if ch in ('"', "'"):
            return self.string(ch)
        if self.text.startswith("[[", self.pos) or self.text.startswith("[=", self.pos):
            raise self.error("[[")
        if ch == "{":
            return self.table()
        negative = self.eat("-")
        self.skip()
        m = _NUMBER.match(self.text, self.pos)
        if m:
            self.pos = m.end()
            raw = m.group()
            number = int(raw, 16) if raw[:2].lower() == "0x" else (
                int(raw) if re.fullmatch(r"\d+", raw) else float(raw))
            return -number if negative else number
        if negative:
            raise self.error(self._describe())
        for word, literal in (("true", True), ("false", False), ("nil", None)):
            if re.match(word + r"\b", self.text[self.pos:]):
                self.pos += len(word)
                return literal
        raise self.error(self._describe())

    def string(self, quote: str) -> str:
        self.pos += 1
        out = []
        while True:
            if self.pos >= len(self.text) or self.text[self.pos] == "\n":
                raise self.error("строка без закрывающей кавычки")
            ch = self.text[self.pos]
            if ch == quote:
                self.pos += 1
                return "".join(out)
            if ch == "\\":
                nxt = self.text[self.pos + 1:self.pos + 2]
                if nxt in _ESCAPES:
                    out.append(_ESCAPES[nxt])
                    self.pos += 2
                    continue
                m = re.compile(r"\d{1,3}").match(self.text, self.pos + 1)
                if not m:
                    raise self.error(f"escape \\{nxt}")
                out.append(chr(int(m.group())))
                self.pos = m.end()
                continue
            out.append(ch)
            self.pos += 1

    def table(self):
        self.expect("{")
        keyed, positional = {}, []
        while not self.eat("}"):
            if self.eat("["):
                key = self.value()
                self.expect("]")
                self.expect("=")
            else:
                save = self.pos
                key = self.name_token()
                if key is None or not self.eat("="):
                    self.pos, key = save, None
            if key is None:
                if keyed:
                    raise self.error("смешанная таблица")
                positional.append(self.value())
            else:
                if positional:
                    raise self.error("смешанная таблица")
                if key in keyed:
                    raise self.error(f"повтор ключа {key!r}")
                keyed[key] = self.value()
            if self.peek("..") or self.peek("("):
                raise self.error(".." if self.peek("..") else "вызов функции")
            if not (self.eat(",") or self.eat(";")):
                self.expect("}")
                break
        return positional if positional else keyed


def parse_assignments(text: str, name: str = "<lua>") -> dict:
    """Глобальные присваивания чанка как словарь Python."""
    return _Parser(text, name).statements()

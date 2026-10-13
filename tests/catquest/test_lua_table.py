"""Ограниченный парсер Lua-данных пака CatQuest (дизайн CQ §6): таблицы и литералы, без исполнения."""
import pytest

from voru.catquest.lua_table import LuaSchemaError, parse_assignments


def test_namespace_and_nested_tables():
    chunk = '''-- комментарий
Pack = Pack or {}
Pack.quests = {
    [2] = { d = 17.5, v = "narrator", n = { x = 184 }, c = { x = { { 0.00, "Раз." }, { 8.07, "Два." } } } },
    [5] = { g = 1, d = -1, ok = true, no = false },
}
'''
    result = parse_assignments(chunk)

    assert result == {"Pack": {"quests": {
        2: {"d": 17.5, "v": "narrator", "n": {"x": 184}, "c": {"x": [[0.0, "Раз."], [8.07, "Два."]]}},
        5: {"g": 1, "d": -1, "ok": True, "no": False},
    }}}


@pytest.mark.parametrize("literal, value", [
    (r'"с \"кавычками\" и \\ слэшем"', 'с "кавычками" и \\ слэшем'),
    (r"'одинарные \'кавычки\''", "одинарные 'кавычки'"),
    (r'"строка\nперенос"', "строка\nперенос"),
    ("1e3", 1000.0),
    ("0x10", 16),
    ("{}", {}),
    ("true", True),
    ("nil", None),
    ("-0.5", -0.5),
    ('{ "a", "b", }', ["a", "b"]),
    ('{ ["ключ с пробелом"] = 1; x = 2 }', {"ключ с пробелом": 1, "x": 2}),
])
def test_literals(literal, value):
    assert parse_assignments(f"T = {literal}") == {"T": value}


@pytest.mark.parametrize("chunk, construct", [
    ('os.execute("rm -rf /")', "вызов функции"),
    ("T = print('x')", "вызов функции"),
    ('T = "a" .. "b"', ".."),
    ("T = [[длинная строка]]", "[["),
    ("T = { [1] = 1, 2 }", "смешанная таблица"),
    ("local T = {}", "local"),
    ("T = function() end", "function"),
    ("T.x = {}", "неизвестная таблица T"),
    ("T = U or {}", "or"),
    ('T = "незакрытая', "строка"),
])
def test_anything_else_is_rejected_with_line(chunk, construct):
    with pytest.raises(LuaSchemaError) as err:
        parse_assignments("A = A or {}\n" + chunk, name="Index.lua")

    assert "Index.lua:2" in str(err.value)
    assert construct in str(err.value)


def test_mixed_table_keys_are_not_merged_silently():
    with pytest.raises(LuaSchemaError):
        parse_assignments("T = { x = 1, x = 2 }")

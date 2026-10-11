import pytest
from lupa import lua51

from voru.exporters.lua import lua_value


def run(value):
    lua = lua51.LuaRuntime(unpack_returned_tuples=True)
    return lua.execute("return " + lua_value(value))


def to_py(obj):
    if hasattr(obj, "items") and not isinstance(obj, dict):
        return {k: to_py(v) for k, v in obj.items()}
    return obj


@pytest.mark.parametrize("value", [
    0, 947, -3, 34.638, True, False,
    "Прошу вас",
    'кавычки " и \ слэш',
    "строка\nс переносом\r и табом\t",
    "\x00\x01 управляющие",
    "]] закрытие длинной строки",
])
def test_scalars_roundtrip(value):
    assert run(value) == value


def test_nested_table_roundtrip():
    data = {947: 3693, "947-accept": 34.638, "f-947-accept": 30.0, "nested": {"a": {1: "x"}}}

    assert to_py(run(data)) == data


def test_output_is_deterministic_and_sorted():
    a = lua_value({"b": 1, "a": 2, 10: 3, 2: 4})
    b = lua_value({2: 4, 10: 3, "a": 2, "b": 1})

    assert a == b
    assert a.index("[2]") < a.index("[10]") < a.index('["a"]') < a.index('["b"]')


def test_float_is_rounded_to_milliseconds():
    assert lua_value(1.23456789) == "1.235"


@pytest.mark.parametrize("bad", [None, [1, 2], {1.5: "x"}, float("nan")])
def test_unsupported_values_rejected(bad):
    with pytest.raises((TypeError, ValueError)):
        lua_value(bad)

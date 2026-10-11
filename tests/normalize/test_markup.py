import pytest

from voru.normalize.markup import (
    Break,
    GenderChoice,
    MarkupError,
    PlayerClass,
    PlayerName,
    PlayerRace,
    StageDirection,
    Text,
    WorldState,
    expand_player_gender,
    parse,
)


# --- parse: разбор разметки в токены, исходник не меняется ---

def test_plain_text_is_single_token():
    assert parse("Приветствую.") == (Text("Приветствую."),)


def test_empty_text_has_no_tokens():
    assert parse("") == ()


@pytest.mark.parametrize("raw", ["$b", "$B"])
def test_line_break_both_cases(raw):
    assert parse(f"А{raw}Б") == (Text("А"), Break(), Text("Б"))


def test_double_break_keeps_both_for_paragraphs():
    assert parse("А$B$BБ") == (Text("А"), Break(), Break(), Text("Б"))


@pytest.mark.parametrize("raw, token", [
    ("$n", PlayerName(capital=False)),
    ("$N", PlayerName(capital=True)),
    ("$c", PlayerClass(capital=False)),
    ("$C", PlayerClass(capital=True)),
    ("$r", PlayerRace(capital=False)),
    ("$R", PlayerRace(capital=True)),
])
def test_player_tokens_keep_case(raw, token):
    assert parse(f"Эй, {raw}.") == (Text("Эй, "), token, Text("."))


@pytest.mark.parametrize("raw", ["$g", "$G"])
def test_gender_choice_both_cases(raw):
    assert parse(f"Ты {raw}готов:готова;?") == (
        Text("Ты "), GenderChoice("готов", "готова"), Text("?"),
    )


def test_gender_choice_with_spaces_inside_options():
    assert parse("$gбрат мой:сестра моя;") == (GenderChoice("брат мой", "сестра моя"),)


def test_gender_choice_options_are_trimmed():
    assert parse("$g пришел : пришла ;") == (GenderChoice("пришел", "пришла"),)


@pytest.mark.parametrize("raw, qualifier", [
    ("$gюный:юная:c;", "c"),
    ("$Gзнающего:знающую:c;", "c"),
    ("$gпроклятый:проклятая:r;", "r"),
    ("$gпришел:пришла: c;", "c"),
])
def test_gender_choice_agreement_qualifier(raw, qualifier):
    (token,) = parse(raw)
    assert token.qualifier == qualifier


def test_several_gender_choices_in_one_text():
    assert parse("$gсам:сама; $gготов:готова;") == (
        GenderChoice("сам", "сама"), Text(" "), GenderChoice("готов", "готова"),
    )


def test_stage_direction():
    assert parse("<Ева плачет.> Ушел...") == (StageDirection("Ева плачет."), Text(" Ушел..."))


@pytest.mark.parametrize("raw, text", [
    ("*Тралл смеется.*$B$BЗаметно…", "Тралл смеется."),
    ("*ик* Я трезв!", "ик"),
])
def test_asterisk_stage_direction(raw, text):
    assert parse(raw)[0] == StageDirection(text)


def test_world_state_value():
    assert parse("в течение $2113w дней") == (Text("в течение "), WorldState(2113), Text(" дней"))


# --- parse: ошибки блокируют запись с понятной причиной ---

@pytest.mark.parametrize("raw, reason", [
    ("Привет, $x!", "unknown_token"),
    ("Стоимость 5$", "unknown_token"),
    ("$gтакому юному:такой Слушай же внимательно", "malformed_gender"),
    ("$gготов;", "malformed_gender"),
    ("$gа:б:в:г;", "malformed_gender"),
    ("<Ева плачет.", "unclosed_stage_direction"),
    ("*Ева плачет.", "unclosed_stage_direction"),
    ("*Андоров мрачно смотрит на вас.>$B$BЕсли", "unclosed_stage_direction"),
    ("Андоров смотрит на вас.> Если", "stray_stage_direction_end"),
    ("$12 монет", "unknown_token"),
])
def test_invalid_markup_raises_with_reason(raw, reason):
    with pytest.raises(MarkupError) as err:
        parse(raw)

    assert err.value.reason == reason
    assert err.value.raw == raw


def test_error_points_to_position():
    with pytest.raises(MarkupError) as err:
        parse("Привет, $x!")

    assert err.value.position == 8


# --- expand_player_gender: варианты по полу игрока ---

def test_no_gender_markup_gives_single_neutral_variant():
    tokens = parse("Привет, $N.")

    assert expand_player_gender(tokens) == {None: tokens}


def test_gender_markup_gives_male_and_female_variants():
    tokens = parse("Ты $gготов:готова;, $n?")

    assert expand_player_gender(tokens) == {
        "m": (Text("Ты "), Text("готов"), Text(", "), PlayerName(capital=False), Text("?")),
        "f": (Text("Ты "), Text("готова"), Text(", "), PlayerName(capital=False), Text("?")),
    }


def test_lowercase_gender_is_not_collapsed_to_male():
    """Регрессия legacy tts_utils: строчный $g сворачивался в мужскую форму до разделения."""
    variants = expand_player_gender(parse("Ты $gпришел:пришла;."))

    assert set(variants) == {"m", "f"}
    assert Text("пришла") in variants["f"]

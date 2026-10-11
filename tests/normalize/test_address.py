import pytest

from voru.normalize.address import NeedsOverride, speak
from voru.normalize.markup import parse


def say(raw):
    return speak(parse(raw))


# --- обращение, выделенное пунктуацией, по умолчанию убирается ---

@pytest.mark.parametrize("raw, expected", [
    ("Прошу вас, $N, соберите грибы.", "Прошу вас, соберите грибы."),
    ("Привет, $N.", "Привет."),
    ("Здравствуй, $n!", "Здравствуй!"),
    ("Спасибо, $N", "Спасибо"),
    ("Ну что, $N?", "Ну что?"),
    ("$N, послушай меня.", "Послушай меня."),
    ("Вот так. $N, послушай.", "Вот так. Послушай."),
    ("Вот так. $N! Иди.", "Вот так. Иди."),
    ("Приветствую, $c.", "Приветствую."),
    ("Да пребудет с тобой Элуна, $R.", "Да пребудет с тобой Элуна."),
    ("Здравствуй, $N, $c!", "Здравствуй!"),
])
def test_punctuated_address_is_removed(raw, expected):
    assert say(raw) == expected


@pytest.mark.parametrize("raw, expected", [
    ("Привет тебе, юный $c. Не окажешь услугу?", "Привет тебе. Не окажешь услугу?"),
    ("Когда-нибудь мы встретимся, юный $c. Но пока прими награду.", "Когда-нибудь мы встретимся. Но пока прими награду."),
    ("Тебе удалось, юный $c! Славно!", "Тебе удалось! Славно!"),
    ("Спасибо, отважный $c, ты помог.", "Спасибо, ты помог."),
    ("Юный $c, послушай.", "Послушай."),
    ("Приветствую, юный $c.", "Приветствую."),
    ("Дорогой $N, слушай.", "Слушай."),
])
def test_adjective_with_address_is_removed_together(raw, expected):
    assert say(raw) == expected


@pytest.mark.parametrize("raw", [
    "Ты весьма достойный и способный $c.",   # не обращение, а сказуемое
    "Ты, как $c, должен понимать.",
])
def test_address_like_phrase_inside_sentence_still_needs_override(raw):
    with pytest.raises(NeedsOverride):
        say(raw)


@pytest.mark.parametrize("raw, expected", [
    ("Спасибо тебе, $N Прости мою немногословность.", "Спасибо тебе. Прости мою немногословность."),
    ("Это очень впечатляет, $N Хотелось бы попросить.", "Это очень впечатляет. Хотелось бы попросить."),
])
def test_missing_period_after_address_is_restored(raw, expected):
    """Опечатка локализации: после обращения нет точки, следующее предложение с заглавной."""
    assert say(raw) == expected


def test_comma_is_kept_when_inner_address_removed():
    """Осознанное ограничение: без синтаксиса не отличить «В отходах, $c, таится» (запятая лишняя)
    от «Если ты гуляешь, $c, то…» (запятая нужна). Лишняя запятая — короткая пауза,
    потерянная склеила бы предложения. Исправляется точечной правкой."""
    assert say("В этих отходах, $c, таится прошлое.") == "В этих отходах, таится прошлое."


def test_address_at_paragraph_start():
    assert say("Готово.$B$B$N, теперь иди.") == "Готово.\n\nТеперь иди."


def test_address_before_paragraph_end():
    assert say("Спасибо, $N$B$BИди.") == "Спасибо\n\nИди."


# --- обращение внутри фразы не трогаем: нужна точечная правка ---

@pytest.mark.parametrize("raw", [
    "Ты похож на $c.",
    "Тебя зовут $N?",
])
def test_address_inside_phrase_needs_override(raw):
    with pytest.raises(NeedsOverride) as err:
        say(raw)

    assert err.value.reason == "needs_override"


def test_text_consisting_only_of_address_is_blocked():
    with pytest.raises(NeedsOverride) as err:
        say("$N!")

    assert err.value.reason == "empty_after_address_removal"


# --- остальная сборка устной формы ---

def test_breaks_become_newlines_and_spaces_are_normalized():
    assert say("Первое.  $B$BВторое. $BТретье.") == "Первое.\n\nВторое.\nТретье."


def test_stage_direction_is_not_spoken():
    assert say("<Ева плачет.> Ушел...") == "Ушел..."


def test_world_state_value_cannot_be_spoken():
    with pytest.raises(NeedsOverride) as err:
        say("Осталось $2113w дней.")

    assert err.value.reason == "dynamic_value"


def test_gender_choice_must_be_expanded_first():
    with pytest.raises(ValueError):
        say("Ты $gготов:готова;?")

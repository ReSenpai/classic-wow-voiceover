from pathlib import Path

import pytest

from voru.normalize.pronunciation import Entry
from voru.normalize.prepare import Blocked, Override, Variant, load_overrides, prepare_text, source_hash

# Текст квеста 947 «Грибы из пещеры» (взятие), восстановлен по скриншоту клиента
# (reference/WowClassic_uh51Hx8CKc.png); имя игрока заменено обратно на $N.
QUEST_947_ACCEPT = (
    "Я тут составляю одно зелье, для которого нужны редкие грибы, растущие в одной-единственной пещере. "
    "Пещера эта находится за водопадом Скалистый, к востоку и чуть севернее в горах.$B$B"
    "Я бы и сам туда пошел, но в Роще Древних мне порекомендовали держаться подальше от того места. "
    "Наши почтенные союзники чувствуют, что в этой пещере таится какое-то незнакомое зло.$B$B"
    "Прошу вас, $N, соберите для меня эти грибы. А в процессе заодно приглядитесь: "
    "может быть, вы сможете подтвердить опасения Дерев."
)


def test_quest_947_has_no_player_address_in_spoken_text():
    """Регрессия: corpus/pilot/known_defects.yaml — adventurer-947-accept."""
    (variant,) = prepare_text("quest:947:accept", QUEST_947_ACCEPT)

    assert variant.player_gender is None
    assert "Прошу вас, соберите для меня эти грибы." in variant.spoken_text
    assert "$" not in variant.spoken_text
    assert "Адвенчур" not in variant.spoken_text and "Герой" not in variant.spoken_text


def test_gender_variants_are_produced():
    result = prepare_text("quest:1:accept", "Ты $gготов:готова;, $N?")

    assert result == (
        Variant(player_gender="m", spoken_text="Ты готов?"),
        Variant(player_gender="f", spoken_text="Ты готова?"),
    )


@pytest.mark.parametrize("raw", [None, "", "   "])
def test_missing_locale_is_blocked_not_replaced(raw):
    assert prepare_text("quest:1:accept", raw) == Blocked("missing_locale")


def test_markup_error_is_blocked_with_reason():
    result = prepare_text("quest:1:accept", "Привет, $x!")

    assert isinstance(result, Blocked)
    assert result.reason == "unknown_token"


def test_address_inside_phrase_is_blocked():
    result = prepare_text("quest:1:accept", "Ты похож на $c.")

    assert isinstance(result, Blocked)
    assert result.reason == "needs_override"


def test_override_replaces_source_text():
    raw = "Ты похож на $c."
    overrides = {"quest:1:accept": Override(source_sha256=source_hash(raw), text="Ты похож на бывалого бойца.", reason="")}

    (variant,) = prepare_text("quest:1:accept", raw, overrides)

    assert variant.spoken_text == "Ты похож на бывалого бойца."


def test_override_text_may_keep_gender_markup():
    raw = "Ты похож на $c."
    overrides = {"quest:1:accept": Override(source_hash(raw), "Ты $gпохож:похожа; на бойца.", "")}

    result = prepare_text("quest:1:accept", raw, overrides)

    assert [v.spoken_text for v in result] == ["Ты похож на бойца.", "Ты похожа на бойца."]


def test_stale_override_is_blocked():
    overrides = {"quest:1:accept": Override(source_hash("старый текст"), "правка", "")}

    assert prepare_text("quest:1:accept", "новый текст", overrides) == Blocked("stale_override")


def test_numbers_are_expanded():
    (variant,) = prepare_text("quest:1:accept", "Принесите 1 мертвянку, $N.")

    assert variant.spoken_text == "Принесите одну мертвянку."


def test_untranslated_english_is_blocked():
    result = prepare_text("quest:1:accept", "Greetings, $N.")

    assert isinstance(result, Blocked)
    assert result.reason == "latin_text"


def test_pronunciation_dictionary_is_applied():
    dictionary = {"еще": Entry("еще", "ещё", "test")}

    (variant,) = prepare_text("quest:1:accept", "Еще раз, $N.", dictionary=dictionary)

    assert variant.spoken_text == "Ещё раз."


def test_load_overrides_from_yaml(tmp_path: Path):
    path = tmp_path / "overrides.yaml"
    path.write_text(
        "- key: quest:1:accept\n"
        "  source_sha256: abc\n"
        "  text: Ты похож на бойца.\n"
        "  reason: обращение внутри фразы\n",
        encoding="utf-8",
    )

    assert load_overrides(path) == {
        "quest:1:accept": Override("abc", "Ты похож на бойца.", "обращение внутри фразы"),
    }


def test_load_overrides_rejects_duplicate_keys(tmp_path: Path):
    path = tmp_path / "overrides.yaml"
    entry = "- key: quest:1:accept\n  source_sha256: abc\n  text: x\n  reason: y\n"
    path.write_text(entry + entry, encoding="utf-8")

    with pytest.raises(ValueError, match="quest:1:accept"):
        load_overrides(path)


def test_repo_overrides_file_is_valid():
    load_overrides()

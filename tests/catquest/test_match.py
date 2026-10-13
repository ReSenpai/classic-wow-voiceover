"""Сопоставление реплик CatQuest с целевым корпусом (дизайн CQ §7)."""
import hashlib

import pytest

from voru.catquest.match import Decision, match_line, match_pack, target_index
from voru.catquest.reader import SourceLine, SourcePack
from voru.corpus.record import SourceRecord
from voru.normalize.prepare import source_hash


def rec(quest_id, stage, raw, npc_id=100, sex=0, npc_type="creature"):
    return SourceRecord(
        schema_version=1, content_id=f"quest:{quest_id}:{stage}:{npc_type}:{npc_id}", text_key=f"quest:{quest_id}:{stage}",
        client_flavor="vanilla", client_build=70003, locale="ruRU", quest_id=quest_id, quest_title=None, zone_id=141,
        stage=stage, npc_type=npc_type, npc_id=npc_id, npc_name="NPC", npc_race_id=4, npc_sex_id=sex,
        speaker_type="npc", raw_text=raw, raw_text_en=None, source_ref="test", source_revision="test",
        locale_status="ok" if raw else "missing_locale")


def line(text, quest_id=1, stage="accept", gender=None, voice="nightelf-male", audio="a" * 64):
    suffix = {"accept": "", "complete": "_t"}[stage] + (f"_{gender}" if gender else "")
    return SourceLine(quest_id, stage, gender, f"Sounds/q/{quest_id}{suffix}.ogg", voice, "eleven_v4", 2.0, text,
                      audio)


def run(source_line, *records, overrides=None):
    return match_line(source_line, target_index(records), overrides or {})


# --- exact: безопасная нормализация ---

@pytest.mark.parametrize("target, spoken", [
    ("Лес ждет тебя.", "Лес ждёт тебя."),  # ё
    ("Иди - быстро!", "Иди – быстро!"),  # тире
    ("Он сказал: \"Иди\".", "Он сказал: «Иди»."),  # кавычки
    ("Раз.$B$BДва.", "Раз. Два."),  # переносы
    ("Подожди...", "Подожди…"),  # многоточие
])
def test_safe_normalization_is_exact(target, spoken):
    assert run(line(spoken), rec(1, "accept", target)).status == "exact"


@pytest.mark.parametrize("target, spoken", [
    ("Будь осторожен, $N.", "Будь осторожен."),  # обращение убрано
    ("Привет, $N! Лес ждет.", "Привет, юный герой! Лес ждет."),  # заменено словами
    ("Ты $Gпомог:помогла; нам, $C.", "Ты помог нам, друид."),
])
def test_player_name_slot_is_exact_and_marked(target, spoken):
    decision = run(line(spoken, gender="m"), rec(1, "accept", target))

    assert decision.status == "exact"
    assert decision.address is True


def test_numbers_and_names_are_not_normalized_away():
    decision = run(line("Убей три волка в Дарнассе."), rec(1, "accept", "Убей 3 волка в Дарнасе."))

    assert decision.status == "needs_review"
    assert decision.diff == [("3", "три"), ("дарнасе", "дарнассе")]


def test_gender_variant_is_compared_with_its_own_target():
    target = rec(1, "accept", "Ты $Gготов:готова;?")

    assert run(line("Ты готова?", gender="f"), target).status == "exact"
    assert run(line("Ты готов?", gender="f"), target).status == "needs_review"


def test_neutral_file_must_fit_both_player_genders():
    """Общий файл CatQuest играет обоим полам — в мужском и женском тексте он обязан совпасть."""
    target = rec(1, "accept", "Ты $Gготов:готова;? Иди.")

    assert run(line("Ты готов? Иди."), target).status == "needs_review"
    assert run(line("Иди."), rec(1, "accept", "Иди.")).status == "exact"


def test_gendered_file_against_neutral_target():
    assert run(line("Иди, юная героиня.", gender="f"), rec(1, "accept", "Иди, $N.")).status == "exact"


# --- прочие статусы ---

def test_target_missing():
    assert run(line("Текст.", quest_id=99260), rec(1, "accept", "Текст.")).status == "target_missing"


def test_stage_is_part_of_the_key():
    assert run(line("Текст.", stage="complete"), rec(1, "accept", "Текст.")).status == "target_missing"


def test_completely_different_text_is_content_mismatch():
    decision = run(line("Совсем другая история про драконов и золото."),
                   rec(1, "accept", "Принеси мне десять шкур волков из леса."))

    assert decision.status == "content_mismatch"


def test_missing_audio():
    assert run(line("Текст.", audio=None), rec(1, "accept", "Текст.")).status == "audio_missing"


def test_no_subtitles_needs_review():
    decision = run(line(None), rec(1, "accept", "Текст."))

    assert (decision.status, decision.reason) == ("needs_review", "no_source_text")


def test_target_without_russian_text():
    assert run(line("Текст."), rec(1, "accept", None)).status == "target_missing"


def test_best_of_several_speakers_wins():
    decision = run(line("Второй текст."), rec(1, "accept", "Первый текст.", npc_id=1),
                   rec(1, "accept", "Второй текст.", npc_id=2))

    assert (decision.status, decision.target_npc_id) == ("exact", 2)


@pytest.mark.parametrize("voice, sex, status", [
    ("nightelf-female", 0, "needs_review"),
    ("nightelf-male", 0, "exact"),
    ("scourge-female#80", 1, "exact"),
    ("narrator", 0, "exact"),
])
def test_speaker_sex_must_agree(voice, sex, status):
    assert run(line("Текст.", voice=voice), rec(1, "accept", "Текст.", sex=sex)).status == status


def test_hashes_are_recorded():
    raw = "Текст."
    decision = run(line("Текст."), rec(1, "accept", raw))

    assert decision.source_text_sha256 == hashlib.sha256("Текст.".encode()).hexdigest()
    assert decision.target_text_sha256 == source_hash(raw)


# --- ручные решения ---

def override_for(decision, verdict="approved_variant", **change):
    entry = {"quest_id": decision.quest_id, "stage": decision.stage, "player_gender": decision.player_gender,
             "source_text_sha256": decision.source_text_sha256, "target_text_sha256": decision.target_text_sha256,
             "source_audio_sha256": decision.source_audio_sha256, "decision": verdict,
             "reason": "клиент пишет «Дарнасс»", "reviewer": "test"}
    entry.update(change)
    return {(entry["quest_id"], entry["stage"], entry["player_gender"]): entry}


def test_human_approval_makes_variant():
    src, tgt = line("Иди в Дарнасс."), rec(1, "accept", "Иди в Дарнас.")
    first = run(src, tgt)

    decision = run(src, tgt, overrides=override_for(first))

    assert (first.status, decision.status) == ("needs_review", "approved_variant")
    assert decision.reason == "клиент пишет «Дарнасс»"


def test_human_rejection_is_kept():
    src, tgt = line("Иди в Дарнасс."), rec(1, "accept", "Иди в Дарнас.")

    decision = run(src, tgt, overrides=override_for(run(src, tgt), verdict="content_mismatch"))

    assert decision.status == "content_mismatch"


@pytest.mark.parametrize("field", ["source_text_sha256", "target_text_sha256", "source_audio_sha256"])
def test_changed_input_voids_human_approval(field):
    src, tgt = line("Иди в Дарнасс."), rec(1, "accept", "Иди в Дарнас.")

    decision = run(src, tgt, overrides=override_for(run(src, tgt), **{field: "0" * 64}))

    assert (decision.status, decision.reason) == ("needs_review", "stale_override")


def test_match_pack_reports_by_status():
    pack = SourcePack("0.6.1", None, lines=[line("Иди."), line("Иди.", stage="complete"), line("Х.", quest_id=7)])

    decisions = match_pack(pack, [rec(1, "accept", "Иди."), rec(1, "complete", "Стой.")])

    assert [d.status for d in decisions] == ["exact", "content_mismatch", "target_missing"]
    assert isinstance(decisions[0], Decision)

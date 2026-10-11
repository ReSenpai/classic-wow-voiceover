import dataclasses
import textwrap

import pytest

from voru.casting import CastingError, cast, load_casting
from voru.config import load_client_profile
from voru.corpus.record import read_jsonl, record_from_row
from voru.config import REPO_ROOT

VALID = """
voices:
  - voice_id: nightelf-male-calm
    revision: "1"
    sex: male
    description: спокойный взрослый ночной эльф
  - voice_id: nightelf-female-calm
    revision: "1"
    sex: female
    description: спокойная взрослая ночная эльфийка
  - voice_id: nightelf-female-sentinel
    revision: "2"
    sex: female
    description: собранная часовая, короткие фразы
    seed: 777
    params:
      f5-tts-ru: {nfe_step: 32}
  - voice_id: satyr-male
    revision: "1"
    sex: male
    description: хитрый сатир
  - voice_id: narrator
    revision: "1"
    sex: any
    description: нейтральный рассказчик
casting:
  npcs:
    creature:2150: satyr-male
  archetypes:
    - match: Часовой
      race: 4
      sex: female
      voice: nightelf-female-sentinel
  race_sex:
    4:male: nightelf-male-calm
    4:female: nightelf-female-calm
  narrator: narrator
  unknown_creature: block
"""


def write(tmp_path, text):
    path = tmp_path / "voices.yaml"
    path.write_text(textwrap.dedent(text), encoding="utf-8")
    return path


@pytest.fixture
def casting(tmp_path):
    return load_casting(write(tmp_path, VALID))


CLIENT = load_client_profile()


def npc(npc_id=2080, name="Деналан", race=4, sex=0, npc_type="creature"):
    row = {
        "quest_id": 1, "quest_title_en": "", "quest_title_ru": "", "zone_id": 141, "stage": "accept",
        "npc_type": npc_type, "npc_id": npc_id, "npc_name_en": "", "npc_name_ru": name,
        "npc_race_id": race, "npc_sex_id": sex, "text_en": "x", "text_ru": "Привет.",
    }
    return record_from_row(row, CLIENT, "test")


# --- порядок выбора ---

def test_race_sex_base_voice(casting):
    decision = cast(npc(), casting)

    assert (decision.voice_id, decision.rule) == ("nightelf-male-calm", "race_sex")


def test_female_npc_gets_female_voice(casting):
    assert cast(npc(name="Сирел Остролист", sex=1), casting).voice_id == "nightelf-female-calm"


def test_archetype_by_name_and_race_sex(casting):
    decision = cast(npc(npc_id=3519, name="Часовой Арания Проблеск Солнца", sex=1), casting)

    assert (decision.voice_id, decision.rule) == ("nightelf-female-sentinel", "archetype")


def test_archetype_requires_matching_sex(casting):
    assert cast(npc(name="Часовой Кто-то", sex=0), casting).voice_id == "nightelf-male-calm"


def test_explicit_npc_profile_wins(casting):
    decision = cast(npc(npc_id=2150, name="Зенн Грязное Копыто", race=None, sex=None), casting)

    assert (decision.voice_id, decision.rule) == ("satyr-male", "npc")


@pytest.mark.parametrize("npc_type", ["gameobject", "item"])
def test_objects_and_items_are_narrated(casting, npc_type):
    decision = cast(npc(npc_type=npc_type, race=None, sex=None), casting)

    assert (decision.voice_id, decision.rule) == ("narrator", "narrator")


# --- неизвестное не становится «человеком-мужчиной» ---

def test_creature_without_race_is_blocked(casting):
    with pytest.raises(CastingError) as err:
        cast(npc(npc_id=15624, name="Лесной огонек", race=None, sex=None), casting)

    assert err.value.reason == "no_voice"
    assert "15624" in str(err.value)


def test_race_without_mapping_is_blocked(casting):
    with pytest.raises(CastingError):
        cast(npc(race=1, sex=0), casting)  # человек — в этом кастинге не описан


def test_unknown_creature_policy_narrator(tmp_path):
    casting = load_casting(write(tmp_path, VALID.replace("unknown_creature: block", "unknown_creature: narrator")))

    assert cast(npc(race=None, sex=None), casting).rule == "narrator_fallback"


# --- стабильность и параметры ---

def test_decision_is_stable(casting):
    assert cast(npc(), casting) == cast(npc(), casting)


def test_voice_profile_details(casting):
    profile = casting.voices["nightelf-female-sentinel"]

    assert profile.revision == "2"
    assert profile.seed == 777
    assert profile.params_for("f5-tts-ru") == {"nfe_step": 32}
    assert profile.params_for("qwen3-tts") == {}


def test_default_seed_is_derived_from_voice_id(casting):
    a = casting.voices["nightelf-male-calm"].seed
    b = casting.voices["nightelf-female-calm"].seed

    assert isinstance(a, int) and a != b
    assert a == load_casting(casting.path).voices["nightelf-male-calm"].seed


def test_voice_ref(casting, tmp_path):
    ref = casting.voices["nightelf-male-calm"].voice_ref(tmp_path)

    assert (ref.voice_id, ref.voice_revision, ref.reference_audio, ref.reference_text) == \
        ("nightelf-male-calm", "1", None, None)


# --- проверки реестра ---

@pytest.mark.parametrize("broken, message", [
    (VALID.replace("voice_id: satyr-male", "voice_id: narrator"), "duplicate"),
    (VALID.replace("creature:2150: satyr-male", "creature:2150: nobody"), "nobody"),
    (VALID.replace("4:female: nightelf-female-calm", "4:female: nightelf-male-calm"), "sex"),
    (VALID.replace("      sex: female\n      voice: nightelf-female-sentinel",
                   "      sex: male\n      voice: nightelf-female-sentinel"), "sex"),
    (VALID.replace("unknown_creature: block", "unknown_creature: human"), "unknown_creature"),
    (VALID.replace("    4:male:", "    four:male:"), "four"),
])
def test_invalid_registry_rejected(tmp_path, broken, message):
    with pytest.raises(ValueError, match=message):
        load_casting(write(tmp_path, broken))


REFERENCE = """
    reference_audio: refs/nightelf-male-calm.wav
    reference_text: Пусть Элуна осветит твой путь.
    provenance: сгенерировано Qwen3-TTS VoiceDesign, 2026-10-12
    license: Apache-2.0 (модель); голос создан нами
"""


def test_reference_with_full_provenance_is_accepted(tmp_path):
    text = VALID.replace("    description: спокойный взрослый ночной эльф\n",
                         "    description: спокойный взрослый ночной эльф" + REFERENCE)
    profile = load_casting(write(tmp_path, text)).voices["nightelf-male-calm"]

    ref = profile.voice_ref(tmp_path)
    assert ref.reference_audio == tmp_path / "refs" / "nightelf-male-calm.wav"
    assert ref.reference_text == "Пусть Элуна осветит твой путь."


@pytest.mark.parametrize("missing", ["reference_text", "provenance", "license"])
def test_reference_requires_transcript_and_provenance(tmp_path, missing):
    lines = [l for l in REFERENCE.splitlines() if not l.strip().startswith(missing)]
    text = VALID.replace("    description: спокойный взрослый ночной эльф\n",
                         "    description: спокойный взрослый ночной эльф" + "\n".join(lines) + "\n")

    with pytest.raises(ValueError, match=missing):
        load_casting(write(tmp_path, text))


# --- кастинг пилота из репозитория ---

def test_repo_casting_is_valid():
    load_casting()


def test_every_pilot_speaker_has_a_voice():
    casting = load_casting()
    pilot = read_jsonl(REPO_ROOT / "corpus" / "pilot" / "teldrassil.jsonl")

    decisions = {(r.npc_type, r.npc_id): cast(r, casting) for r in pilot}

    voices = {d.voice_id for d in decisions.values()}
    assert len(voices) >= 4
    for r in pilot:
        sex = casting.voices[decisions[(r.npc_type, r.npc_id)].voice_id].sex
        if r.npc_sex_id == 1:
            assert sex == "female", r.npc_name
        if r.npc_sex_id == 0:
            assert sex == "male", r.npc_name

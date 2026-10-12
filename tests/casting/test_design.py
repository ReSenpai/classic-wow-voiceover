import textwrap
import wave

import pytest

from voru.casting import load_casting
from voru.casting.design import design_candidates, pick_candidate

VOICES = """
# комментарий в начале — должен сохраниться
voices:
  - voice_id: nightelf-male-calm
    revision: "1"
    sex: male
    description: Взрослый ночной эльф, спокойный.
    seed: 100
    test_lines:
      - Пусть Элуна осветит твой путь, странник.
      - Лес помнит всё.

  - voice_id: dryad-female
    revision: "3"
    sex: female
    description: Дриада, звонкая.
    design_prompt: A young playful forest dryad, light bright female voice.
    test_lines:
      - Я вижу, тебе удалось найти меня!

casting:
  npcs: {}
  race_sex:
    4:male: nightelf-male-calm
  narrator: nightelf-male-calm
"""


class FakeDesigner:
    model_revision = "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign@abc"

    def __init__(self):
        self.calls = []

    def design_batch(self, texts, instructs, seed):
        self.calls.append({"texts": texts, "instructs": instructs, "seed": seed})
        return [([0.1 * (i + 1), -0.1] * 12000, 24000) for i in range(len(texts))]


@pytest.fixture
def voices(tmp_path):
    path = tmp_path / "config" / "voices.yaml"
    path.parent.mkdir()
    path.write_text(textwrap.dedent(VOICES), encoding="utf-8")
    return path


def test_candidates_use_description_and_test_lines(voices, tmp_path):
    designer = FakeDesigner()

    paths = design_candidates(load_casting(voices), "nightelf-male-calm", designer, tmp_path / "work", count=3)

    assert [p.name for p in paths] == ["seed-100.wav", "seed-101.wav", "seed-102.wav"]
    assert all(p.exists() for p in paths)
    (call,) = designer.calls  # все варианты голоса — один батч
    assert call["texts"] == ["Пусть Элуна осветит твой путь, странник. Лес помнит всё."] * 3
    assert call["instructs"] == ["Взрослый ночной эльф, спокойный."] * 3
    assert call["seed"] == 100
    assert len({p.read_bytes() for p in paths}) == 3
    with wave.open(str(paths[0])) as w:
        assert w.getframerate() == 24000


def test_new_candidates_are_appended_not_overwritten(voices, tmp_path):
    casting = load_casting(voices)
    first = design_candidates(casting, "nightelf-male-calm", FakeDesigner(), tmp_path / "work", count=2)
    liked = first[1].read_bytes()

    designer = FakeDesigner()
    more = design_candidates(casting, "nightelf-male-calm", designer, tmp_path / "work", count=3)

    assert [p.name for p in more] == ["seed-102.wav", "seed-103.wav", "seed-104.wav"]
    assert [c["seed"] for c in designer.calls] == [102]
    assert first[1].read_bytes() == liked


def test_large_count_is_split_into_batches(voices, tmp_path):
    designer = FakeDesigner()

    paths = design_candidates(load_casting(voices), "nightelf-male-calm", designer, tmp_path / "work",
                              count=5, batch_size=2)

    assert [len(c["texts"]) for c in designer.calls] == [2, 2, 1]
    assert [c["seed"] for c in designer.calls] == [100, 102, 104]
    assert [p.name for p in paths] == [f"seed-{s}.wav" for s in range(100, 105)]


def test_candidate_records_its_batch(voices, tmp_path):
    import json

    paths = design_candidates(load_casting(voices), "nightelf-male-calm", FakeDesigner(), tmp_path / "work", count=3)

    meta = json.loads(paths[2].with_suffix(".json").read_text(encoding="utf-8"))
    assert (meta["seed"], meta["batch_seed"], meta["batch_index"], meta["batch_size"]) == (102, 100, 2, 3)


def test_candidate_remembers_its_prompt(voices, tmp_path):
    import json

    (path,) = design_candidates(load_casting(voices), "dryad-female", FakeDesigner(), tmp_path / "work", count=1)

    meta = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
    assert meta["instruct"] == "A young playful forest dryad, light bright female voice."


def test_design_prompt_overrides_description(voices, tmp_path):
    designer = FakeDesigner()

    design_candidates(load_casting(voices), "dryad-female", designer, tmp_path / "work", count=1)

    assert designer.calls[0]["instructs"] == ["A young playful forest dryad, light bright female voice."]


def test_pick_writes_reference_and_bumps_revision(voices, tmp_path):
    designer = FakeDesigner()
    design_candidates(load_casting(voices), "dryad-female", designer, tmp_path / "work", count=2)

    pick_candidate(voices, "dryad-female", tmp_path / "work", seed=1 + load_casting(voices).voices["dryad-female"].seed,
                   designer_revision=designer.model_revision, date="2026-10-11")

    casting = load_casting(voices)
    profile = casting.voices["dryad-female"]
    assert profile.revision == "4"
    assert profile.reference_audio == "voice_refs/dryad-female.wav"
    assert (voices.parent / "voice_refs" / "dryad-female.wav").exists()
    assert profile.reference_text == "Я вижу, тебе удалось найти меня!"
    assert "VoiceDesign@abc" in profile.provenance and "2026-10-11" in profile.provenance
    assert "Apache-2.0" in profile.license
    assert casting.voices["nightelf-male-calm"].revision == "1"  # другие голоса не тронуты
    assert voices.read_text(encoding="utf-8").startswith("\n# комментарий в начале")


def test_pick_twice_replaces_reference(voices, tmp_path):
    designer = FakeDesigner()
    casting = load_casting(voices)
    seed = casting.voices["nightelf-male-calm"].seed
    design_candidates(casting, "nightelf-male-calm", designer, tmp_path / "work", count=2)

    pick_candidate(voices, "nightelf-male-calm", tmp_path / "work", seed=seed, designer_revision="r", date="d")
    pick_candidate(voices, "nightelf-male-calm", tmp_path / "work", seed=seed + 1, designer_revision="r", date="d")

    profile = load_casting(voices).voices["nightelf-male-calm"]
    assert profile.revision == "3"
    assert f"seed {seed + 1}" in profile.provenance
    assert voices.read_text(encoding="utf-8").count("reference_audio:") == 1


def test_provenance_records_prompt_and_batch(voices, tmp_path):
    casting = load_casting(voices)
    seed = casting.voices["dryad-female"].seed
    design_candidates(casting, "dryad-female", FakeDesigner(), tmp_path / "work", count=3)

    pick_candidate(voices, "dryad-female", tmp_path / "work", seed=seed + 2, designer_revision="r", date="d")

    provenance = load_casting(voices).voices["dryad-female"].provenance
    assert f"батч {seed}, №3 из 3" in provenance
    assert "A young playful forest dryad" in provenance  # описание может позже измениться в voices.yaml


def _long_candidate(work, voice_id, seed, speech_s=2.1, pause_s=0.7, parts=5, rate=24000):
    """Кандидат длиннее 12 с: речь (тон) с длинными паузами между фразами."""
    import json
    import math

    frames = []
    for i in range(parts):
        frames += [int(8000 * math.sin(2 * math.pi * 220 * n / rate)) for n in range(int(rate * speech_s))]
        if i < parts - 1:
            frames += [0] * int(rate * pause_s)
    folder = work / "voice_design" / voice_id
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"seed-{seed}.wav"
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"".join(int(x).to_bytes(2, "little", signed=True) for x in frames))
    path.with_suffix(".json").write_text(json.dumps({"seed": seed, "text": "Хе-хе... Длинный текст.",
                                                     "instruct": "sly satyr"}), encoding="utf-8")
    return path


def _seconds(path):
    with wave.open(str(path)) as w:
        return w.getnframes() / w.getframerate()


def test_pick_fits_long_reference_by_shortening_pauses(voices, tmp_path):
    """Регрессия (12.10.2026): два выбранных голоса сатира были 13.2 и 12.3 с — F5 читает не больше 12 с."""
    from voru.casting.design import F5_MAX_REFERENCE_S

    source = _long_candidate(tmp_path / "work", "dryad-female", seed=7)
    assert _seconds(source) > F5_MAX_REFERENCE_S

    pick_candidate(voices, "dryad-female", tmp_path / "work", seed=7, designer_revision="r", date="d")

    ref = voices.parent / "voice_refs" / "dryad-female.wav"
    assert 11.0 < _seconds(ref) <= F5_MAX_REFERENCE_S  # 13.3 с: паузы 0.7 → 0.25 с
    profile = load_casting(voices).voices["dryad-female"]
    assert "паузы" in profile.provenance and "→" in profile.provenance


def test_pick_keeps_short_reference_untouched(voices, tmp_path):
    source = _long_candidate(tmp_path / "work", "dryad-female", seed=8, parts=2)

    pick_candidate(voices, "dryad-female", tmp_path / "work", seed=8, designer_revision="r", date="d")

    assert (voices.parent / "voice_refs" / "dryad-female.wav").read_bytes() == source.read_bytes()
    assert "паузы" not in load_casting(voices).voices["dryad-female"].provenance


def test_pick_refuses_reference_that_cannot_fit(voices, tmp_path):
    _long_candidate(tmp_path / "work", "dryad-female", seed=9, speech_s=3.0, pause_s=0.3)

    with pytest.raises(ValueError, match="12"):
        pick_candidate(voices, "dryad-female", tmp_path / "work", seed=9, designer_revision="r", date="d")
    assert not (voices.parent / "voice_refs" / "dryad-female.wav").exists()


def test_pick_unknown_candidate(voices, tmp_path):
    with pytest.raises(FileNotFoundError):
        pick_candidate(voices, "dryad-female", tmp_path / "work", seed=999, designer_revision="r", date="d")


def test_candidates_record_generation_session(voices, tmp_path):
    import json

    (path,) = design_candidates(load_casting(voices), "dryad-female", FakeDesigner(), tmp_path / "work", count=1,
                                session="2026-10-11T15:00")

    assert json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))["session"] == "2026-10-11T15:00"

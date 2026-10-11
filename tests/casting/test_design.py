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

    def design(self, text, instruct, seed):
        self.calls.append({"text": text, "instruct": instruct, "seed": seed})
        return [0.1, -0.1] * 12000, 24000


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
    call = designer.calls[0]
    assert call["text"] == "Пусть Элуна осветит твой путь, странник. Лес помнит всё."
    assert call["instruct"] == "Взрослый ночной эльф, спокойный."
    assert [c["seed"] for c in designer.calls] == [100, 101, 102]
    with wave.open(str(paths[0])) as w:
        assert w.getframerate() == 24000


def test_design_prompt_overrides_description(voices, tmp_path):
    designer = FakeDesigner()

    design_candidates(load_casting(voices), "dryad-female", designer, tmp_path / "work", count=1)

    assert designer.calls[0]["instruct"] == "A young playful forest dryad, light bright female voice."


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


def test_pick_unknown_candidate(voices, tmp_path):
    with pytest.raises(FileNotFoundError):
        pick_candidate(voices, "dryad-female", tmp_path / "work", seed=999, designer_revision="r", date="d")

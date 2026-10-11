import dataclasses
import hashlib
import math

import pytest

from voru.jobs.fingerprint import SynthesisInput, file_sha256, fingerprint
from voru.normalize import NORMALIZATION_REVISION


def make(**overrides):
    base = dict(
        model_text="Прошу вас, соберите для меня эти грибы.",
        locale="ruRU",
        player_gender=None,
        normalization_revision=1,
        voice_id="nightelf-male-calm",
        voice_revision="1",
        reference_audio_sha256="a" * 64,
        reference_text_sha256="b" * 64,
        delivery_profile="neutral",
        provider="f5-tts-ru",
        model_revision="Misha24-10/F5-TTS_RUSSIAN@abc123",
        adapter_version="1",
        generation_config={"seed": 42, "speed": 1.0, "nfe_step": 32},
    )
    base.update(overrides)
    return SynthesisInput(**base)


def test_fingerprint_is_sha256_hex():
    fp = fingerprint(make())

    assert len(fp) == 64 and int(fp, 16) >= 0


def test_fingerprint_is_stable_golden_value():
    """Изменение канонизации молча инвалидирует весь корпус — этот тест должен это поймать."""
    assert fingerprint(make()) == "296425aba7feca5db19b5a95504cc024faa1740a1f9d6bcf30a92b793c97c469"


def test_config_key_order_does_not_matter():
    a = make(generation_config={"seed": 42, "speed": 1.0})
    b = make(generation_config={"speed": 1.0, "seed": 42})

    assert fingerprint(a) == fingerprint(b)


def test_unicode_normalization_does_not_matter():
    composed = make(model_text="ещё")
    decomposed = make(model_text="ещ" + "ё")  # «е» + комбинируемая диерезис

    assert fingerprint(composed) == fingerprint(decomposed)


@pytest.mark.parametrize("field, value", [
    ("model_text", "Прошу вас, соберите грибы."),
    ("locale", "enUS"),
    ("player_gender", "f"),
    ("normalization_revision", 2),
    ("voice_id", "nightelf-female-priestess"),
    ("voice_revision", "2"),
    ("reference_audio_sha256", "c" * 64),
    ("reference_text_sha256", "d" * 64),
    ("delivery_profile", "anxious"),
    ("provider", "qwen3-tts"),
    ("model_revision", "Misha24-10/F5-TTS_RUSSIAN@def456"),
    ("adapter_version", "2"),
    ("generation_config", {"seed": 43, "speed": 1.0, "nfe_step": 32}),
])
def test_every_input_changes_fingerprint(field, value):
    assert fingerprint(make()) != fingerprint(make(**{field: value}))


def test_nested_config_is_canonical():
    a = make(generation_config={"sampler": {"top_p": 0.9, "temperature": 0.7}})
    b = make(generation_config={"sampler": {"temperature": 0.7, "top_p": 0.9}})

    assert fingerprint(a) == fingerprint(b)


def test_encoding_settings_are_not_part_of_synthesis_input():
    """Смена кодека/битрейта — переэкспорт, а не дорогой синтез (дизайн §5)."""
    names = {f.name for f in dataclasses.fields(SynthesisInput)}

    assert not names & {"codec", "bitrate", "format", "sample_rate", "loudness"}


@pytest.mark.parametrize("bad", [math.nan, math.inf])
def test_non_finite_numbers_rejected(bad):
    with pytest.raises(ValueError):
        fingerprint(make(generation_config={"speed": bad}))


def test_non_string_config_keys_rejected():
    with pytest.raises(TypeError):
        fingerprint(make(generation_config={1: "x"}))


def test_file_sha256(tmp_path):
    path = tmp_path / "ref.wav"
    path.write_bytes(b"RIFF" + bytes(100_000))

    assert file_sha256(path) == hashlib.sha256(b"RIFF" + bytes(100_000)).hexdigest()


def test_normalization_revision_is_declared():
    assert isinstance(NORMALIZATION_REVISION, int) and NORMALIZATION_REVISION >= 1

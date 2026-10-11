"""Адаптеры настоящих моделей без GPU: модель подменяется заглушкой, проверяется контракт вызова."""
import wave

import pytest

from voru.providers import get_provider
from voru.providers.base import SynthesisRequest, UnsupportedOption, VoiceRef
from voru.providers.f5_ru import F5_REPO, F5_REVISION, F5RuV2Provider, F5RuV4Provider
from voru.providers.qwen3 import QWEN_BASE_REPO, QWEN_BASE_REVISION, Qwen3BaseProvider


class FakeQwen:
    def __init__(self):
        self.calls = []

    def generate_voice_clone(self, **kwargs):
        self.calls.append(kwargs)
        return [[0.1, -0.1] * 2400], 24000


class FakeF5:
    def __init__(self):
        self.calls = []

    def infer(self, **kwargs):
        self.calls.append(kwargs)
        return [0.2, -0.2] * 2400, 24000, None


@pytest.fixture
def reference(tmp_path):
    path = tmp_path / "ref.wav"
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(24000)
        w.writeframes(b"\x00\x00" * 24000)
    return path


def request(tmp_path, reference, text="Тельдр+ассил ждёт.", config=None):
    return SynthesisRequest(
        text=text, locale="ruRU", player_gender=None,
        voice=VoiceRef("nightelf-male-calm", "1", reference, "Пусть Элуна осветит твой путь."),
        delivery_profile="neutral", generation_config=config or {"seed": 42},
        output_path=tmp_path / "out.wav",
    )


def loaded(provider, fake):
    provider._load = lambda: setattr(provider, "_model", fake)
    provider._apply_seed = lambda seed: setattr(provider, "applied_seed", seed)
    return provider


# --- Qwen3-TTS Base ---

def test_qwen_calls_voice_clone_in_russian_without_stress_marks(tmp_path, reference):
    fake = FakeQwen()
    provider = loaded(Qwen3BaseProvider(), fake)

    result = provider.synthesize(request(tmp_path, reference, config={"seed": 42, "temperature": 0.7}))

    (call,) = fake.calls
    assert call["text"] == "Тельдрассил ждёт."
    assert call["language"] == "Russian"
    assert call["ref_audio"] == str(reference)
    assert call["ref_text"] == "Пусть Элуна осветит твой путь."
    assert call["temperature"] == 0.7
    assert "seed" not in call
    assert provider.applied_seed == 42
    assert result.sample_rate == 24000
    assert result.duration_ms == 200


def test_qwen_requires_reference(tmp_path):
    req = SynthesisRequest(text="Привет.", locale="ruRU", player_gender=None,
                           voice=VoiceRef("v", "1", None, None), delivery_profile="neutral",
                           generation_config={"seed": 1}, output_path=tmp_path / "o.wav")

    with pytest.raises(UnsupportedOption) as err:
        Qwen3BaseProvider().synthesize(req)

    assert err.value.reason == "reference_required"


def test_qwen_rejects_unknown_config(tmp_path, reference):
    with pytest.raises(UnsupportedOption) as err:
        Qwen3BaseProvider().synthesize(request(tmp_path, reference, config={"seed": 1, "nfe_step": 32}))

    assert err.value.reason == "unsupported_config"


def test_qwen_revision_is_pinned():
    assert Qwen3BaseProvider().model_revision() == f"{QWEN_BASE_REPO}@{QWEN_BASE_REVISION}"
    assert len(QWEN_BASE_REVISION) == 40


# --- F5-TTS Russian ---

def test_f5_keeps_stress_marks_and_passes_seed(tmp_path, reference):
    fake = FakeF5()
    provider = loaded(F5RuV2Provider(), fake)

    provider.synthesize(request(tmp_path, reference, config={"seed": 42, "nfe_step": 48}))

    (call,) = fake.calls
    assert call["gen_text"] == "Тельдр+ассил ждёт."
    assert call["ref_file"] == str(reference)
    assert call["ref_text"] == "Пусть Элуна осветит твой путь."
    assert call["seed"] == 42
    assert call["nfe_step"] == 48


@pytest.mark.parametrize("provider_class, checkpoint", [
    (F5RuV2Provider, "F5TTS_v1_Base_v2/model_last_inference.safetensors"),
    (F5RuV4Provider, "F5TTS_v1_Base_v4_winter/model_212000.safetensors"),
])
def test_f5_checkpoints_are_pinned(provider_class, checkpoint):
    assert provider_class().model_revision() == f"{F5_REPO}@{F5_REVISION}:{checkpoint}"
    assert len(F5_REVISION) == 40


def test_f5_variants_have_different_fingerprints(tmp_path, reference):
    from voru.jobs.fingerprint import fingerprint

    req = request(tmp_path, reference)

    assert fingerprint(F5RuV2Provider().synthesis_input(req, 1)) != fingerprint(F5RuV4Provider().synthesis_input(req, 1))


# --- реестр: тяжёлые модули не импортируются до _load ---

@pytest.mark.parametrize("name, cls", [
    ("qwen3-tts-base", Qwen3BaseProvider), ("f5-tts-ru-v2", F5RuV2Provider), ("f5-tts-ru-v4", F5RuV4Provider),
])
def test_registry_names(name, cls):
    provider = get_provider(name)

    assert isinstance(provider, cls)
    assert provider.name == name

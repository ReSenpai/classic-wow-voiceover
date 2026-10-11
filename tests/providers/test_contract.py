import dataclasses
import wave

import pytest

from voru.jobs.fingerprint import fingerprint
from voru.providers import get_provider
from voru.providers.base import Capabilities, SynthesisRequest, UnsupportedOption, VoiceRef
from voru.providers.mock import MockProvider

TEXT = "Прошу вас, соберите для меня эти грибы."


def voice(**overrides):
    base = dict(voice_id="nightelf-male-calm", voice_revision="1", reference_audio=None, reference_text=None)
    base.update(overrides)
    return VoiceRef(**base)


def request(tmp_path, **overrides):
    base = dict(
        text=TEXT,
        locale="ruRU",
        player_gender=None,
        voice=voice(),
        delivery_profile="neutral",
        generation_config={"seed": 1},
        output_path=tmp_path / "out" / "947-accept.wav",
    )
    base.update(overrides)
    return SynthesisRequest(**base)


def caps(**overrides):
    return dataclasses.replace(MockProvider.default_capabilities, **overrides)


# --- результат синтеза ---

def test_mock_writes_valid_wav(tmp_path):
    result = MockProvider().synthesize(request(tmp_path))

    assert result.path == tmp_path / "out" / "947-accept.wav"
    with wave.open(str(result.path)) as w:
        assert w.getnchannels() == 1
        assert w.getframerate() == result.sample_rate
        assert w.getnframes() > 0
        assert result.duration_ms == w.getnframes() * 1000 // w.getframerate()


def test_result_describes_what_was_generated(tmp_path):
    result = MockProvider().synthesize(request(tmp_path, generation_config={"seed": 7}))

    assert result.provider == "mock"
    assert result.model_revision == MockProvider().model_revision()
    assert result.generation_config == {"seed": 7}
    assert result.elapsed_s >= 0
    assert result.warnings == ()


def test_longer_text_gives_longer_audio(tmp_path):
    short = MockProvider().synthesize(request(tmp_path, text="Привет.", output_path=tmp_path / "a.wav"))
    long = MockProvider().synthesize(request(tmp_path, output_path=tmp_path / "b.wav"))

    assert long.duration_ms > short.duration_ms


def test_mock_is_deterministic(tmp_path):
    a = MockProvider().synthesize(request(tmp_path, output_path=tmp_path / "a.wav"))
    b = MockProvider().synthesize(request(tmp_path, output_path=tmp_path / "b.wav"))

    assert a.path.read_bytes() == b.path.read_bytes()


def test_different_voices_sound_different(tmp_path):
    a = MockProvider().synthesize(request(tmp_path, output_path=tmp_path / "a.wav"))
    b = MockProvider().synthesize(request(tmp_path, voice=voice(voice_id="nightelf-female-priestess"),
                                          output_path=tmp_path / "b.wav"))

    assert a.path.read_bytes() != b.path.read_bytes()


def test_no_temp_files_left_behind(tmp_path):
    MockProvider().synthesize(request(tmp_path))

    assert [p.name for p in (tmp_path / "out").iterdir()] == ["947-accept.wav"]


def test_failed_generation_leaves_no_output(tmp_path):
    class Broken(MockProvider):
        def _generate(self, model_text, req):
            raise RuntimeError("CUDA out of memory")

    with pytest.raises(RuntimeError):
        Broken().synthesize(request(tmp_path))

    out = tmp_path / "out"
    assert not out.exists() or list(out.iterdir()) == []


def test_existing_output_not_damaged_by_failed_attempt(tmp_path):
    good = MockProvider().synthesize(request(tmp_path))
    before = good.path.read_bytes()

    class Broken(MockProvider):
        def _generate(self, model_text, req):
            raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        Broken().synthesize(request(tmp_path))

    assert good.path.read_bytes() == before


# --- ленивая загрузка: одна модель на провайдер ---

def test_model_loaded_lazily_and_once(tmp_path):
    provider = MockProvider()
    assert provider.load_count == 0

    provider.synthesize(request(tmp_path, output_path=tmp_path / "a.wav"))
    provider.synthesize(request(tmp_path, output_path=tmp_path / "b.wav"))

    assert provider.load_count == 1


# --- неподдерживаемые настройки — ошибка, а не тихое игнорирование ---

@pytest.mark.parametrize("capabilities, overrides, reason", [
    (caps(), {"locale": "deDE"}, "unsupported_language"),
    (caps(), {"delivery_profile": "anxious"}, "unsupported_delivery"),
    (caps(), {"generation_config": {"seed": 1, "temperature": 0.7}}, "unsupported_config"),
    (caps(), {"generation_config": {}}, "seed_required"),
    (caps(), {"text": "   "}, "empty_text"),
    (caps(max_chars=10), {}, "text_too_long"),
    (caps(voice_reference=False), {"voice": voice(reference_audio="ref.wav", reference_text="текст")},
     "unsupported_voice_reference"),
    (caps(requires_reference=True), {}, "reference_required"),
])
def test_unsupported_options_raise(tmp_path, capabilities, overrides, reason):
    provider = MockProvider(capabilities=capabilities)

    with pytest.raises(UnsupportedOption) as err:
        provider.synthesize(request(tmp_path, **overrides))

    assert err.value.reason == reason
    assert provider.load_count == 0  # проверка до загрузки модели


def test_reference_requires_transcript(tmp_path):
    with pytest.raises(UnsupportedOption) as err:
        MockProvider().synthesize(request(tmp_path, voice=voice(reference_audio="ref.wav")))

    assert err.value.reason == "reference_text_required"


# --- вход модели и fingerprint ---

def test_stress_marks_kept_only_when_supported(tmp_path):
    req = request(tmp_path, text="Тельдр+ассил.")

    assert MockProvider(capabilities=caps(stress_marks=True)).model_text(req) == "Тельдр+ассил."
    assert MockProvider(capabilities=caps(stress_marks=False)).model_text(req) == "Тельдрассил."


def test_synthesis_input_for_fingerprint(tmp_path):
    ref = tmp_path / "ref.wav"
    ref.write_bytes(b"RIFF-fake")
    req = request(tmp_path, text="Тельдр+ассил.",
                  voice=voice(reference_audio=ref, reference_text="Пример речи."))

    si = MockProvider(capabilities=caps(stress_marks=False)).synthesis_input(req, normalization_revision=3)

    assert si.model_text == "Тельдрассил."
    assert si.normalization_revision == 3
    assert si.provider == "mock"
    assert si.adapter_version == MockProvider.adapter_version
    assert si.reference_audio_sha256 is not None and si.reference_text_sha256 is not None
    assert fingerprint(si)


def test_stress_change_does_not_touch_fingerprint_of_provider_without_stress(tmp_path):
    provider = MockProvider(capabilities=caps(stress_marks=False))
    a = provider.synthesis_input(request(tmp_path, text="Тельдрассил."), 1)
    b = provider.synthesis_input(request(tmp_path, text="Тельдр+ассил."), 1)

    assert fingerprint(a) == fingerprint(b)


# --- реестр провайдеров ---

def test_registry_returns_mock():
    assert isinstance(get_provider("mock"), MockProvider)


def test_registry_unknown_provider():
    with pytest.raises(KeyError, match="nope"):
        get_provider("nope")

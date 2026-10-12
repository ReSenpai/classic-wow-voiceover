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


def test_qwen_loads_from_pinned_snapshot(monkeypatch):
    """qwen-tts грузит процессор и generate_config без revision — закрепляем весь снимок репозитория."""
    import sys
    import types

    calls = {}
    hub = types.SimpleNamespace(snapshot_download=lambda repo, revision: calls.setdefault("snapshot", (repo, revision))
                                and "/cache/qwen-base")
    torch = types.SimpleNamespace(bfloat16="bf16")

    class FakeModelClass:
        @staticmethod
        def from_pretrained(path, **kwargs):
            calls["from_pretrained"] = (path, kwargs)
            return "model"

    monkeypatch.setitem(sys.modules, "huggingface_hub", hub)
    monkeypatch.setitem(sys.modules, "torch", torch)
    monkeypatch.setitem(sys.modules, "qwen_tts", types.SimpleNamespace(Qwen3TTSModel=FakeModelClass))

    provider = Qwen3BaseProvider()
    provider._load()

    assert calls["snapshot"] == (QWEN_BASE_REPO, QWEN_BASE_REVISION)
    path, kwargs = calls["from_pretrained"]
    assert path == "/cache/qwen-base"
    assert "revision" not in kwargs
    assert kwargs["dtype"] == "bf16"


# --- Qwen3-TTS Base, дообученная на ударения (siriusfreak/…-ru-stress-cf) ---

@pytest.mark.parametrize("marked, expected", [
    ("Тельдрасс+ил ждёт.", "Тельдрасси́л ждёт."),
    ("+Этот З+енн", "Э́тот Зе́нн"),
    ("вс+ё, ещ+Ё", "всё́, ещЁ́"),
    ("без ударений", "без ударений"),
])
def test_stress_marks_become_combining_acute_after_vowel(marked, expected):
    from voru.providers.qwen3 import to_combining_acute

    assert to_combining_acute(marked) == expected


def test_qwen_stress_passes_acute_marks_to_model(tmp_path, reference):
    from voru.providers.qwen3 import Qwen3StressProvider

    fake = FakeQwen()
    provider = loaded(Qwen3StressProvider(), fake)

    provider.synthesize(request(tmp_path, reference, text="Тельдр+ассил ждёт."))

    (call,) = fake.calls
    assert call["text"] == "Тельдра́ссил ждёт."
    assert call["language"] == "Russian"
    assert provider.capabilities.stress_marks


def test_qwen_stress_is_pinned_and_differs_from_base(tmp_path, reference):
    from voru.jobs.fingerprint import fingerprint
    from voru.providers.qwen3 import QWEN_STRESS_REPO, QWEN_STRESS_REVISION, Qwen3StressProvider

    req = request(tmp_path, reference)

    assert Qwen3StressProvider().model_revision() == f"{QWEN_STRESS_REPO}@{QWEN_STRESS_REVISION}"
    assert len(QWEN_STRESS_REVISION) == 40
    assert fingerprint(Qwen3StressProvider().synthesis_input(req, 1)) != \
        fingerprint(Qwen3BaseProvider().synthesis_input(req, 1))


def test_stress_mark_on_non_vowel_is_an_error():
    from voru.providers.qwen3 import to_combining_acute

    with pytest.raises(ValueError):
        to_combining_acute("Сл+ава +!")


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


def test_f5_text_is_chunked_by_sentences_with_pauses(tmp_path):
    """Регрессия «обрыв на "Может,"»: F5 сам резал по запятой — режем по предложениям сами."""
    from voru.normalize.chunking import PARAGRAPH_PAUSE_S, SENTENCE_PAUSE_S

    ref = tmp_path / "long_ref.wav"
    with wave.open(str(ref), "wb") as w:  # 10 с референса, транскрипт 72 байта → лимит ~86 байт
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(24000)
        w.writeframes(b"\x00\x00" * 240000)
    text = "Принеси мне ростки. Может, позже ты ещё увидишь результаты!\n\nСпасибо."
    req = SynthesisRequest(text=text, locale="ruRU", player_gender=None,
                           voice=VoiceRef("v", "1", ref, "Пусть луна осветит твой путь, странник."),
                           delivery_profile="neutral",
                           generation_config={"seed": 7}, output_path=tmp_path / "out.wav")
    fake = FakeF5()

    result = loaded(F5RuV4Provider(), fake).synthesize(req)

    assert [c["gen_text"] for c in fake.calls] == [
        "Принеси мне ростки.", "Может, позже ты ещё увидишь результаты!", "Спасибо."]
    assert all(c["seed"] == 7 for c in fake.calls)
    pause_ms = int((SENTENCE_PAUSE_S + PARAGRAPH_PAUSE_S) * 1000)
    assert result.duration_ms == 3 * 200 + pause_ms


class PaddedF5(FakeF5):
    """Как настоящий F5: каждый кусок с ~0.5 с тишины по краям."""
    def infer(self, **kwargs):
        self.calls.append(kwargs)
        silence = [0.0] * 12000
        return silence + [0.2, -0.2] * 2400 + silence, 24000, None


def test_f5_trims_chunk_edge_silence_so_pause_is_ours(tmp_path):
    """Регрессия: тишина кусков + наша пауза давали 1.5–2.2 с на границах абзацев (QA long_pause)."""
    from voru.normalize.chunking import PARAGRAPH_PAUSE_S
    from voru.providers.f5_ru import EDGE_KEEP_S
    from voru.qa.audio import check_audio

    req = SynthesisRequest(text="Готово.\n\nТеперь иди.", locale="ruRU", player_gender=None,
                           voice=VoiceRef("v", "1", tmp_path / "ref.wav", "Пусть луна осветит твой путь."),
                           delivery_profile="neutral", generation_config={"seed": 1}, output_path=tmp_path / "out.wav")
    with wave.open(str(tmp_path / "ref.wav"), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(24000)
        w.writeframes(b"\x00\x00" * 24000 * 5)

    result = loaded(F5RuV4Provider(), PaddedF5()).synthesize(req)

    expected_ms = 2 * 200 + (PARAGRAPH_PAUSE_S + 4 * EDGE_KEEP_S) * 1000
    assert abs(result.duration_ms - expected_ms) <= 2
    assert [f.reason for f in check_audio(result.path, req.text)] == []


def test_f5_rejects_reference_longer_than_it_reads(tmp_path):
    """Регрессия (приёмка 12.10.2026): референс сатира 13.2 с — F5 обрезал звук до 12 с, а хвост
    транскрипта («о чём другие только шепчутся») вставлял в каждую реплику."""
    ref = tmp_path / "long.wav"
    with wave.open(str(ref), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(24000)
        w.writeframes(b"\x00\x00" * int(24000 * 12.5))
    req = SynthesisRequest(text="Привет.", locale="ruRU", player_gender=None,
                           voice=VoiceRef("v", "1", ref, "Длинный транскрипт."), delivery_profile="neutral",
                           generation_config={"seed": 1}, output_path=tmp_path / "out.wav")

    with pytest.raises(UnsupportedOption) as err:
        F5RuV4Provider().validate(req)

    assert err.value.reason == "reference_too_long"


def test_repo_references_fit_f5_limit():
    from voru.casting import load_casting
    from voru.providers.f5_ru import F5_MAX_REFERENCE_S

    casting = load_casting()
    too_long = {}
    for voice_id, profile in casting.voices.items():
        if profile.reference_audio:
            with wave.open(str(casting.path.parent / profile.reference_audio)) as w:
                seconds = w.getnframes() / w.getframerate()
            if seconds > F5_MAX_REFERENCE_S:
                too_long[voice_id] = round(seconds, 2)

    assert too_long == {}


def test_f5_loads_pinned_checkpoint_vocab_and_vocoder(monkeypatch):
    import sys
    import types

    from voru.providers.f5_ru import F5_VOCAB, VOCOS_REPO, VOCOS_REVISION

    calls = {"files": []}
    hub = types.SimpleNamespace(
        hf_hub_download=lambda repo, filename, revision: calls["files"].append((repo, filename, revision))
        or f"/cache/{filename}",
        snapshot_download=lambda repo, revision: calls.setdefault("vocoder", (repo, revision)) and "/cache/vocos",
    )

    class FakeF5TTS:
        def __init__(self, **kwargs):
            calls["init"] = kwargs

    audio_segment = types.SimpleNamespace(converter=None)
    monkeypatch.setitem(sys.modules, "huggingface_hub", hub)
    monkeypatch.setitem(sys.modules, "f5_tts", types.SimpleNamespace())
    monkeypatch.setitem(sys.modules, "f5_tts.api", types.SimpleNamespace(F5TTS=FakeF5TTS))
    monkeypatch.setitem(sys.modules, "pydub", types.SimpleNamespace(AudioSegment=audio_segment))
    monkeypatch.setitem(sys.modules, "imageio_ffmpeg", types.SimpleNamespace(get_ffmpeg_exe=lambda: "/bin/ffmpeg"))

    provider = F5RuV4Provider()
    provider._load()

    assert calls["files"] == [(F5_REPO, provider.checkpoint, F5_REVISION), (F5_REPO, F5_VOCAB, F5_REVISION)]
    assert calls["vocoder"] == (VOCOS_REPO, VOCOS_REVISION)
    assert calls["init"]["ckpt_file"] == f"/cache/{provider.checkpoint}"
    assert calls["init"]["vocab_file"] == f"/cache/{F5_VOCAB}"
    assert calls["init"]["vocoder_local_path"] == "/cache/vocos"
    assert audio_segment.converter == "/bin/ffmpeg"


def test_f5_revision_includes_vocoder():
    from voru.providers.f5_ru import VOCOS_REVISION

    assert VOCOS_REVISION[:7] in F5RuV2Provider().model_revision()


@pytest.mark.parametrize("provider_class, checkpoint", [
    (F5RuV2Provider, "F5TTS_v1_Base_v2/model_last_inference.safetensors"),
    (F5RuV4Provider, "F5TTS_v1_Base_v4_winter/model_212000.safetensors"),
])
def test_f5_checkpoints_are_pinned(provider_class, checkpoint):
    assert provider_class().model_revision().startswith(f"{F5_REPO}@{F5_REVISION}:{checkpoint}")
    assert len(F5_REVISION) == 40


def test_f5_variants_have_different_fingerprints(tmp_path, reference):
    from voru.jobs.fingerprint import fingerprint

    req = request(tmp_path, reference)

    assert fingerprint(F5RuV2Provider().synthesis_input(req, 1)) != fingerprint(F5RuV4Provider().synthesis_input(req, 1))


# --- реестр: тяжёлые модули не импортируются до _load ---

@pytest.mark.parametrize("name, cls", [
    ("qwen3-tts-base", Qwen3BaseProvider), ("qwen3-tts-ru-stress", None), ("f5-tts-ru-v2", F5RuV2Provider), ("f5-tts-ru-v4", F5RuV4Provider),
])
def test_registry_names(name, cls):
    from voru.providers.qwen3 import Qwen3StressProvider

    provider = get_provider(name)

    assert isinstance(provider, cls or Qwen3StressProvider)
    assert provider.name == name

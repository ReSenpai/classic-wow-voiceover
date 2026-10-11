"""GPU smoke-тесты настоящих моделей. Только вручную, в окружении WSL нужной модели:

  ~/voru-envs/qwen/bin/python -m pytest -m gpu tests/providers/test_gpu_smoke.py -s
  ~/voru-envs/f5/bin/python   -m pytest -m gpu tests/providers/test_gpu_smoke.py -s

Пишут в лог модель, ревизию, окружение и RTF (дизайн §14–15).
"""
import importlib.util
import platform
import time
import wave

import pytest

from voru.providers.base import SynthesisRequest, VoiceRef, write_wav_atomically

pytestmark = pytest.mark.gpu

TEXT = "Пусть луна осветит твой путь, странник. Лес неспокоен в последние дни."
REF_TEXT = "Будь осторожен в лесу, не все его обитатели дружелюбны. Я буду ждать тебя здесь, у ручья."


def report(name, revision, elapsed, duration_s):
    import torch

    print(f"\n[{name}] {revision}\n  python {platform.python_version()}, torch {torch.__version__}, "
          f"cuda {torch.version.cuda}, {torch.cuda.get_device_name(0)}\n"
          f"  синтез {elapsed:.1f} с, звук {duration_s:.1f} с, RTF {elapsed / duration_s:.2f}, "
          f"пик VRAM {torch.cuda.max_memory_allocated() / 2**30:.1f} GiB")


def wav_seconds(path):
    with wave.open(str(path)) as w:
        return w.getnframes() / w.getframerate()


@pytest.fixture(scope="session")
def reference(tmp_path_factory):
    """Референс: из VoiceDesign, если есть qwen-tts, иначе — предсгенерированный файл из work/."""
    path = tmp_path_factory.mktemp("ref") / "ref.wav"
    if importlib.util.find_spec("qwen_tts"):
        from voru.providers.qwen3 import QwenVoiceDesigner

        designer = QwenVoiceDesigner()
        started = time.perf_counter()
        samples, sr = designer.design(REF_TEXT, "Adult female, warm and composed alto voice, calm pace.", seed=1)
        write_wav_atomically(path, samples, sr)
        report("qwen3-voicedesign", designer.model_revision, time.perf_counter() - started, wav_seconds(path))
        return path
    from voru.config import REPO_ROOT

    cached = REPO_ROOT / "work" / "gpu_smoke_ref.wav"
    if not cached.exists():
        pytest.skip("нет референса: сначала прогоните smoke в окружении qwen")
    return cached


@pytest.fixture(scope="session", autouse=True)
def keep_reference(reference):
    from voru.config import REPO_ROOT

    target = REPO_ROOT / "work" / "gpu_smoke_ref.wav"
    if reference != target:
        target.parent.mkdir(exist_ok=True)
        target.write_bytes(reference.read_bytes())


@pytest.mark.parametrize("name, module", [
    ("qwen3-tts-base", "qwen_tts"), ("f5-tts-ru-v2", "f5_tts"), ("f5-tts-ru-v4", "f5_tts"),
])
def test_provider_synthesizes_russian(name, module, reference, tmp_path):
    if importlib.util.find_spec(module) is None:
        pytest.skip(f"нет пакета {module} в окружении")
    from voru.providers import get_provider

    provider = get_provider(name)
    request = SynthesisRequest(text=TEXT, locale="ruRU", player_gender=None,
                               voice=VoiceRef("smoke", "1", reference, REF_TEXT), delivery_profile="neutral",
                               generation_config={"seed": 1}, output_path=tmp_path / f"{name}.wav")
    result = provider.synthesize(request)

    duration = result.duration_ms / 1000
    report(name, result.model_revision, result.elapsed_s, duration)
    assert 2.0 < duration < 20.0
    from voru.config import REPO_ROOT

    keep = REPO_ROOT / "work" / "gpu_smoke" / f"{name}.wav"
    keep.parent.mkdir(parents=True, exist_ok=True)
    keep.write_bytes(result.path.read_bytes())

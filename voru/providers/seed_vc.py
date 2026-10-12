"""Seed-VC: преобразование голоса — запись реплики человеком → тембр референса голоса.

Код Seed-VC — GPL-3.0 (репозиторий в архиве), ставится отдельным окружением WSL:
scripts/wsl/setup_env.sh seedvc. Мы его не распространяем, а вызываем подпроцессом.
Подача (интонация, смех, паузы) — от человека; модель меняет только тембр.

Вход — generation_config: source_audio (путь к записи) и source_sha256 (её хэш: перезапись
на стенде меняет fingerprint и пересобирает реплику). Текст в преобразовании не участвует,
но остаётся в запросе: по нему автопроверка оценивает темп.
Основной чекпоинт закреплён по ревизии HF; вспомогательные модели Seed-VC (whisper-small,
bigvgan, campplus) он качает сам без ревизии — известный пробел.
"""
import hashlib
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from voru.providers.base import Capabilities, Provider, UnsupportedOption

SEEDVC_REPO = "Plachtaa/seed-vc"
SEEDVC_COMMIT = "51383efd921027683c89e5348211d93ff12ac2a8"
SEEDVC_HF_REPO = "Plachta/Seed-VC"
SEEDVC_HF_REVISION = "257283f9f41585055e8f858fba4fd044e5caed6e"
SEEDVC_CHECKPOINT = "DiT_seed_v2_uvit_whisper_small_wavenet_bigvgan_pruned.pth"
SEEDVC_CONFIG = "config_dit_mel_seed_uvit_whisper_small_wavenet.yml"
DEFAULT_SRC = Path.home() / "voru-envs" / "seedvc-src"

# Запуск inference.py с фиксированным seed (у самого скрипта seed нет — диффузия случайна).
_LAUNCHER = """
import random, runpy, sys
import numpy, torch
seed = int(sys.argv[1]); script = sys.argv[2]
random.seed(seed); numpy.random.seed(seed % 2**32); torch.manual_seed(seed); torch.cuda.manual_seed_all(seed)
sys.argv = [script] + sys.argv[3:]
runpy.run_path(script, run_name="__main__")
"""


def file_sha256(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class SeedVcProvider(Provider):
    name = "seed-vc"
    adapter_version = "1"
    default_capabilities = Capabilities(
        languages=frozenset({"ru"}),
        voice_reference=True,
        requires_reference=True,
        voice_design=False,
        delivery_profiles=frozenset({"neutral"}),
        stress_marks=False,  # текст не озвучивается — ударения не нужны
        max_chars=5000,
        config_keys=frozenset({"source_audio", "source_sha256", "diffusion_steps", "inference_cfg_rate"}),
        reference_format="wav",
    )

    def __init__(self, src_dir=None):
        super().__init__()
        self.src_dir = Path(src_dir or os.environ.get("VORU_SEEDVC_SRC", DEFAULT_SRC))

    def model_revision(self) -> str:
        return (f"{SEEDVC_REPO}@{SEEDVC_COMMIT}+{SEEDVC_HF_REPO}@{SEEDVC_HF_REVISION}:{SEEDVC_CHECKPOINT}")

    def validate(self, request):
        super().validate(request)
        config = request.generation_config
        source = Path(config.get("source_audio") or "")
        if not config.get("source_audio") or not source.exists():
            raise UnsupportedOption("source_missing", str(source))
        if file_sha256(source) != config.get("source_sha256"):
            raise UnsupportedOption("source_changed", f"{source.name}: запись изменилась после планирования")

    def _load(self):
        from huggingface_hub import hf_hub_download

        self._model = {
            "checkpoint": hf_hub_download(SEEDVC_HF_REPO, SEEDVC_CHECKPOINT, revision=SEEDVC_HF_REVISION),
            "config": hf_hub_download(SEEDVC_HF_REPO, SEEDVC_CONFIG, revision=SEEDVC_HF_REVISION),
        }

    def _run(self, args, seed, out_dir):
        script = str(self.src_dir / "inference.py")
        proc = subprocess.run([sys.executable, "-c", _LAUNCHER, str(seed), script, *args],
                              cwd=self.src_dir, capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(f"seed-vc: {proc.stderr[-800:]}")

    def _generate(self, model_text, request):
        config = request.generation_config
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            args = ["--source", config["source_audio"], "--target", str(request.voice.reference_audio),
                    "--output", str(out_dir),
                    "--diffusion-steps", str(config.get("diffusion_steps", 30)), "--length-adjust", "1.0",
                    "--inference-cfg-rate", str(config.get("inference_cfg_rate", 0.7)),
                    "--f0-condition", "False", "--auto-f0-adjust", "False", "--semi-tone-shift", "0",
                    "--checkpoint", self._model["checkpoint"], "--config", self._model["config"],
                    "--fp16", "True"]
            self._run(args, config["seed"], out_dir)
            (result,) = list(out_dir.glob("*.wav"))
            return read_wav_mono(result)


def read_wav_mono(path):
    """WAV PCM16 или float32 (Seed-VC пишет float) → (сэмплы −1…1, частота). Только stdlib."""
    import array
    import struct

    data = Path(path).read_bytes()
    if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise ValueError(f"{path}: не WAV")
    pos, fmt, payload = 12, None, None
    while pos + 8 <= len(data):
        chunk, size = data[pos:pos + 4], struct.unpack("<I", data[pos + 4:pos + 8])[0]
        body = data[pos + 8:pos + 8 + size]
        if chunk == b"fmt ":
            fmt = struct.unpack("<HHIIHH", body[:16])
        elif chunk == b"data":
            payload = body
        pos += 8 + size + (size % 2)
    if fmt is None or payload is None:
        raise ValueError(f"{path}: нет fmt/data")
    tag, channels, rate, _, _, bits = fmt
    if tag == 3 and bits == 32:
        values = array.array("f", payload)
    elif tag == 1 and bits == 16:
        values = [v / 32768 for v in array.array("h", payload)]
    else:
        raise ValueError(f"{path}: формат {tag}/{bits} бит не поддержан")
    return [float(v) for v in values[::channels]], rate

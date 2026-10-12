"""Qwen3-TTS 1.7B Base: синтез по референсу + точному транскрипту (Apache-2.0).

Ставится в отдельное окружение WSL: scripts/wsl/setup_env.sh qwen. Ударения «+» модель
не понимает — снимаются до синтеза (и до fingerprint). Веса закреплены по ревизии HF.

Qwen3StressProvider — та же Base, дообученная на русские ударения (LoRA, слитый чекпоинт,
Apache-2.0): ставит ударение по знаку U+0301 после гласной, в т.ч. против словаря.
"""
import dataclasses
import re

from voru.providers.base import Capabilities, Provider

QWEN_BASE_REPO = "Qwen/Qwen3-TTS-12Hz-1.7B-Base"
QWEN_BASE_REVISION = "fd4b254389122332181a7c3db7f27e918eec64e3"
QWEN_DESIGN_REPO = "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign"
QWEN_DESIGN_REVISION = "5ecdb67327fd37bb2e042aab12ff7391903235d3"
QWEN_STRESS_REPO = "siriusfreak/qwen3-tts-12hz-1.7b-ru-stress-cf"
QWEN_STRESS_REVISION = "c16b3af3db3095120efc1ebb73f6522442bcb3b1"
LANGUAGES = {"ru": "Russian"}
ACUTE = "́"
_STRESS = re.compile(r"\+(.?)")
_VOWELS = set("аеёиоуыэюяАЕЁИОУЫЭЮЯ")


def to_combining_acute(text: str) -> str:
    """«+» перед ударной гласной (наш формат, RUAccent) → U+0301 после неё (формат дообученной Qwen)."""
    def repl(match):
        vowel = match.group(1)
        if vowel not in _VOWELS:
            raise ValueError(f"знак ударения не перед гласной: {text[max(0, match.start() - 10):match.end() + 10]!r}")
        return vowel + ACUTE
    return _STRESS.sub(repl, text)


def load_pinned(repo: str, revision: str):
    """qwen-tts передаёт revision только в AutoModel, а процессор и generate_config грузит
    с последней версии — поэтому качаем снимок репозитория целиком и грузим из папки."""
    import torch
    from huggingface_hub import snapshot_download
    from qwen_tts import Qwen3TTSModel

    path = snapshot_download(repo, revision=revision)
    return Qwen3TTSModel.from_pretrained(path, device_map="cuda:0", dtype=torch.bfloat16)


def seed_everything(seed: int):
    import random

    import numpy as np
    import torch

    random.seed(seed)
    np.random.seed(seed % 2**32)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


class Qwen3BaseProvider(Provider):
    name = "qwen3-tts-base"
    adapter_version = "1"
    default_capabilities = Capabilities(
        languages=frozenset(LANGUAGES),
        voice_reference=True,
        requires_reference=True,
        voice_design=False,
        delivery_profiles=frozenset({"neutral"}),
        stress_marks=False,
        max_chars=1500,
        config_keys=frozenset({"temperature", "top_p", "top_k", "repetition_penalty"}),
        reference_format="wav",
    )

    def model_revision(self) -> str:
        return f"{QWEN_BASE_REPO}@{QWEN_BASE_REVISION}"

    def _load(self):
        self._model = load_pinned(QWEN_BASE_REPO, QWEN_BASE_REVISION)

    def _apply_seed(self, seed: int):
        seed_everything(seed)

    def _generate(self, model_text, request):
        config = dict(request.generation_config)
        self._apply_seed(config.pop("seed"))
        wavs, sample_rate = self._model.generate_voice_clone(
            text=model_text,
            language=LANGUAGES[request.locale[:2]],
            ref_audio=str(request.voice.reference_audio),
            ref_text=request.voice.reference_text,
            **config,
        )
        return wavs[0], sample_rate


class Qwen3StressProvider(Qwen3BaseProvider):
    name = "qwen3-tts-ru-stress"
    default_capabilities = dataclasses.replace(Qwen3BaseProvider.default_capabilities, stress_marks=True)

    def model_revision(self) -> str:
        return f"{QWEN_STRESS_REPO}@{QWEN_STRESS_REVISION}"

    def model_text(self, request) -> str:
        return to_combining_acute(super().model_text(request))

    def _load(self):
        self._model = load_pinned(QWEN_STRESS_REPO, QWEN_STRESS_REVISION)


class QwenVoiceDesigner:
    """Qwen3-TTS VoiceDesign: голос по текстовому описанию — для создания референсов, не для корпуса."""
    model_revision = f"{QWEN_DESIGN_REPO}@{QWEN_DESIGN_REVISION}"

    def __init__(self):
        self._model = None

    def design_batch(self, texts: list, instructs: list, seed: int) -> list:
        """Несколько вариантов за один проход модели; случайность общая на батч."""
        if self._model is None:
            self._model = load_pinned(QWEN_DESIGN_REPO, QWEN_DESIGN_REVISION)
        seed_everything(seed)
        wavs, sample_rate = self._model.generate_voice_design(
            text=list(texts), language=["Russian"] * len(texts), instruct=list(instructs))
        return [(wav, sample_rate) for wav in wavs]

    def design(self, text: str, instruct: str, seed: int):
        return self.design_batch([text], [instruct], seed)[0]

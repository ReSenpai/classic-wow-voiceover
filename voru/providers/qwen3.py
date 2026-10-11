"""Qwen3-TTS 1.7B Base: синтез по референсу + точному транскрипту (Apache-2.0).

Ставится в отдельное окружение WSL: scripts/wsl/setup_env.sh qwen. Ударения «+» модель
не понимает — снимаются до синтеза (и до fingerprint). Веса закреплены по ревизии HF.
"""
from voru.providers.base import Capabilities, Provider

QWEN_BASE_REPO = "Qwen/Qwen3-TTS-12Hz-1.7B-Base"
QWEN_BASE_REVISION = "fd4b254389122332181a7c3db7f27e918eec64e3"
QWEN_DESIGN_REPO = "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign"
QWEN_DESIGN_REVISION = "5ecdb67327fd37bb2e042aab12ff7391903235d3"
LANGUAGES = {"ru": "Russian"}


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
        import torch
        from qwen_tts import Qwen3TTSModel

        self._model = Qwen3TTSModel.from_pretrained(
            QWEN_BASE_REPO, revision=QWEN_BASE_REVISION, device_map="cuda:0", dtype=torch.bfloat16,
        )

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


class QwenVoiceDesigner:
    """Qwen3-TTS VoiceDesign: голос по текстовому описанию — для создания референсов, не для корпуса."""
    model_revision = f"{QWEN_DESIGN_REPO}@{QWEN_DESIGN_REVISION}"

    def __init__(self):
        self._model = None

    def design(self, text: str, instruct: str, seed: int):
        if self._model is None:
            import torch
            from qwen_tts import Qwen3TTSModel

            self._model = Qwen3TTSModel.from_pretrained(
                QWEN_DESIGN_REPO, revision=QWEN_DESIGN_REVISION, device_map="cuda:0", dtype=torch.bfloat16,
            )
        seed_everything(seed)
        wavs, sample_rate = self._model.generate_voice_design(text=text, language="Russian", instruct=instruct)
        return wavs[0], sample_rate

"""F5-TTS Russian (Misha24-10): синтез по референсу, ударения «+» перед гласной.

Веса CC BY-NC 4.0 (код F5-TTS — MIT): некоммерческое использование.
Ставится в отдельное окружение WSL: scripts/wsl/setup_env.sh f5. Чекпоинт и словарь
закреплены по ревизии репозитория HF; v2 и v4_winter — разные провайдеры для сравнения.
"""
from voru.providers.base import Capabilities, Provider

F5_REPO = "Misha24-10/F5-TTS_RUSSIAN"
F5_REVISION = "ea166adeae4c80ec5ee423a671e2bdb83906cf84"
F5_VOCAB = "F5TTS_v1_Base/vocab.txt"
F5_ARCHITECTURE = "F5TTS_v1_Base"


class _F5RuProvider(Provider):
    adapter_version = "1"
    checkpoint: str
    default_capabilities = Capabilities(
        languages=frozenset({"ru"}),
        voice_reference=True,
        requires_reference=True,
        voice_design=False,
        delivery_profiles=frozenset({"neutral"}),
        stress_marks=True,
        max_chars=1500,  # длинный текст F5 сам режет на части по длине референса
        config_keys=frozenset({"nfe_step", "cfg_strength", "sway_sampling_coef", "speed", "cross_fade_duration"}),
        reference_format="wav",
    )

    def model_revision(self) -> str:
        return f"{F5_REPO}@{F5_REVISION}:{self.checkpoint}"

    def _load(self):
        from f5_tts.api import F5TTS
        from huggingface_hub import hf_hub_download

        ckpt = hf_hub_download(F5_REPO, self.checkpoint, revision=F5_REVISION)
        vocab = hf_hub_download(F5_REPO, F5_VOCAB, revision=F5_REVISION)
        self._model = F5TTS(model=F5_ARCHITECTURE, ckpt_file=ckpt, vocab_file=vocab, device="cuda")

    def _generate(self, model_text, request):
        config = dict(request.generation_config)
        wav, sample_rate, _ = self._model.infer(
            ref_file=str(request.voice.reference_audio),
            ref_text=request.voice.reference_text,
            gen_text=model_text,
            seed=config.pop("seed"),
            show_info=lambda *args, **kwargs: None,
            **config,
        )
        return wav, sample_rate


class F5RuV2Provider(_F5RuProvider):
    name = "f5-tts-ru-v2"
    checkpoint = "F5TTS_v1_Base_v2/model_last_inference.safetensors"


class F5RuV4Provider(_F5RuProvider):
    name = "f5-tts-ru-v4"
    checkpoint = "F5TTS_v1_Base_v4_winter/model_212000.safetensors"

"""F5-TTS Russian (Misha24-10): синтез по референсу, ударения «+» перед гласной.

Веса CC BY-NC 4.0 (код F5-TTS — MIT): некоммерческое использование.
Ставится в отдельное окружение WSL: scripts/wsl/setup_env.sh f5. Чекпоинт и словарь
закреплены по ревизии репозитория HF; v2 и v4_winter — разные провайдеры для сравнения.
"""
import wave

from voru.normalize.chunking import chunk_text
from voru.providers.base import Capabilities, Provider, UnsupportedOption

F5_REPO = "Misha24-10/F5-TTS_RUSSIAN"
F5_REVISION = "ea166adeae4c80ec5ee423a671e2bdb83906cf84"
F5_VOCAB = "F5TTS_v1_Base/vocab.txt"
F5_ARCHITECTURE = "F5TTS_v1_Base"
# Вокодер F5 по умолчанию качается без ревизии — закрепляем и передаём локальной папкой.
VOCOS_REPO = "charactr/vocos-mel-24khz"
VOCOS_REVISION = "0feb3fdd929bcd6649e0e7c5a688cf7dd012ef21"


EDGE_KEEP_S = 0.05  # оставляем у краёв куска: не срезать согласные и дыхание
EDGE_SILENCE_LEVEL = 0.01  # ≈ -40 dBFS
F5_MAX_SECONDS = 22  # F5 рассчитывает лимит куска как байты/с референса × (22 − длина референса)
# F5 обрезает референс до 12 с, а транскрипт оставляет целым — хвост текста без звука модель
# вставляет в каждую реплику. Поэтому длиннее не принимаем.
F5_MAX_REFERENCE_S = 12.0


def _reference_seconds(reference_audio) -> float:
    with wave.open(str(reference_audio)) as w:
        return w.getnframes() / w.getframerate()


def chunk_limit_bytes(reference_audio, reference_text: str) -> int:
    ref_seconds = min(_reference_seconds(reference_audio), F5_MAX_REFERENCE_S)
    return int(len(reference_text.encode("utf-8")) / ref_seconds * (F5_MAX_SECONDS - ref_seconds))


def trim_edges(samples, sample_rate: int) -> list:
    """Срезает тишину по краям куска F5, оставляя EDGE_KEEP_S: паузы между кусками ставим сами."""
    samples = [float(x) for x in samples]
    loud = [i for i, x in enumerate(samples) if abs(x) >= EDGE_SILENCE_LEVEL]
    if not loud:
        return samples
    keep = int(sample_rate * EDGE_KEEP_S)
    return samples[max(0, loud[0] - keep):loud[-1] + 1 + keep]


class _F5RuProvider(Provider):
    # 2: своя нарезка по предложениям (F5 резал по запятым посреди фразы)
    # 3: тишина по краям кусков срезается — иначе паузы на абзацах были 1.5–2.2 с
    adapter_version = "3"
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
        return f"{F5_REPO}@{F5_REVISION}:{self.checkpoint}+{VOCOS_REPO}@{VOCOS_REVISION[:12]}"

    def validate(self, request):
        super().validate(request)
        seconds = _reference_seconds(request.voice.reference_audio)
        if seconds > F5_MAX_REFERENCE_S:
            raise UnsupportedOption("reference_too_long",
                                    f"{request.voice.voice_id}: {seconds:.1f} с > {F5_MAX_REFERENCE_S:.0f} с")

    def _load(self):
        import imageio_ffmpeg
        from f5_tts.api import F5TTS
        from huggingface_hub import hf_hub_download, snapshot_download
        from pydub import AudioSegment

        AudioSegment.converter = imageio_ffmpeg.get_ffmpeg_exe()  # pydub читает референс через ffmpeg
        ckpt = hf_hub_download(F5_REPO, self.checkpoint, revision=F5_REVISION)
        vocab = hf_hub_download(F5_REPO, F5_VOCAB, revision=F5_REVISION)
        vocoder = snapshot_download(VOCOS_REPO, revision=VOCOS_REVISION)
        self._model = F5TTS(model=F5_ARCHITECTURE, ckpt_file=ckpt, vocab_file=vocab,
                            vocoder_local_path=vocoder, device="cuda")

    def _generate(self, model_text, request):
        config = dict(request.generation_config)
        seed = config.pop("seed")
        limit = chunk_limit_bytes(request.voice.reference_audio, request.voice.reference_text)
        samples, sample_rate = [], None
        for chunk in chunk_text(model_text, limit):
            wav, sample_rate, _ = self._model.infer(
                ref_file=str(request.voice.reference_audio),
                ref_text=request.voice.reference_text,
                gen_text=chunk.text,
                seed=seed,
                show_info=lambda *args, **kwargs: None,
                **config,
            )
            samples.extend(trim_edges(wav, sample_rate))
            samples.extend([0.0] * int(sample_rate * chunk.pause_after_s))
        return samples, sample_rate


class F5RuV2Provider(_F5RuProvider):
    name = "f5-tts-ru-v2"
    checkpoint = "F5TTS_v1_Base_v2/model_last_inference.safetensors"


class F5RuV4Provider(_F5RuProvider):
    name = "f5-tts-ru-v4"
    checkpoint = "F5TTS_v1_Base_v4_winter/model_212000.safetensors"

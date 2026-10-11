"""Контракт TTS-провайдера (дизайн §9).

Адаптер объявляет возможности (Capabilities); неподдерживаемая настройка — UnsupportedOption
до загрузки модели, а не тихое игнорирование. Модель грузится лениво и один раз на экземпляр
(один GPU-worker = один провайдер). Итоговый WAV появляется атомарно: временный файл →
проверка контейнера → os.replace. Неудачная попытка не портит уже существующий файл.
"""
import array
import hashlib
import os
import time
import unicodedata
import wave
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from voru.jobs.fingerprint import SynthesisInput, file_sha256
from voru.normalize.pronunciation import model_input


class UnsupportedOption(ValueError):
    def __init__(self, reason, detail=""):
        self.reason = reason
        self.detail = detail
        super().__init__(f"{reason}: {detail}" if detail else reason)


@dataclass(frozen=True)
class Capabilities:
    languages: frozenset
    voice_reference: bool
    requires_reference: bool
    voice_design: bool
    delivery_profiles: frozenset
    stress_marks: bool
    max_chars: int
    config_keys: frozenset  # допустимые ключи generation_config; seed обязателен всегда
    reference_format: Optional[str] = None


@dataclass(frozen=True)
class VoiceRef:
    voice_id: str
    voice_revision: str
    reference_audio: Optional[Path]
    reference_text: Optional[str]  # точный транскрипт референса


@dataclass(frozen=True)
class SynthesisRequest:
    text: str  # устный текст в канонической форме (с «+» и «ё»)
    locale: str
    player_gender: Optional[str]
    voice: VoiceRef
    delivery_profile: str
    generation_config: dict
    output_path: Path


@dataclass(frozen=True)
class SynthesisResult:
    path: Path
    sample_rate: int
    duration_ms: int
    provider: str
    model_revision: str
    generation_config: dict
    elapsed_s: float
    warnings: tuple = field(default=())


def language_of(locale: str) -> str:
    return locale[:2]


class Provider(ABC):
    name: str
    adapter_version: str
    default_capabilities: Capabilities

    def __init__(self, capabilities: Optional[Capabilities] = None):
        self.capabilities = capabilities or self.default_capabilities
        self._loaded = False

    @abstractmethod
    def model_revision(self) -> str:
        """Точная версия весов/checkpoint (repo@revision или хэш)."""

    @abstractmethod
    def _load(self):
        """Загрузить модель в память."""

    @abstractmethod
    def _generate(self, model_text: str, request: SynthesisRequest):
        """Вернуть (сэмплы float -1..1 моно, частота дискретизации)."""

    def model_text(self, request: SynthesisRequest) -> str:
        return model_input(request.text, stress_marks=self.capabilities.stress_marks)

    def validate(self, request: SynthesisRequest):
        caps = self.capabilities
        text = self.model_text(request)
        if not text.strip():
            raise UnsupportedOption("empty_text")
        if len(text) > caps.max_chars:
            raise UnsupportedOption("text_too_long", f"{len(text)} > {caps.max_chars}")
        if language_of(request.locale) not in caps.languages:
            raise UnsupportedOption("unsupported_language", request.locale)
        if request.delivery_profile not in caps.delivery_profiles:
            raise UnsupportedOption("unsupported_delivery", request.delivery_profile)
        if "seed" not in request.generation_config:
            raise UnsupportedOption("seed_required")
        unknown = set(request.generation_config) - caps.config_keys - {"seed"}
        if unknown:
            raise UnsupportedOption("unsupported_config", ", ".join(sorted(unknown)))
        has_reference = request.voice.reference_audio is not None
        if has_reference and not caps.voice_reference:
            raise UnsupportedOption("unsupported_voice_reference", request.voice.voice_id)
        if caps.requires_reference and not has_reference:
            raise UnsupportedOption("reference_required", request.voice.voice_id)
        if has_reference and not request.voice.reference_text:
            raise UnsupportedOption("reference_text_required", request.voice.voice_id)

    def synthesis_input(self, request: SynthesisRequest, normalization_revision: int) -> SynthesisInput:
        voice = request.voice
        return SynthesisInput(
            model_text=self.model_text(request),
            locale=request.locale,
            player_gender=request.player_gender,
            normalization_revision=normalization_revision,
            voice_id=voice.voice_id,
            voice_revision=voice.voice_revision,
            reference_audio_sha256=file_sha256(voice.reference_audio) if voice.reference_audio else None,
            reference_text_sha256=_text_sha256(voice.reference_text) if voice.reference_text else None,
            delivery_profile=request.delivery_profile,
            provider=self.name,
            model_revision=self.model_revision(),
            adapter_version=self.adapter_version,
            generation_config=dict(request.generation_config),
        )

    def synthesize(self, request: SynthesisRequest) -> SynthesisResult:
        self.validate(request)
        if not self._loaded:
            self._load()
            self._loaded = True
        started = time.perf_counter()
        samples, sample_rate = self._generate(self.model_text(request), request)
        frames = write_wav_atomically(request.output_path, samples, sample_rate)
        return SynthesisResult(
            path=request.output_path,
            sample_rate=sample_rate,
            duration_ms=frames * 1000 // sample_rate,
            provider=self.name,
            model_revision=self.model_revision(),
            generation_config=dict(request.generation_config),
            elapsed_s=time.perf_counter() - started,
        )


def _text_sha256(text: str) -> str:
    return hashlib.sha256(unicodedata.normalize("NFC", text).encode("utf-8")).hexdigest()


def write_wav_atomically(path: Path, samples, sample_rate: int) -> int:
    pcm = array.array("h", (int(max(-1.0, min(1.0, s)) * 32767) for s in samples))
    if not pcm:
        raise ValueError(f"{path}: provider returned no audio")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with wave.open(str(tmp), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(sample_rate)
            w.writeframes(pcm.tobytes())
        with wave.open(str(tmp), "rb") as w:  # проверка контейнера до публикации
            frames = w.getnframes()
            if frames != len(pcm):
                raise ValueError(f"{path}: wrote {frames} frames, expected {len(pcm)}")
        os.replace(tmp, path)
        return frames
    finally:
        if tmp.exists():
            tmp.unlink()

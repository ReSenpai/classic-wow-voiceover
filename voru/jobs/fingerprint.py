"""Fingerprint синтеза: SHA-256 канонического JSON всех входов, от которых зависит звук (дизайн §5).

В отпечаток идёт ровно тот текст, который получает модель (model_text): результат словаря и
нормализации уже в нём, поэтому новая запись словаря пересобирает только затронутые реплики.
Параметры кодирования (кодек, битрейт, громкость) сюда не входят — их смена требует
переэкспорта, а не синтеза.
"""
import hashlib
import json
import math
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

FINGERPRINT_SCHEMA = 1


@dataclass(frozen=True)
class SynthesisInput:
    model_text: str
    locale: str
    player_gender: Optional[str]
    normalization_revision: int
    voice_id: str
    voice_revision: str
    reference_audio_sha256: Optional[str]
    reference_text_sha256: Optional[str]
    delivery_profile: str
    provider: str
    model_revision: str
    adapter_version: str
    generation_config: dict  # параметры модели, включая seed


def _canonical(value):
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"non-finite number in synthesis input: {value}")
    if isinstance(value, dict):
        if not all(isinstance(k, str) for k in value):
            raise TypeError(f"config keys must be strings: {list(value)}")
        return {_canonical(k): _canonical(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canonical(v) for v in value]
    return value


def canonical_json(synthesis: SynthesisInput) -> str:
    payload = {"fingerprint_schema": FINGERPRINT_SCHEMA, **_canonical(asdict(synthesis))}
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def fingerprint(synthesis: SynthesisInput) -> str:
    return hashlib.sha256(canonical_json(synthesis).encode("utf-8")).hexdigest()


def file_sha256(path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()

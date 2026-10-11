"""Реестр голосов и кастинг NPC (дизайн §7).

Порядок выбора: явный профиль NPC → архетип (слово в имени + раса + пол) → базовый голос
расы/пола → рассказчик (объекты и предметы). Существо без подходящего правила не получает
голос по умолчанию: CastingError(no_voice), пока человек не назначит голос явно
(или в конфиге не выбрана политика unknown_creature: narrator).
Выбор детерминирован: только из YAML, без случайности.
"""
import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

from voru.config import REPO_ROOT
from voru.providers.base import VoiceRef

CASTING_PATH = REPO_ROOT / "config" / "voices.yaml"
SEXES = ("male", "female")
_DISPLAY_SEX = {0: "male", 1: "female"}  # DisplaySexID из CreatureDisplayInfoExtra
UNKNOWN_CREATURE_POLICIES = ("block", "narrator")


class CastingError(ValueError):
    def __init__(self, reason, detail=""):
        self.reason = reason
        self.detail = detail
        super().__init__(f"{reason}: {detail}" if detail else reason)


@dataclass(frozen=True)
class VoiceProfile:
    voice_id: str
    revision: str
    sex: str  # male / female / any
    description: str
    seed: int
    params: dict = field(default_factory=dict)  # {провайдер: {параметр: значение}}
    reference_audio: Optional[str] = None  # путь относительно папки voices.yaml
    reference_text: Optional[str] = None  # точный транскрипт референса
    provenance: Optional[str] = None
    license: Optional[str] = None
    test_lines: tuple = ()

    def params_for(self, provider: str) -> dict:
        return dict(self.params.get(provider, {}))

    def voice_ref(self, base_dir) -> VoiceRef:
        audio = Path(base_dir) / self.reference_audio if self.reference_audio else None
        return VoiceRef(self.voice_id, self.revision, audio, self.reference_text)


@dataclass(frozen=True)
class Archetype:
    match: str
    race: int
    sex: str
    voice: str


@dataclass(frozen=True)
class Casting:
    path: Path
    voices: dict
    npcs: dict  # "creature:2150" → voice_id
    archetypes: tuple
    race_sex: dict  # (race, sex) → voice_id
    narrator: str
    unknown_creature: str


@dataclass(frozen=True)
class CastingDecision:
    voice_id: str
    rule: str  # npc / archetype / race_sex / narrator / narrator_fallback


def _default_seed(voice_id: str) -> int:
    return int(hashlib.sha256(voice_id.encode("utf-8")).hexdigest()[:8], 16) % 2**31


def _profile(raw: dict) -> VoiceProfile:
    voice_id = raw["voice_id"]
    if raw.get("sex") not in (*SEXES, "any"):
        raise ValueError(f"voice {voice_id}: sex must be male/female/any")
    if raw.get("reference_audio"):
        for required in ("reference_text", "provenance", "license"):
            if not raw.get(required):
                raise ValueError(f"voice {voice_id}: reference_audio requires {required}")
    return VoiceProfile(
        voice_id=voice_id,
        revision=str(raw["revision"]),
        sex=raw["sex"],
        description=raw.get("description", ""),
        seed=int(raw.get("seed", _default_seed(voice_id))),
        params=raw.get("params") or {},
        reference_audio=raw.get("reference_audio"),
        reference_text=raw.get("reference_text"),
        provenance=raw.get("provenance"),
        license=raw.get("license"),
        test_lines=tuple(raw.get("test_lines") or ()),
    )


def load_casting(path=CASTING_PATH) -> Casting:
    path = Path(path)
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    voices = {}
    for raw in data["voices"]:
        profile = _profile(raw)
        if profile.voice_id in voices:
            raise ValueError(f"{path}: duplicate voice_id {profile.voice_id}")
        voices[profile.voice_id] = profile

    def voice(voice_id, where, sex=None):
        if voice_id not in voices:
            raise ValueError(f"{path}: {where} refers to unknown voice {voice_id}")
        if sex and voices[voice_id].sex not in (sex, "any"):
            raise ValueError(f"{path}: {where} expects sex {sex}, voice {voice_id} is {voices[voice_id].sex}")
        return voice_id

    section = data["casting"]
    npcs = {str(k): voice(v, f"npc {k}") for k, v in (section.get("npcs") or {}).items()}
    archetypes = []
    for raw in section.get("archetypes") or []:
        if raw["sex"] not in SEXES:
            raise ValueError(f"{path}: archetype {raw['match']}: sex must be male/female")
        archetypes.append(Archetype(raw["match"], int(raw["race"]), raw["sex"],
                                    voice(raw["voice"], f"archetype {raw['match']}", raw["sex"])))
    race_sex = {}
    for key, voice_id in (section.get("race_sex") or {}).items():
        race, _, sex = str(key).partition(":")
        if not race.isdigit() or sex not in SEXES:
            raise ValueError(f"{path}: race_sex key {key!r} must look like '4:male'")
        race_sex[(int(race), sex)] = voice(voice_id, f"race_sex {key}", sex)
    policy = section.get("unknown_creature", "block")
    if policy not in UNKNOWN_CREATURE_POLICIES:
        raise ValueError(f"{path}: unknown_creature must be one of {UNKNOWN_CREATURE_POLICIES}")
    return Casting(path, voices, npcs, tuple(archetypes), race_sex,
                   voice(section["narrator"], "narrator"), policy)


def cast(record, casting: Casting) -> CastingDecision:
    explicit = casting.npcs.get(f"{record.npc_type}:{record.npc_id}")
    if explicit:
        return CastingDecision(explicit, "npc")
    if record.npc_type != "creature":
        return CastingDecision(casting.narrator, "narrator")

    race, sex = record.npc_race_id, _DISPLAY_SEX.get(record.npc_sex_id)
    if race is not None and sex:
        for archetype in casting.archetypes:
            if archetype.race == race and archetype.sex == sex and archetype.match in (record.npc_name or ""):
                return CastingDecision(archetype.voice, "archetype")
        if (race, sex) in casting.race_sex:
            return CastingDecision(casting.race_sex[(race, sex)], "race_sex")
    if casting.unknown_creature == "narrator":
        return CastingDecision(casting.narrator, "narrator_fallback")
    raise CastingError("no_voice", f"creature:{record.npc_id} {record.npc_name} race={race} sex={sex}")

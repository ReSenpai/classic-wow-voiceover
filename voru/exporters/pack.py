"""Сборка data-модуля VoiceOver из принятых WAV-мастеров (дизайн §11).

Отдельный модуль со своим именем и приоритетом выше старого пака: для реплик пилота
звучит новый пак, для остальных — старый; откат — выключить аддон.
Имена файлов совместимы с плеером: "<quest>-<stage>" и "m-"/"f-" для вариантов пола игрока.
Если один quest-stage озвучивают разные NPC разными голосами — CollisionError, пока выбор
не задан явно (resolutions). Сборка идёт во временную папку и подменяет пак целиком.
"""
import hashlib
import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from voru.exporters.audio import encode_ogg
from voru.exporters.lua import lua_value

MODULE_FORMAT_VERSION = 1
MANIFEST_SCHEMA = 1
GUARD = "if not VoiceOver or not VoiceOver.DataModules then return end"
SOUNDS_DIR = "generated/sounds/quests"
_LOOKUP_TABLES = {"creature": "NPCIDLookupByQuestID", "gameobject": "ObjectIDLookupByQuestID", "item": "ItemIDLookupByQuestID"}
_NAME_TABLES = {"creature": "NPCNameLookupByNPCID", "gameobject": "ObjectNameLookupByObjectID", "item": "ItemNameLookupByItemID"}
_TOC_FILES = ["Module.lua", r"generated\sound_length_table.lua", r"generated\questlog_npc_lookups.lua",
              r"generated\npc_name_lookups.lua"]

MODULE_LUA = r'''if not VoiceOver or not VoiceOver.DataModules then return end

{module} = {{}}

function {module}:GetSoundPath(fileName, event)
    setfenv(1, VoiceOver)
    if Enums.SoundEvent:IsQuestEvent(event) then
        return format([[generated\sounds\quests\%s.ogg]], fileName)
    elseif Enums.SoundEvent:IsGossipEvent(event) then
        return format([[generated\sounds\gossip\%s.ogg]], fileName)
    end
end

VoiceOver.DataModules:Register("{module}", {module})
'''


class CollisionError(ValueError):
    pass


@dataclass(frozen=True)
class PackEntry:
    content_id: str
    text_key: str
    file_key: str
    quest_id: int
    stage: str
    npc_type: str
    npc_id: int
    npc_name: str
    voice_id: str
    fingerprint: str
    master_path: Path


@dataclass(frozen=True)
class PackInfo:
    module_name: str
    title: str
    version: str
    client: object  # ClientProfile
    priority: int = 200


def file_key(addon_key: str, player_gender) -> str:
    return f"{player_gender}-{addon_key}" if player_gender else addon_key


def _choose(entries, resolutions):
    by_key = {}
    for e in sorted(entries, key=lambda e: e.content_id):
        by_key.setdefault(e.file_key, []).append(e)
    chosen, collisions, problems = {}, {}, []
    for key, group in sorted(by_key.items()):
        if len({e.fingerprint for e in group}) == 1:
            chosen[key] = group[0]
            continue
        pick = resolutions.get(key)
        winner = next((e for e in group if e.content_id == pick), None)
        if winner is None:
            problems.append(f"{key}: " + ", ".join(f"{e.content_id} ({e.voice_id})" for e in group))
            continue
        chosen[key] = winner
        collisions[key] = {"chosen": winner.content_id, "dropped": [e.content_id for e in group if e is not winner]}
    if problems:
        raise CollisionError("один quest-stage озвучен разными NPC; выберите в resolutions:\n" + "\n".join(problems))
    return chosen, collisions


def _write(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def _lua_tables(module, tables: dict) -> str:
    body = "\n".join(f"{module}.{name} = {lua_value(value)}" for name, value in tables.items())
    return f"{GUARD}\n{body}\n"


def _toc(info: PackInfo) -> str:
    lines = [
        f"## Interface: {info.client.interface}",
        f"## Title: {info.title}",
        # VoiceOver загружает data-модули даже «выключенными» в списке аддонов
        # (FORCE_ENABLE_DISABLED_MODULES), поэтому честный способ отката — удалить папку.
        "## Notes: Русская озвучка квестов (пилот). Перекрывает старый пак; для отката удалите папку"
        " этого аддона и перезапустите клиент. VoiceOver загружает модуль, даже если он выключен.",
        f"## Version: {info.version}",
        "## LoadOnDemand: 1",
        "## RequiredDeps: AI_VoiceOver",
        "## X-Part-Of: VoiceOver",
        "## X-Child-Of: VoiceOver",
        f"## X-VoiceOver-DataModule-Version: {MODULE_FORMAT_VERSION}",
        f"## X-VoiceOver-DataModule-Priority: {info.priority}",
        "## X-VoiceOver-DataModule-Maps: 0, 1",
        f"## X-VoiceOver-Locale: {info.client.locale}",
        "",
        *_TOC_FILES,
    ]
    return "\n".join(lines) + "\n"


def _build(chosen, collisions, root: Path, info: PackInfo, credits: dict) -> dict:
    module = info.module_name
    lengths, files = {}, {}
    lookups = {name: {} for name in _LOOKUP_TABLES.values()}
    names = {name: {} for name in _NAME_TABLES.values()}
    for key, e in chosen.items():
        relative = f"{SOUNDS_DIR}/{key}.ogg"
        duration = round(encode_ogg(e.master_path, root / relative), 3)
        lengths[key] = duration
        files[relative] = {
            "sha256": hashlib.sha256((root / relative).read_bytes()).hexdigest(),
            "duration_s": duration,
            "content_id": e.content_id,
            "voice_id": e.voice_id,
            "fingerprint": e.fingerprint,
        }
        if e.stage == "accept":
            lookups[_LOOKUP_TABLES[e.npc_type]][e.quest_id] = e.npc_id
        if e.npc_name:
            names[_NAME_TABLES[e.npc_type]][e.npc_id] = e.npc_name

    _write(root / f"{module}.toc", _toc(info))
    _write(root / "Module.lua", MODULE_LUA.format(module=module))
    _write(root / "generated" / "sound_length_table.lua", _lua_tables(module, {"SoundLengthLookupByFileName": lengths}))
    _write(root / "generated" / "questlog_npc_lookups.lua", _lua_tables(module, lookups))
    _write(root / "generated" / "npc_name_lookups.lua", _lua_tables(module, names))

    stages = [e.stage for e in chosen.values()]
    manifest = {
        "schema_version": MANIFEST_SCHEMA,
        "module": module,
        "title": info.title,
        "version": info.version,
        "locale": info.client.locale,
        "flavor": info.client.flavor,
        "client_build": info.client.build,
        "interface": info.client.interface,
        "priority": info.priority,
        "module_format_version": MODULE_FORMAT_VERSION,
        "coverage": {
            "files": len(chosen),
            "quests": len({e.quest_id for e in chosen.values()}),
            **{stage: stages.count(stage) for stage in sorted(set(stages))},
        },
        "collisions": collisions,
        "voices": {v: credits[v] for v in sorted({e.voice_id for e in chosen.values()})},
        "files": files,
    }
    _write(root / "manifest.json", json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    return manifest


def build_pack(entries, out_dir, info: PackInfo, credits: dict, resolutions=None) -> dict:
    chosen, collisions = _choose(entries, resolutions or {})
    missing = sorted({e.voice_id for e in chosen.values()} - set(credits))
    if missing:
        raise ValueError(f"нет сведений о происхождении/лицензии голосов: {', '.join(missing)}")

    out_dir = Path(out_dir)
    final = out_dir / info.module_name
    staging = out_dir / f".{info.module_name}.build-{os.getpid()}"
    retired = out_dir / f".{info.module_name}.old-{os.getpid()}"
    shutil.rmtree(staging, ignore_errors=True)
    try:
        manifest = _build(chosen, collisions, staging, info, credits)
        if final.exists():
            os.replace(final, retired)
        os.replace(staging, final)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
        shutil.rmtree(retired, ignore_errors=True)
    return manifest

"""Reader пака CatQuest Voices 0.6.x (дизайн CQ §5–6).

Правила имён из потребителя CatQuest 0.6.4: запись квеста — взятие (есть только при поле `d`),
вложенная `t` — сдача со своими `d`/`g`/`v`; `g = 1` — варианты по полу ИГРОКА `_m`/`_f`
(CatQuest берёт `_f` при UnitSex == 3, иначе `_m`), иначе общий файл. Текст реплики — склейка
субтитров `c[x|m|f]`. Схема проверяется строго: неизвестное поле или тип — отказ целиком.

Источник правды — Index.lua (его играет CatQuest). index.json — тот же индекс без субтитров, но с моделью
`m` (eleven_v4 или пусто у старых записей); из него берём только модель и требуем полного совпадения
остальных полей. В 0.6.1 в index.json ещё 61 квест «только сдача», которых нет в Index.lua, — не переносим.
"""
import dataclasses
import hashlib
import json
import posixpath
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from voru.catquest.lua_table import LuaSchemaError, parse_assignments

MODULE_DIR = "CatQuest_Voices"
SOUNDS_DIR = "Sounds/q"
INDEX_FILE = "Index.lua"
JSON_FILE = "index.json"
SUPPORTED_VERSIONS = re.compile(r"0\.6\.\d+")
_ENTRY_KEYS = {"d", "v", "n", "m", "g", "c"}
_ROOT_KEYS = _ENTRY_KEYS | {"t"}


class UnsupportedSchema(ValueError):
    pass


@dataclass(frozen=True)
class SourceLine:
    quest_id: int
    stage: str  # accept | complete
    player_gender: Optional[str]  # None — общий файл, m/f — вариант по полу игрока
    source_path: str  # относительно папки модуля CatQuest_Voices
    voice: Optional[str]
    model: Optional[str]
    index_duration: float
    text: Optional[str]  # склейка субтитров; None — субтитров нет
    audio_sha256: Optional[str]  # None — файла нет в паке


@dataclass
class SourcePack:
    version: str
    source_sha256: Optional[str]  # хэш ZIP; для распакованной папки — None
    lines: list = field(default_factory=list)
    missing_audio: list = field(default_factory=list)
    unused_audio: list = field(default_factory=list)
    json_only_quests: list = field(default_factory=list)  # есть в index.json, но CatQuest их не играет


class PackFiles:
    """Единый доступ к папке и ZIP; пути — относительно папки модуля."""

    def __init__(self, source: Path):
        self.zip = None
        if source.is_file():
            self.zip = zipfile.ZipFile(source)
            names = {}
            for info in self.zip.infolist():
                if info.is_dir():
                    continue
                path = info.filename
                norm = posixpath.normpath(path)
                if path.startswith(("/", "\\")) or "\\" in path or norm.startswith("..") or ".." in path.split("/") \
                        or re.match(r"[A-Za-z]:", path):
                    raise UnsupportedSchema(f"путь вне архива: {path}")
                if not norm.startswith(MODULE_DIR + "/"):
                    raise UnsupportedSchema(f"файл вне папки {MODULE_DIR}: {path}")
                names[norm[len(MODULE_DIR) + 1:]] = info
            self.names = names
        else:
            self.root = source if (source / f"{MODULE_DIR}.toc").exists() else source / MODULE_DIR
            self.names = {p.relative_to(self.root).as_posix(): p for p in self.root.rglob("*") if p.is_file()}

    def read(self, rel: str) -> bytes:
        if rel not in self.names:
            raise UnsupportedSchema(f"нет файла {MODULE_DIR}/{rel}")
        return self.zip.read(self.names[rel]) if self.zip else self.names[rel].read_bytes()

    def sha256(self, rel: str) -> str:
        digest = hashlib.sha256()
        stream = self.zip.open(self.names[rel]) if self.zip else open(self.names[rel], "rb")
        with stream:
            for chunk in iter(lambda: stream.read(1 << 20), b""):
                digest.update(chunk)
        return digest.hexdigest()


def _toc_version(toc: str) -> str:
    m = re.search(r"^## Version:\s*(\S+)", toc, re.MULTILINE)
    if not m:
        raise UnsupportedSchema("в TOC нет ## Version")
    if not SUPPORTED_VERSIONS.fullmatch(m.group(1)):
        raise UnsupportedSchema(f"версия пака {m.group(1)} не поддерживается (reader 0.6.x)")
    return m.group(1)


def _number(entry, key, where):
    value = entry.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise UnsupportedSchema(f"{where}: поле {key} = {value!r}, ожидалось положительное число")
    return float(value)


def _variants(entry, where):
    g = entry.get("g")
    if g not in (None, 1):
        raise UnsupportedSchema(f"{where}: поле g = {g!r}, ожидалось 1 или нет")
    return ("m", "f") if g == 1 else ("x",)


def _text(entry, variant, keys, where) -> Optional[str]:
    cues = entry.get("c")
    if cues is None:
        return None
    if not isinstance(cues, dict) or set(cues) != set(keys):
        raise UnsupportedSchema(f"{where}: поле c {sorted(cues) if isinstance(cues, dict) else cues!r} "
                                f"не совпадает с вариантами {list(keys)}")
    parts = []
    for cue in cues[variant]:
        if not (isinstance(cue, list) and len(cue) == 2 and isinstance(cue[1], str)):
            raise UnsupportedSchema(f"{where}: поле c — субтитр {cue!r}")
        parts.append(cue[1].strip())
    return " ".join(parts)


def _entry_lines(quest_id, stage, entry, files, where):
    unknown = set(entry) - _ENTRY_KEYS
    if unknown:
        raise UnsupportedSchema(f"{where}: неизвестные поля {sorted(unknown)}")
    duration = _number(entry, "d", where)
    keys = _variants(entry, where)
    for key in ("v", "m"):
        if entry.get(key) is not None and not isinstance(entry[key], str):
            raise UnsupportedSchema(f"{where}: поле {key} = {entry[key]!r}")
    base = f"{quest_id}{'_t' if stage == 'complete' else ''}"
    for variant in keys:
        path = f"{SOUNDS_DIR}/{base}{'' if variant == 'x' else '_' + variant}.ogg"
        yield SourceLine(quest_id, stage, None if variant == "x" else variant, path, entry.get("v"), entry.get("m"),
                         duration, _text(entry, variant, keys, where),
                         files.sha256(path) if path in files.names else None)


def read_pack(source) -> SourcePack:
    source = Path(source)
    files = PackFiles(source)
    version = _toc_version(files.read(f"{MODULE_DIR}.toc").decode("utf-8"))
    try:
        env = parse_assignments(files.read(INDEX_FILE).decode("utf-8"), INDEX_FILE)
    except LuaSchemaError as e:
        raise UnsupportedSchema(str(e)) from e
    root = env.get("CatQuestVoicePack")
    if set(env) != {"CatQuestVoicePack"} or not isinstance(root, dict) or set(root) != {"quests"}:
        raise UnsupportedSchema(f"{INDEX_FILE}: ожидалась только таблица CatQuestVoicePack.quests, "
                                f"есть {sorted(env)} / {sorted(root) if isinstance(root, dict) else root!r}")

    try:
        index_json = json.loads(files.read(JSON_FILE).decode("utf-8"))
    except json.JSONDecodeError as e:
        raise UnsupportedSchema(f"{JSON_FILE}: {e}") from e

    pack = SourcePack(version, _sha256_file(source) if source.is_file() else None)
    for quest_id, entry in sorted(root["quests"].items(), key=lambda kv: str(kv[0])):
        where = f"{INDEX_FILE}: квест {quest_id!r}"
        if isinstance(quest_id, bool) or not isinstance(quest_id, int) or quest_id <= 0:
            raise UnsupportedSchema(f"{where}: quest id должен быть положительным целым")
        if not isinstance(entry, dict) or set(entry) - _ROOT_KEYS:
            raise UnsupportedSchema(f"{where}: неизвестные поля {sorted(set(entry) - _ROOT_KEYS)}")
        lines = []
        accept = {k: v for k, v in entry.items() if k != "t"}
        if accept:
            if "d" not in accept:
                raise UnsupportedSchema(f"{where}: поля взятия {sorted(accept)} без длительности d")
            lines.extend(_entry_lines(quest_id, "accept", accept, files, where))
        if "t" in entry:
            if not isinstance(entry["t"], dict):
                raise UnsupportedSchema(f"{where}: поле t = {entry['t']!r}")
            lines.extend(_entry_lines(quest_id, "complete", entry["t"], files, f"{where} (сдача)"))
        if not lines:
            raise UnsupportedSchema(f"{where}: пустая запись")
        models = _models(entry, index_json.get(str(quest_id)), quest_id)
        pack.lines.extend(dataclasses.replace(l, model=models[l.stage]) for l in lines)

    pack.json_only_quests = sorted(int(q) for q in set(index_json) - {str(q) for q in root["quests"]})
    pack.lines.sort(key=lambda l: (l.quest_id, l.stage, l.player_gender or ""))
    expected = {l.source_path for l in pack.lines}
    sounds = {n for n in files.names if n.startswith(SOUNDS_DIR + "/")}
    pack.missing_audio = sorted(expected - sounds)
    pack.unused_audio = sorted(sounds - expected)
    return pack


def _without(entry: dict, drop: set) -> dict:
    return {k: (_without(v, drop) if k == "t" and isinstance(v, dict) else v)
            for k, v in entry.items() if k not in drop}


def _models(entry: dict, json_entry, quest_id) -> dict:
    """Модель `m` по стадиям из index.json; остальные поля обязаны совпасть с Index.lua."""
    if not isinstance(json_entry, dict) or _without(entry, {"c", "m"}) != _without(json_entry, {"m"}):
        raise UnsupportedSchema(f"{JSON_FILE}: квест {quest_id} расходится с {INDEX_FILE}")
    return {"accept": json_entry.get("m"), "complete": (json_entry.get("t") or {}).get("m")}


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()

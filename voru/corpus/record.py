"""Запись корпуса: исходная реплика квеста с происхождением (дизайн §5).

Три разных ключа:
- content_id — постоянный внутренний id (квест + стадия + конкретный говорящий);
- text_key — ключ текста (квест + стадия), к нему привязаны правки в overrides.yaml;
- addon_key() — имя файла, которое ищет аддон ("947-accept").

Пустая русская локализация остаётся пустой (missing_locale) — английский хранится отдельно
в raw_text_en только для справки и в синтез не идёт.
"""
import json
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Optional

SCHEMA_VERSION = 1
STAGES = ("accept", "progress", "complete")
NPC_TYPES = ("creature", "gameobject", "item")
LOCALE_COLUMN_SUFFIX = {"ruRU": "_loc8"}
_TEXT_COLUMNS = {"accept": "Details", "progress": "RequestItemsText", "complete": "OfferRewardText"}


@dataclass(frozen=True)
class SourceRecord:
    schema_version: int
    content_id: str
    text_key: str
    client_flavor: str
    client_build: int
    locale: str
    quest_id: int
    quest_title: Optional[str]
    zone_id: Optional[int]
    stage: str
    npc_type: str
    npc_id: int
    npc_name: Optional[str]
    npc_race_id: Optional[int]
    npc_sex_id: Optional[int]
    speaker_type: str  # npc / narrator
    raw_text: Optional[str]
    raw_text_en: Optional[str]
    source_ref: str
    source_revision: str
    locale_status: str  # ok / missing_locale

    def __post_init__(self):
        if self.stage not in STAGES:
            raise ValueError(f"{self.content_id}: unknown stage {self.stage!r}")
        if self.npc_type not in NPC_TYPES:
            raise ValueError(f"{self.content_id}: unknown npc_type {self.npc_type!r}")
        expected_status = "ok" if self.raw_text else "missing_locale"
        if self.locale_status != expected_status:
            raise ValueError(f"{self.content_id}: locale_status {self.locale_status!r} != {expected_status!r}")


def _localized(value):
    return value if value and value.strip() else None


def record_from_row(row: dict, client, source_revision: str) -> SourceRecord:
    stage, npc_type = row["stage"], row["npc_type"]
    text_key = f"quest:{row['quest_id']}:{stage}"
    column = _TEXT_COLUMNS.get(stage, "?")
    suffix = LOCALE_COLUMN_SUFFIX[client.locale]
    raw_text = _localized(row["text_ru"])
    return SourceRecord(
        schema_version=SCHEMA_VERSION,
        content_id=f"{text_key}:{npc_type}:{row['npc_id']}",
        text_key=text_key,
        client_flavor=client.flavor,
        client_build=client.build,
        locale=client.locale,
        quest_id=row["quest_id"],
        quest_title=_localized(row["quest_title_ru"]),
        zone_id=row["zone_id"],
        stage=stage,
        npc_type=npc_type,
        npc_id=row["npc_id"],
        npc_name=_localized(row["npc_name_ru"]),
        npc_race_id=row["npc_race_id"],
        npc_sex_id=row["npc_sex_id"],
        speaker_type="npc" if npc_type == "creature" else "narrator",
        raw_text=raw_text,
        raw_text_en=row["text_en"],
        source_ref=f"quest_template.{column} / locales_quest.{column}{suffix}",
        source_revision=source_revision,
        locale_status="ok" if raw_text else "missing_locale",
    )


def addon_key(record: SourceRecord) -> str:
    return f"{record.quest_id}-{record.stage}"


def write_jsonl(records, path):
    lines = [json.dumps(asdict(r), ensure_ascii=False) for r in sorted(records, key=lambda r: r.content_id)]
    Path(path).write_text("".join(line + "\n" for line in lines), encoding="utf-8")


def read_jsonl(path) -> list:
    known = {f.name for f in fields(SourceRecord)}
    records, seen = [], set()
    for number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        data = json.loads(line)
        if data.get("schema_version") != SCHEMA_VERSION:
            raise ValueError(f"{path}:{number}: schema_version {data.get('schema_version')} != {SCHEMA_VERSION}")
        unknown = set(data) - known
        if unknown:
            raise ValueError(f"{path}:{number}: unknown fields {sorted(unknown)}")
        record = SourceRecord(**data)
        if record.content_id in seen:
            raise ValueError(f"{path}:{number}: duplicate content_id {record.content_id}")
        seen.add(record.content_id)
        records.append(record)
    return records

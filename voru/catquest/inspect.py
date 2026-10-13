"""inspect: целостность и состав пака CatQuest Voices, сверка с lock-файлом (дизайн CQ §6, §13).

  python -m voru.catquest inspect --source work/catquest/input/CatQuest_Voices-0.6.1.zip --out work/catquest/inspect.json
"""
import argparse
import collections
import json
import sys
from pathlib import Path

import yaml

from voru.catquest.reader import UnsupportedSchema, read_pack
from voru.config import REPO_ROOT

LOCK_PATH = REPO_ROOT / "config" / "catquest.lock.yaml"


class LockMismatch(ValueError):
    pass


def load_lock(path=LOCK_PATH) -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def check_lock(pack, lock: dict):
    """Вход обязан совпасть с зафиксированным: версия и SHA-256 исходного ZIP."""
    expected = lock["source"]
    if pack.version != expected["version"]:
        raise LockMismatch(f"version: в паке {pack.version}, в lock {expected['version']}")
    if pack.source_sha256 is None:
        raise LockMismatch("распакованную папку нельзя сверить с lock — нужен исходный ZIP")
    if pack.source_sha256 != expected["sha256"]:
        raise LockMismatch(f"sha256: архив {pack.source_sha256}, в lock {expected['sha256']}")


def inspect_pack(pack) -> dict:
    by_stage = {stage: collections.Counter() for stage in ("accept", "complete")}
    for line in pack.lines:
        by_stage[line.stage][line.player_gender or "x"] += 1
    return {
        "version": pack.version,
        "source_sha256": pack.source_sha256,
        "quests": len({l.quest_id for l in pack.lines}),
        "lines": len(pack.lines),
        "by_stage": {stage: dict(sorted(c.items(), key=lambda kv: "xmf".index(kv[0])))
                     for stage, c in by_stage.items()},
        "quests_with_accept": len({l.quest_id for l in pack.lines if l.stage == "accept"}),
        "quests_with_complete": len({l.quest_id for l in pack.lines if l.stage == "complete"}),
        "voices": len({l.voice for l in pack.lines}),
        "models": dict(collections.Counter(l.model or "unknown" for l in pack.lines).most_common()),
        "without_text": sum(l.text is None for l in pack.lines),
        "missing_audio": pack.missing_audio,
        "unused_audio": pack.unused_audio,
        "json_only_quests": pack.json_only_quests,
        "index_hours": round(sum(l.index_duration for l in pack.lines) / 3600, 4),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m voru.catquest inspect", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", type=Path, required=True, help="ZIP пака или распакованная папка")
    parser.add_argument("--lock", type=Path, default=LOCK_PATH)
    parser.add_argument("--no-lock", action="store_true", help="не сверять с lock (только для разведки)")
    parser.add_argument("--out", type=Path, help="JSON-отчёт")
    args = parser.parse_args(argv)

    try:
        pack = read_pack(args.source)
        if not args.no_lock:
            check_lock(pack, load_lock(args.lock))
    except (UnsupportedSchema, LockMismatch) as e:
        print(f"ошибка: {e}", file=sys.stderr)
        sys.exit(2)
    report = inspect_pack(pack)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"пак {report['version']}: квестов {report['quests']}, реплик: {report['lines']} "
          f"(взятие {report['by_stage']['accept']}, сдача {report['by_stage']['complete']}), "
          f"голосов {report['voices']}, ~{report['index_hours']:.1f} ч по индексу")
    print(f"модели: {report['models']}; без текста: {report['without_text']}")
    print(f"нет файла: {len(report['missing_audio'])}, файл без записи: {len(report['unused_audio'])}, "
          f"только в index.json: {len(report['json_only_quests'])}")

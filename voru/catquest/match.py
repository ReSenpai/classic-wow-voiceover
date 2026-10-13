"""Сопоставление реплик CatQuest с целевым корпусом (дизайн CQ §7).

Ключ: квест + стадия + пол игрока. Совпадение ID — начало проверки: текст CatQuest (склейка субтитров)
сравнивается с текстом корпуса после безопасной нормализации — регистр, «ё», пунктуация, кавычки, тире,
переносы. Место обращения `$N/$C/$R` в корпусе может быть пустым или занято 1–3 словами («юный герой»,
«друид») — это exact с пометкой address. Числа, имена, слова не нормализуются: «3»/«три», «Дарнас»/«Дарнасс» —
needs_review с diff, решение человека — в mapping-overrides.yaml (привязано к хэшам текстов и звука).
"""
import dataclasses
import difflib
import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

from voru.config import REPO_ROOT
from voru.normalize.markup import (
    Break,
    MarkupError,
    PlayerClass,
    PlayerName,
    PlayerRace,
    StageDirection,
    Text,
    WorldState,
    expand_player_gender,
    parse,
)
from voru.normalize.prepare import source_hash

OVERRIDES_PATH = REPO_ROOT / "corpus" / "catquest" / "mapping-overrides.yaml"
STATUSES = ("exact", "approved_variant", "needs_review", "target_missing", "content_mismatch", "audio_missing",
            "collision")
INCLUDED = ("exact", "approved_variant")
MISMATCH_RATIO = 0.5  # ниже — другой текст (другая стадия/квест), а не правка
ADDRESS_WORDS = 3  # сколько слов CatQuest может поставить на место ника
_SLOT = None  # место обращения в словах корпуса
_RANK = {"exact": 0, "needs_review": 1, "content_mismatch": 2}


@dataclass(frozen=True)
class Decision:
    quest_id: int
    stage: str
    player_gender: Optional[str]
    status: str
    reason: str = ""
    source_path: str = ""
    voice: Optional[str] = None
    source_audio_sha256: Optional[str] = None
    source_text_sha256: Optional[str] = None
    target_text_sha256: Optional[str] = None
    target_npc_type: Optional[str] = None
    target_npc_id: Optional[int] = None
    address: bool = False
    ratio: float = 0.0
    diff: list = field(default_factory=list, compare=False)  # [(корпус, CatQuest), …]

    @property
    def key(self):
        return self.quest_id, self.stage, self.player_gender


def _words(text: str) -> list:
    text = text.lower().replace("ё", "е")
    return re.findall(r"\w+", text)


def _target_words(tokens) -> tuple:
    """Слова варианта корпуса; обращение — слот _SLOT. Ремарки <…> не озвучиваются и в сравнение не входят."""
    words, address = [], False
    for t in tokens:
        if isinstance(t, Text):
            words.extend(_words(t.value))
        elif isinstance(t, (PlayerName, PlayerClass, PlayerRace)):
            words.append(_SLOT)
            address = True
        elif isinstance(t, WorldState):
            words.append(f"${t.id}w")
        elif not isinstance(t, (Break, StageDirection)):
            raise TypeError(t)
    return words, address


def _compare(target: list, source: list) -> tuple:
    """(статус, ratio, diff) одного варианта."""
    pattern = "".join(rf"(?:\s\S+){{0,{ADDRESS_WORDS}}}" if w is _SLOT else r"\s" + re.escape(w) for w in target)
    plain = [w for w in target if w is not _SLOT]
    matcher = difflib.SequenceMatcher(None, plain, source, autojunk=False)
    if re.fullmatch(pattern, "".join(" " + w for w in source)):
        return "exact", 1.0, []
    diff = [(" ".join(plain[i1:i2]), " ".join(source[j1:j2]))
            for op, i1, i2, j1, j2 in matcher.get_opcodes() if op != "equal"]
    ratio = matcher.ratio()
    return ("content_mismatch" if ratio < MISMATCH_RATIO else "needs_review"), ratio, diff


def _against_record(line, record, source_words):
    try:
        variants = expand_player_gender(parse(record.raw_text))
    except MarkupError as e:
        return "needs_review", f"target_markup: {e.reason}", 0.0, [], False
    if line.player_gender is not None:
        needed = [variants.get(line.player_gender, variants.get(None))]
    else:
        needed = list(variants.values())  # общий файл слышат оба пола
    worst = ("exact", 1.0, [])
    address = False
    for tokens in needed:
        target, has_address = _target_words(tokens)
        address = address or has_address
        result = _compare(target, source_words)
        if (_RANK[result[0]], -result[1]) > (_RANK[worst[0]], -worst[1]):
            worst = result
    status, ratio, diff = worst
    return status, "" if status == "exact" else "text_differs", ratio, diff, address


def _speaker_agrees(voice: Optional[str], npc_sex: Optional[int]) -> bool:
    if not voice or npc_sex is None:
        return True
    sex = re.search(r"-(male|female)\b", voice)
    if not sex:  # narrator и прочие голоса без пола
        return True
    return sex.group(1) == ("female" if npc_sex == 1 else "male")


def target_index(records) -> dict:
    """(quest_id, stage) → записи корпуса с русским текстом."""
    index = {}
    for r in records:
        if r.raw_text:
            index.setdefault((r.quest_id, r.stage), []).append(r)
    return index


def match_line(line, targets: dict, overrides: dict) -> Decision:
    base = dict(quest_id=line.quest_id, stage=line.stage, player_gender=line.player_gender,
                source_path=line.source_path, voice=line.voice, source_audio_sha256=line.audio_sha256,
                source_text_sha256=hashlib.sha256(line.text.encode("utf-8")).hexdigest() if line.text else None)
    records = targets.get((line.quest_id, line.stage))
    if not records:
        return Decision(**base, status="target_missing", reason="нет квеста/стадии с русским текстом в корпусе")
    if line.audio_sha256 is None:
        return Decision(**base, status="audio_missing", reason=line.source_path)

    best = None
    for record in records:
        if line.text is None:
            result = ("needs_review", "no_source_text", 0.0, [], False)
        else:
            result = _against_record(line, record, _words(line.text))
        status, reason, ratio, diff, address = result
        if status == "exact" and not _speaker_agrees(line.voice, record.npc_sex_id):
            status, reason = "needs_review", "speaker_sex"
        candidate = Decision(**base, status=status, reason=reason, ratio=round(ratio, 4), diff=diff, address=address,
                             target_text_sha256=source_hash(record.raw_text), target_npc_type=record.npc_type,
                             target_npc_id=record.npc_id)
        if best is None or (_RANK[candidate.status], -candidate.ratio) < (_RANK[best.status], -best.ratio):
            best = candidate
    return _apply_override(best, overrides.get(best.key)) if best.status != "exact" else best


def _apply_override(decision: Decision, override: Optional[dict]) -> Decision:
    if override is None:
        return decision
    hashes = ("source_text_sha256", "target_text_sha256", "source_audio_sha256")
    if any(override.get(h) != getattr(decision, h) for h in hashes):
        return dataclasses.replace(decision, status="needs_review", reason="stale_override")
    return dataclasses.replace(decision, status=override["decision"], reason=override["reason"])


def load_overrides(path=OVERRIDES_PATH) -> dict:
    path = Path(path)
    if not path.exists():
        return {}
    overrides = {}
    for entry in yaml.safe_load(path.read_text(encoding="utf-8")) or []:
        key = (entry["quest_id"], entry["stage"], entry.get("player_gender"))
        if entry.get("decision") not in ("approved_variant", "content_mismatch"):
            raise ValueError(f"{path}: {key}: decision {entry.get('decision')!r}")
        for required in ("reason", "reviewer"):
            if not entry.get(required):
                raise ValueError(f"{path}: {key}: нет поля {required}")
        if key in overrides:
            raise ValueError(f"{path}: повтор решения {key}")
        overrides[key] = entry
    return overrides


def match_pack(pack, records, overrides: Optional[dict] = None) -> list:
    targets = target_index(records)
    return [match_line(line, targets, overrides or {}) for line in pack.lines]


def summarize(decisions, targets: dict) -> dict:
    by_status = {}
    for d in decisions:
        by_status[d.status] = by_status.get(d.status, 0) + 1
    reasons = {}
    for d in decisions:
        if d.status == "needs_review":
            reason = d.reason.split(":")[0]
            reasons[reason] = reasons.get(reason, 0) + 1
    included = [d for d in decisions if d.status in INCLUDED]
    return {
        "by_status": dict(sorted(by_status.items(), key=lambda kv: STATUSES.index(kv[0]))),
        "needs_review_reasons": dict(sorted(reasons.items())),
        "target_quests": len({q for q, _ in targets}),
        "included_quests": len({d.quest_id for d in included}),
        "included_lines": len(included),
        "with_address": sum(d.address for d in included),
    }


def main(argv=None):
    """python -m voru.catquest match --source <zip> --target <jsonl>… --report <папка>"""
    import argparse
    import json
    import sys

    from voru.catquest.inspect import LOCK_PATH, LockMismatch, check_lock, load_lock
    from voru.catquest.reader import UnsupportedSchema, read_pack
    from voru.corpus.record import read_jsonl

    parser = argparse.ArgumentParser(prog="python -m voru.catquest match")
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--target", type=Path, action="append", required=True, help="JSONL корпуса (можно несколько)")
    parser.add_argument("--report", type=Path, required=True, help="папка: mapping.jsonl + summary.json")
    parser.add_argument("--overrides", type=Path, default=OVERRIDES_PATH)
    parser.add_argument("--target-only", action="store_true", help="только квесты, которые есть в целевом корпусе")
    parser.add_argument("--lock", type=Path, default=LOCK_PATH)
    parser.add_argument("--no-lock", action="store_true")
    args = parser.parse_args(argv)

    try:
        pack = read_pack(args.source)
        if not args.no_lock:
            check_lock(pack, load_lock(args.lock))
    except (UnsupportedSchema, LockMismatch) as e:
        print(f"ошибка: {e}", file=sys.stderr)
        sys.exit(2)
    records = [r for path in args.target for r in read_jsonl(path)]
    targets = target_index(records)
    decisions = match_pack(pack, records, load_overrides(args.overrides))
    if args.target_only:
        quests = {q for q, _ in targets}
        decisions = [d for d in decisions if d.quest_id in quests]

    args.report.mkdir(parents=True, exist_ok=True)
    with open(args.report / "mapping.jsonl", "w", encoding="utf-8", newline="\n") as f:
        for d in decisions:
            f.write(json.dumps(dataclasses.asdict(d), ensure_ascii=False, sort_keys=True) + "\n")
    summary = summarize(decisions, targets)
    (args.report / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
                                              encoding="utf-8")
    print(", ".join(f"{k}: {v}" for k, v in summary["by_status"].items()))
    print(f"в сборку: {summary['included_lines']} реплик, {summary['included_quests']} квестов "
          f"(из них с обращением: {summary['with_address']}); на ревью: {summary['needs_review_reasons']}")

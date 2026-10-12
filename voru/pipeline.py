"""Пилот одной командой: корпус → подготовка текста → кастинг → очередь → TTS → пак.

  python -m voru.pipeline --provider mock --allow-unreviewed
  python -m voru.pipeline --provider f5-tts-ru-v4 --work-dir ~/voru-work --no-pack   # в WSL
  (по умолчанию пилот Тельдрассила + смоук Тенистой долины для проверки в игре)

Заблокированные реплики и NPC без голоса попадают в отчёт, а не пропадают молча.
По умолчанию в пак идут только принятые (accepted) записи; --allow-unreviewed берёт
сгенерированные без ревью — только для тестовых паков (mock-тоны).
Для настоящих моделей рабочую папку (SQLite-очередь, мастера) держать на диске WSL, не на /mnt/c.
"""
import argparse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

from voru.casting import CastingError, cast, load_casting
from voru.config import REPO_ROOT, load_client_profile
from voru.corpus.record import addon_key, read_jsonl
from voru.exporters.pack import PackEntry, PackInfo, build_pack, file_key
from voru.jobs.queue import JobQueue
from voru.jobs.runner import enqueue_synthesis, run_worker
from voru.normalize import NORMALIZATION_REVISION
from voru.normalize.accent import Accentuator
from voru.normalize.prepare import Blocked, load_overrides, prepare_text
from voru.normalize.pronunciation import load_dictionary
from voru.providers import get_provider
from voru.providers.base import SynthesisRequest

MODULE_NAME = "AI_VoiceOverData_Vanilla_RU"
MODULE_TITLE = "VoiceOver Data - Vanilla (RU)"
PILOT_CORPUS = REPO_ROOT / "corpus" / "pilot" / "teldrassil.jsonl"
SMOKE_CORPUS = REPO_ROOT / "corpus" / "smoke" / "shadowglen.jsonl"
WORK_DIR = REPO_ROOT / "work"
TAKES = REPO_ROOT / "corpus" / "takes.yaml"
TAKE_SEED_STEP = 104729  # дубль n слота: seed голоса + n * шаг (не пересекается с шагом QA-повторов)


def load_takes(path=TAKES) -> dict:
    """Дубли по итогам прослушивания: слот → номер дубля (≥1). Причина обязательна."""
    path = Path(path)
    if not path.exists():
        return {}
    takes = {}
    for entry in yaml.safe_load(path.read_text(encoding="utf-8")) or []:
        slot, take = entry.get("slot"), entry.get("take")
        if not slot or not isinstance(take, int) or take < 1 or not entry.get("reason"):
            raise ValueError(f"{path.name}: нужна запись slot + take ≥ 1 + reason: {entry}")
        if slot in takes:
            raise ValueError(f"{path.name}: слот указан дважды: {slot}")
        takes[slot] = take
    return takes


@dataclass
class Report:
    blocked: dict = field(default_factory=dict)  # text_key → причина
    casting_errors: dict = field(default_factory=dict)  # content_id → причина
    unused_takes: list = field(default_factory=list)  # дубли этой модели, не совпавшие ни с одним слотом
    stats: dict = field(default_factory=dict)
    files: int = 0
    pack_dir: Optional[Path] = None


@dataclass(frozen=True)
class Planned:
    record: object  # SourceRecord
    variant: object  # Variant
    voice_id: str
    slot: str
    request: SynthesisRequest


def slot_of(provider_name: str, content_id: str, player_gender) -> str:
    """Слот задания: у каждой модели своя версия реплики — сравнение не вытесняет друг друга."""
    return f"{provider_name}:{content_id}|{player_gender or '-'}"


def read_corpora(paths) -> list:
    """Объединяет корпуса; одна и та же запись в нескольких корпусах учитывается один раз."""
    if isinstance(paths, (str, Path)):
        paths = [paths]
    records = {}
    for path in paths:
        for record in read_jsonl(path):
            known = records.setdefault(record.content_id, record)
            if known != record:
                raise ValueError(f"{record.content_id}: разные версии записи в корпусах ({path})")
    return list(records.values())


def plan(corpus_paths, provider_name: str, report: Report, casting=None, accent: bool = True,
         takes=TAKES) -> list:
    """Реплики к синтезу для провайдера: подготовка текста, кастинг, запрос. Проблемы — в отчёт.
    Ударения берутся из кэша corpus/accents.jsonl (python -m voru.normalize.accent warm).
    Дубли из corpus/takes.yaml меняют seed только своего слота."""
    overrides, dictionary = load_overrides(), load_dictionary()
    take_of = load_takes(takes) if takes else {}
    accentuator = Accentuator() if accent else None
    casting = casting or load_casting()
    planned = []
    for record in read_corpora(corpus_paths):
        prepared = prepare_text(record.text_key, record.raw_text, overrides, dictionary, accentuator)
        if isinstance(prepared, Blocked):
            report.blocked[record.text_key] = prepared.reason
            continue
        try:
            decision = cast(record, casting)
        except CastingError as err:
            report.casting_errors[record.content_id] = err.reason
            continue
        profile = casting.voices[decision.voice_id]
        for variant in prepared:
            slot = slot_of(provider_name, record.content_id, variant.player_gender)
            seed = profile.seed + take_of.get(slot, 0) * TAKE_SEED_STEP
            request = SynthesisRequest(
                text=variant.spoken_text, locale=record.locale, player_gender=variant.player_gender,
                voice=profile.voice_ref(casting.path.parent), delivery_profile="neutral",
                generation_config={"seed": seed, **profile.params_for(provider_name)}, output_path=None,
            )
            planned.append(Planned(record, variant, decision.voice_id, slot, request))
    used = {p.slot for p in planned}
    report.unused_takes = sorted(s for s in take_of if s.startswith(f"{provider_name}:") and s not in used)
    return planned


def build_pilot(corpus_paths, provider_name: str, work_dir=WORK_DIR, out_dir=None, version="0.1.0-pilot",
                allow_unreviewed: bool = False, pack: bool = True, accent: bool = True) -> Report:
    work_dir = Path(work_dir)
    out_dir = Path(out_dir) if out_dir else work_dir / "packs"
    casting = load_casting()
    provider = get_provider(provider_name)
    queue = JobQueue(work_dir / "jobs.sqlite")
    report = Report()

    planned = plan(corpus_paths, provider.name, report, casting, accent)
    for item in planned:
        enqueue_synthesis(queue, item.slot, provider, item.request, NORMALIZATION_REVISION)
    report.stats = run_worker(queue, provider, "pilot", work_dir / "masters")
    if not pack:
        return report

    entries = []
    for item in planned:
        jobs = queue.jobs_for_slot(item.slot)
        job = queue.accepted(item.slot) or (
            next((j for j in reversed(jobs) if j.state == "generated"), None) if allow_unreviewed else None)
        if job is None:
            continue
        record = item.record
        entries.append(PackEntry(
            content_id=record.content_id, text_key=record.text_key,
            file_key=file_key(addon_key(record), item.variant.player_gender), quest_id=record.quest_id,
            stage=record.stage, npc_type=record.npc_type, npc_id=record.npc_id, npc_name=record.npc_name,
            voice_id=item.voice_id, fingerprint=job.fingerprint, master_path=Path(job.result["output_path"]),
        ))
    if not entries:
        return report

    credits = {
        voice_id: {"provenance": p.provenance or f"нет референса ({provider.name})",
                   "license": p.license or "не указана"}
        for voice_id, p in casting.voices.items()
    }
    info = PackInfo(MODULE_NAME, MODULE_TITLE, version, load_client_profile(), priority=200)
    manifest = build_pack(entries, out_dir, info, credits)
    report.files = manifest["coverage"]["files"]
    report.pack_dir = out_dir / MODULE_NAME
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--provider", default="mock")
    parser.add_argument("--corpus", type=Path, action="append",
                        help=f"можно несколько; по умолчанию пилот и смоук: {PILOT_CORPUS.name}, {SMOKE_CORPUS.name}")
    parser.add_argument("--work-dir", type=Path, default=WORK_DIR)
    parser.add_argument("--out-dir", type=Path)
    parser.add_argument("--version", default="0.1.0-pilot")
    parser.add_argument("--allow-unreviewed", action="store_true")
    parser.add_argument("--no-pack", action="store_true", help="только синтез, без сборки пака")
    args = parser.parse_args(argv)

    report = build_pilot(args.corpus or [PILOT_CORPUS, SMOKE_CORPUS], args.provider, work_dir=args.work_dir,
                         out_dir=args.out_dir, version=args.version, allow_unreviewed=args.allow_unreviewed,
                         pack=not args.no_pack)
    print(f"синтез: {report.stats}")
    for key, reason in sorted(report.blocked.items()):
        print(f"  заблокировано {key}: {reason}")
    for key, reason in sorted(report.casting_errors.items()):
        print(f"  нет голоса {key}: {reason}")
    for slot in report.unused_takes:
        print(f"  дубль не применён (нет такого слота): {slot}")
    print(f"файлов в паке: {report.files} → {report.pack_dir or 'пак не собран'}")


if __name__ == "__main__":
    main()

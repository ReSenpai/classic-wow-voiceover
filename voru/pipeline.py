"""Пилот одной командой: корпус → подготовка текста → кастинг → очередь → TTS → пак.

  python -m voru.pipeline --provider mock --allow-unreviewed

Заблокированные реплики и NPC без голоса попадают в отчёт, а не пропадают молча.
По умолчанию в пак идут только принятые (accepted) записи; --allow-unreviewed берёт
сгенерированные без ревью — только для тестовых паков (mock-тоны).
"""
import argparse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from voru.casting import CastingError, cast, load_casting
from voru.config import REPO_ROOT, load_client_profile
from voru.corpus.record import addon_key, read_jsonl
from voru.exporters.pack import PackEntry, PackInfo, build_pack, file_key
from voru.jobs.queue import JobQueue
from voru.jobs.runner import enqueue_synthesis, run_worker
from voru.normalize import NORMALIZATION_REVISION
from voru.normalize.prepare import Blocked, load_overrides, prepare_text
from voru.normalize.pronunciation import load_dictionary
from voru.providers import get_provider
from voru.providers.base import SynthesisRequest

MODULE_NAME = "AI_VoiceOverData_Vanilla_RU"
MODULE_TITLE = "VoiceOver Data - Vanilla (RU)"
PILOT_CORPUS = REPO_ROOT / "corpus" / "pilot" / "teldrassil.jsonl"
WORK_DIR = REPO_ROOT / "work"


@dataclass
class Report:
    blocked: dict = field(default_factory=dict)  # text_key → причина
    casting_errors: dict = field(default_factory=dict)  # content_id → причина
    stats: dict = field(default_factory=dict)
    files: int = 0
    pack_dir: Optional[Path] = None


def slot_of(content_id: str, player_gender) -> str:
    return f"{content_id}|{player_gender or '-'}"


def build_pilot(corpus_path, provider_name: str, work_dir=WORK_DIR, out_dir=None, version="0.1.0-pilot",
                allow_unreviewed: bool = False) -> Report:
    work_dir = Path(work_dir)
    out_dir = Path(out_dir) if out_dir else work_dir / "packs"
    client = load_client_profile()
    overrides, dictionary, casting = load_overrides(), load_dictionary(), load_casting()
    provider = get_provider(provider_name)
    queue = JobQueue(work_dir / "jobs.sqlite")
    report = Report()

    planned = []  # (record, variant, voice_id, slot)
    for record in read_jsonl(corpus_path):
        prepared = prepare_text(record.text_key, record.raw_text, overrides, dictionary)
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
            request = SynthesisRequest(
                text=variant.spoken_text, locale=record.locale, player_gender=variant.player_gender,
                voice=profile.voice_ref(casting.path.parent), delivery_profile="neutral",
                generation_config={"seed": profile.seed, **profile.params_for(provider.name)}, output_path=None,
            )
            slot = slot_of(record.content_id, variant.player_gender)
            enqueue_synthesis(queue, slot, provider, request, NORMALIZATION_REVISION)
            planned.append((record, variant, decision.voice_id, slot))

    report.stats = run_worker(queue, provider, "pilot", work_dir / "masters")

    entries = []
    for record, variant, voice_id, slot in planned:
        jobs = queue.jobs_for_slot(slot)
        job = queue.accepted(slot) or (
            next((j for j in reversed(jobs) if j.state == "generated"), None) if allow_unreviewed else None)
        if job is None:
            continue
        entries.append(PackEntry(
            content_id=record.content_id, text_key=record.text_key,
            file_key=file_key(addon_key(record), variant.player_gender), quest_id=record.quest_id,
            stage=record.stage, npc_type=record.npc_type, npc_id=record.npc_id, npc_name=record.npc_name,
            voice_id=voice_id, fingerprint=job.fingerprint, master_path=Path(job.result["output_path"]),
        ))
    if not entries:
        return report

    credits = {
        voice_id: {"provenance": p.provenance or f"нет референса ({provider.name})",
                   "license": p.license or "не указана"}
        for voice_id, p in casting.voices.items()
    }
    info = PackInfo(MODULE_NAME, MODULE_TITLE, version, client, priority=200)
    manifest = build_pack(entries, out_dir, info, credits)
    report.files = manifest["coverage"]["files"]
    report.pack_dir = out_dir / MODULE_NAME
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--provider", default="mock")
    parser.add_argument("--corpus", type=Path, default=PILOT_CORPUS)
    parser.add_argument("--version", default="0.1.0-pilot")
    parser.add_argument("--allow-unreviewed", action="store_true")
    args = parser.parse_args(argv)

    report = build_pilot(args.corpus, args.provider, version=args.version, allow_unreviewed=args.allow_unreviewed)
    print(f"синтез: {report.stats}")
    for key, reason in sorted(report.blocked.items()):
        print(f"  заблокировано {key}: {reason}")
    for key, reason in sorted(report.casting_errors.items()):
        print(f"  нет голоса {key}: {reason}")
    print(f"файлов в паке: {report.files} → {report.pack_dir or 'пак не собран'}")


if __name__ == "__main__":
    main()

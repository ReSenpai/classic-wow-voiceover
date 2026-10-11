"""Создание референсов голосов через Qwen3-TTS VoiceDesign (дизайн §7–8).

  python -m voru.casting.design generate --voice dryad-female --count 4   # кандидаты в work/voice_design/
  python -m voru.casting.design generate --all
  python -m voru.casting.design pick --voice dryad-female --seed 1234     # выбранный → config/voice_refs/

Кандидат синтезируется из описания голоса (design_prompt или description) и его test_lines.
pick копирует WAV в config/voice_refs/, вписывает в voices.yaml reference_audio, точный
reference_text, provenance и license и поднимает revision (реплики голоса уйдут на пересинтез).
voices.yaml правится построчно — комментарии и порядок сохраняются.
"""
import argparse
import datetime
import json
import re
import shutil
from pathlib import Path

from voru.casting import CASTING_PATH, load_casting
from voru.config import REPO_ROOT
from voru.providers.base import write_wav_atomically

DESIGN_DIR = "voice_design"
REFS_DIR = "voice_refs"
DESIGN_LICENSE = "Apache-2.0 (модель Qwen3-TTS); голос сгенерирован проектом"
_REFERENCE_KEYS = ("reference_audio", "reference_text", "provenance", "license")


def _candidate_dir(work_dir, voice_id) -> Path:
    return Path(work_dir) / DESIGN_DIR / voice_id


def design_candidates(casting, voice_id: str, designer, work_dir, count: int = 3) -> list:
    profile = casting.voices[voice_id]
    if not profile.test_lines:
        raise ValueError(f"voice {voice_id}: нужны test_lines — из них синтезируется референс")
    text = " ".join(profile.test_lines)
    instruct = profile.design_prompt or profile.description
    paths = []
    for seed in range(profile.seed, profile.seed + count):
        samples, sample_rate = designer.design(text=text, instruct=instruct, seed=seed)
        path = _candidate_dir(work_dir, voice_id) / f"seed-{seed}.wav"
        write_wav_atomically(path, samples, sample_rate)
        path.with_suffix(".json").write_text(
            json.dumps({"text": text, "instruct": instruct, "seed": seed}, ensure_ascii=False), encoding="utf-8")
        paths.append(path)
    return paths


def _yaml_str(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)  # JSON-строка — валидная YAML-строка в двойных кавычках


def _set_reference_in_yaml(text: str, voice_id: str, fields: dict) -> str:
    lines = text.splitlines(keepends=True)
    start = next((i for i, l in enumerate(lines) if re.fullmatch(rf"\s*- voice_id: {re.escape(voice_id)}\s*", l)), None)
    if start is None:
        raise KeyError(f"voice {voice_id} not found")
    indent = " " * (len(lines[start]) - len(lines[start].lstrip()) + 2)
    end = start + 1
    while end < len(lines) and not re.match(r"\s*- voice_id:", lines[end]) and \
            (lines[end].startswith(indent) or not lines[end].strip()):
        end += 1
    block = [l for l in lines[start + 1:end]
             if not any(l.startswith(f"{indent}{key}:") for key in _REFERENCE_KEYS)]
    for i, line in enumerate(block):
        match = re.match(rf'{indent}revision: "?(\d+)"?\s*$', line)
        if match:
            block[i] = f'{indent}revision: "{int(match.group(1)) + 1}"\n'
            insert_at = i + 1
            break
    else:
        raise ValueError(f"voice {voice_id}: numeric revision not found")
    block[insert_at:insert_at] = [f"{indent}{key}: {_yaml_str(value)}\n" for key, value in fields.items()]
    return "".join(lines[:start + 1] + block + lines[end:])


def pick_candidate(voices_path, voice_id: str, work_dir, seed: int, designer_revision: str, date: str):
    voices_path = Path(voices_path)
    source = _candidate_dir(work_dir, voice_id) / f"seed-{seed}.wav"
    if not source.exists():
        raise FileNotFoundError(source)
    meta = json.loads(source.with_suffix(".json").read_text(encoding="utf-8"))
    relative = f"{REFS_DIR}/{voice_id}.wav"
    target = voices_path.parent / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    fields = {
        "reference_audio": relative,
        "reference_text": meta["text"],
        "provenance": f"Qwen3-TTS VoiceDesign {designer_revision}, seed {seed}, {date}",
        "license": DESIGN_LICENSE,
    }
    voices_path.write_text(_set_reference_in_yaml(voices_path.read_text(encoding="utf-8"), voice_id, fields),
                           encoding="utf-8")
    load_casting(voices_path)  # правка должна оставить реестр валидным


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    gen = sub.add_parser("generate")
    gen.add_argument("--voice", action="append", default=[])
    gen.add_argument("--all", action="store_true")
    gen.add_argument("--count", type=int, default=3)
    pick = sub.add_parser("pick")
    pick.add_argument("--voice", required=True)
    pick.add_argument("--seed", type=int, required=True)
    for p in (gen, pick):
        p.add_argument("--work-dir", type=Path, default=REPO_ROOT / "work")
    args = parser.parse_args(argv)

    from voru.providers.qwen3 import QwenVoiceDesigner

    if args.command == "generate":
        casting = load_casting()
        voices = list(casting.voices) if args.all else args.voice
        designer = QwenVoiceDesigner()
        for voice_id in voices:
            for path in design_candidates(casting, voice_id, designer, args.work_dir, args.count):
                print(path)
    else:
        pick_candidate(CASTING_PATH, args.voice, args.work_dir, args.seed,
                       QwenVoiceDesigner.model_revision, datetime.date.today().isoformat())
        print(f"{args.voice}: референс записан в {CASTING_PATH}")


if __name__ == "__main__":
    main()

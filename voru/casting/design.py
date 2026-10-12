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
import time
import wave
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


def design_candidates(casting, voice_id: str, designer, work_dir, count: int = 3, batch_size: int = 8,
                      session: str = "") -> list:
    """Кандидаты считаются батчами: генерация упирается в накладные расходы Python на каждый шаг,
    а не в GPU, поэтому N вариантов за один проход почти не дороже одного.
    Номер кандидата seed-N — для имени и pick; случайность общая на батч (batch_seed)."""
    profile = casting.voices[voice_id]
    if not profile.test_lines:
        raise ValueError(f"voice {voice_id}: нужны test_lines — из них синтезируется референс")
    text = " ".join(profile.test_lines)
    instruct = profile.design_prompt or profile.description
    existing = [int(p.stem.removeprefix("seed-")) for p in _candidate_dir(work_dir, voice_id).glob("seed-*.wav")]
    start = max(existing) + 1 if existing else profile.seed  # дописываем, понравившиеся не перезаписываем
    paths = []
    for batch_seed in range(start, start + count, batch_size):
        size = min(batch_size, start + count - batch_seed)
        results = designer.design_batch(texts=[text] * size, instructs=[instruct] * size, seed=batch_seed)
        for index, (samples, sample_rate) in enumerate(results):
            seed = batch_seed + index
            path = _candidate_dir(work_dir, voice_id) / f"seed-{seed}.wav"
            write_wav_atomically(path, samples, sample_rate)
            meta = {"text": text, "instruct": instruct, "seed": seed,
                    "batch_seed": batch_seed, "batch_index": index, "batch_size": size, "session": session}
            path.with_suffix(".json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
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


def _provenance(meta: dict, designer_revision: str, date: str) -> str:
    """Происхождение референса: модель, описание (в voices.yaml оно может позже измениться) и случайность.
    У батча случайность общая — по одному seed звук не воспроизвести, поэтому пишем и батч."""
    where = f"seed {meta['seed']}"
    if meta.get("batch_size", 1) > 1:
        where += f" (батч {meta['batch_seed']}, №{meta['batch_index'] + 1} из {meta['batch_size']})"
    return f"Qwen3-TTS VoiceDesign {designer_revision}, {where}, {date}; описание: {meta['instruct']}"


def pick_candidate(voices_path, voice_id: str, work_dir, seed: int, designer_revision: str, date: str):
    voices_path = Path(voices_path)
    source = _candidate_dir(work_dir, voice_id) / f"seed-{seed}.wav"
    if not source.exists():
        raise FileNotFoundError(source)
    meta = json.loads(source.with_suffix(".json").read_text(encoding="utf-8"))
    relative = f"{REFS_DIR}/{voice_id}.wav"
    target = voices_path.parent / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    provenance = _provenance(meta, designer_revision, date)
    fitted = fit_reference(source)  # до записи на место: не влезет — референс остаётся прежним
    if fitted is None:
        shutil.copyfile(source, target)
    else:
        samples, rate, before, after = fitted
        write_wav_atomically(target, samples, rate)
        provenance += (f"; паузы длиннее {FIT_PAUSE_S} с сжаты до {FIT_PAUSE_S} с, края подрезаны "
                       f"({before:.2f} с → {after:.2f} с, F5 читает не больше {F5_MAX_REFERENCE_S:.0f} с)")
    fields = {
        "reference_audio": relative,
        "reference_text": meta["text"],
        "provenance": provenance,
        "license": DESIGN_LICENSE,
    }
    voices_path.write_text(_set_reference_in_yaml(voices_path.read_text(encoding="utf-8"), voice_id, fields),
                           encoding="utf-8")
    load_casting(voices_path)  # правка должна оставить реестр валидным


F5_MAX_REFERENCE_S = 12.0  # F5 обрезает референс — транскрипт перестаёт совпадать со звуком
FIT_PAUSE_S = 0.25  # до скольких сжимаются паузы длинного референса
_SILENCE_LEVEL = 0.01  # ≈ −40 dBFS
_EDGE_KEEP_S = 0.05


def fit_reference(path):
    """Референс длиннее F5_MAX_REFERENCE_S укорачивается без смены слов: края подрезаются, паузы
    длиннее FIT_PAUSE_S сжимаются до FIT_PAUSE_S. Короткий → None. Не влезает → ValueError."""
    with wave.open(str(path)) as w:
        rate, frames = w.getframerate(), w.readframes(w.getnframes())
    import array

    samples = [s / 32768 for s in array.array("h", frames)]
    before = len(samples) / rate
    if before <= F5_MAX_REFERENCE_S:
        return None
    loud = [i for i, s in enumerate(samples) if abs(s) >= _SILENCE_LEVEL]
    edge = int(rate * _EDGE_KEEP_S)
    lo, hi = max(0, loud[0] - edge), min(len(samples), loud[-1] + 1 + edge)
    win, keep = int(rate * 0.02), int(rate * FIT_PAUSE_S)
    out, pos, start = [], lo, None
    for i in range(lo, hi, win):
        quiet = max(abs(s) for s in samples[i:i + win]) < _SILENCE_LEVEL
        if quiet and start is None:
            start = i
        elif not quiet and start is not None:
            if i - start > keep:
                out += samples[pos:start + keep // 2]
                pos = i - keep // 2
            start = None
    out += samples[pos:hi]
    after = len(out) / rate
    if after > F5_MAX_REFERENCE_S:
        raise ValueError(f"{path.name}: даже со сжатыми паузами {after:.1f} с > {F5_MAX_REFERENCE_S:.0f} с — "
                         f"нужны короче test_lines")
    return out, rate, before, after


def candidates_page(work_dir, latest_only: bool = True) -> Path:
    """index.html с кандидатами: плееры, текст, флаги QA и готовая команда pick.
    По умолчанию — только последняя сессия generate (старые файлы остаются на диске)."""
    import html
    import wave

    from voru.qa.audio import check_audio

    root = Path(work_dir) / DESIGN_DIR
    metas = {w: json.loads(w.with_suffix(".json").read_text(encoding="utf-8")) for w in root.glob("*/seed-*.wav")}
    latest = max((m.get("session", "") for m in metas.values()), default="")
    sections = []
    for voice_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        rows = []
        for wav_path in sorted(voice_dir.glob("seed-*.wav")):
            meta = metas[wav_path]
            if latest_only and meta.get("session", "") != latest:
                continue
            with wave.open(str(wav_path)) as w:
                seconds = w.getnframes() / w.getframerate()
            notes = [f"{f.reason}: {f.detail}" for f in check_audio(wav_path, meta["text"])]
            if seconds > F5_MAX_REFERENCE_S:
                notes.append(f"{seconds:.1f} с — длиннее 12 с: F5 обрежет референс")
            seed = wav_path.stem.removeprefix("seed-")
            command = f"python -m voru.casting.design pick --voice {voice_dir.name} --seed {seed}"
            rows.append(
                f'<div class="cand"><audio controls preload="none" src="{voice_dir.name}/{wav_path.name}"></audio>'
                f"<span>seed {seed} · {seconds:.1f} с</span><code>{html.escape(command)}</code>"
                f'<p class="prompt">{html.escape(meta["instruct"])}</p>'
                + "".join(f'<p class="warn">{html.escape(n)}</p>' for n in notes) + "</div>")
        text = json.loads(next(voice_dir.glob("seed-*.json")).read_text(encoding="utf-8")) if rows else {}
        if not rows:
            continue
        sections.append(f"<section><h2>{html.escape(voice_dir.name)}</h2>"
                        f"<p><i>{html.escape(text.get('text', ''))}</i></p>"
                        f"{''.join(rows)}</section>")
    style = (":root{--bg:#fafaf8;--fg:#1d1d1b;--line:#deddd8;--warn:#a8552b}"
             "@media(prefers-color-scheme:dark){:root{--bg:#171716;--fg:#ecebe6;--line:#3a3a36;--warn:#e0915f}}"
             "body{margin:0;padding:16px;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,sans-serif}"
             "main{max-width:900px;margin:0 auto}section{border-bottom:1px solid var(--line);padding:8px 0}"
             ".cand{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin:6px 0}"
             "audio{width:320px;max-width:100%}code{font-size:12px}.warn{color:var(--warn);margin:0;width:100%}"
             ".prompt{opacity:.7;font-size:13px;margin:0;width:100%}")
    page = root / "index.html"
    page.write_text(f'<!doctype html><html lang="ru"><head><meta charset="utf-8">'
                    f'<meta name="viewport" content="width=device-width, initial-scale=1"><title>Кандидаты голосов</title>'
                    f"<style>{style}</style></head><body><main><h1>Кандидаты голосов</h1>{''.join(sections)}"
                    f"</main></body></html>\n", encoding="utf-8")
    return page


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    gen = sub.add_parser("generate")
    gen.add_argument("--voice", action="append", default=[])
    gen.add_argument("--all", action="store_true")
    gen.add_argument("--count", type=int, default=3)
    gen.add_argument("--batch-size", type=int, default=8)
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
        session = datetime.datetime.now().isoformat(timespec="seconds")  # страница покажет только эту сессию
        for voice_id in voices:
            started = time.perf_counter()
            paths = design_candidates(casting, voice_id, designer, args.work_dir, args.count, args.batch_size,
                                      session=session)
            elapsed = time.perf_counter() - started
            audio = sum(wave.open(str(p)).getnframes() / wave.open(str(p)).getframerate() for p in paths)
            print(f"{voice_id}: {len(paths)} шт., звук {audio:.0f} с за {elapsed:.0f} с, RTF {elapsed / audio:.2f}")
    else:
        pick_candidate(CASTING_PATH, args.voice, args.work_dir, args.seed,
                       QwenVoiceDesigner.model_revision, datetime.date.today().isoformat())
        print(f"{args.voice}: референс записан в {CASTING_PATH}")


if __name__ == "__main__":
    main()

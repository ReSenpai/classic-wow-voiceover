"""Приёмка реплик одной модели (дизайн §10): прослушать → «принять» / «брак» → accepted в очереди.

Страница не слепая: модель уже выбрана A/B. Каждое решение привязано к fingerprint звука,
который слушали, — если реплику пересинтезировали после прослушивания, решение не применяется.
Брак лечится текстом (corpus/pronunciation.yaml, overrides) или новым дублем (corpus/takes.yaml).

  python -m voru.review.acceptance build --provider f5-tts-ru-v4 --work-dir ~/voru-work --out work/review/accept
  python -m voru.review.acceptance apply --work-dir ~/voru-work --decisions work/review/accept/decisions.json
"""
import argparse
import html
import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from voru.review import _STYLE, _listenable_job

VERDICTS = ("accept", "reject")


def build_acceptance_page(corpus_paths, provider_name: str, work_dir, out_dir, include_accepted: bool = False) -> Path:
    from voru.jobs.queue import JobQueue
    from voru.pipeline import Report, plan

    queue = JobQueue(Path(work_dir) / "jobs.sqlite")
    out = Path(out_dir)
    items, cards = {}, []
    planned_items = plan(corpus_paths, provider_name, Report(), recordings_root=Path(work_dir) / "recordings")
    for planned in sorted(planned_items, key=lambda p: p.slot):
        job = _listenable_job(queue, planned.slot)
        if job is None or (job.state == "accepted" and not include_accepted):
            continue
        record = planned.record
        items[planned.slot] = {
            "fingerprint": job.fingerprint,
            "audio": f"{job.fingerprint[:16]}.wav",
            "title": f"{record.quest_title or record.quest_id} · {record.stage}",
            "npc_name": record.npc_name or "",
            "player_gender": planned.variant.player_gender,
            "spoken_text": planned.variant.spoken_text,
            "source": Path(job.result["output_path"]),
            "flag": job.last_error if job.state == "review_required" else None,
            "state": job.state,
        }
    if not items:
        raise ValueError(f"{provider_name}: нечего слушать — нет непринятых сгенерированных реплик")

    shutil.rmtree(out, ignore_errors=True)
    (out / "audio").mkdir(parents=True)
    for slot, item in items.items():
        shutil.copyfile(item.pop("source"), out / "audio" / item["audio"])
        cards.append(_card(slot, item))
    (out / "items.json").write_text(json.dumps(items, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                                    encoding="utf-8")
    (out / "index.html").write_text(_page(cards, f"accept-{provider_name}-{len(items)}"), encoding="utf-8")
    return out


def _card(slot, item) -> str:
    e = html.escape
    gender = {"m": " · игрок-мужчина", "f": " · игрок-женщина"}.get(item["player_gender"], "")
    flag = f'<p class="flag">QA: {e(item["flag"])}</p>' if item["flag"] else ""
    done = " (уже принято)" if item["state"] == "accepted" else ""
    choice = "".join(f'<label><input type="radio" name="v-{e(slot)}" value="{v}"> {t}</label>'
                     for v, t in (("accept", "Принять"), ("reject", "Брак")))
    return (f'<section class="card" data-slot="{e(slot)}" data-fingerprint="{e(item["fingerprint"])}">'
            f'<header><b>{e(item["title"])}</b> · {e(item["npc_name"])}{gender}{done}'
            f' <small>{e(slot)}</small></header>'
            f'<p class="spoken">{e(item["spoken_text"])}</p>{flag}'
            f'<audio controls preload="none" src="audio/{e(item["audio"])}"></audio>'
            f'<div class="choice">{choice}</div>'
            f'<textarea placeholder="Что не так: ударение, обрыв, пропуск, интонация…"></textarea></section>')


_SCRIPT = """
const STORE = "voru-" + document.body.dataset.report;
function load() { try { return JSON.parse(localStorage.getItem(STORE)) || {}; } catch (e) { return {}; } }
function save(state) { try { localStorage.setItem(STORE, JSON.stringify(state)); } catch (e) {} }
function collect() {
  const items = {};
  document.querySelectorAll(".card").forEach(card => {
    const picked = card.querySelector("input[type=radio]:checked"), comment = card.querySelector("textarea").value;
    if (picked || comment) items[card.dataset.slot] = {
      fingerprint: card.dataset.fingerprint, verdict: picked ? picked.value : null, comment };
  });
  return { items };
}
function restore() {
  const state = load().items || {};
  document.querySelectorAll(".card").forEach(card => {
    const r = state[card.dataset.slot]; if (!r || r.fingerprint !== card.dataset.fingerprint) return;
    if (r.verdict) { const i = card.querySelector(`input[value="${r.verdict}"]`); if (i) i.checked = true; }
    card.querySelector("textarea").value = r.comment || "";
  });
}
function progress() {
  const items = Object.values(collect().items);
  document.getElementById("progress").textContent = items.filter(r => r.verdict).length + " / "
    + document.querySelectorAll(".card").length + " · брак: " + items.filter(r => r.verdict === "reject").length;
}
document.addEventListener("change", () => { save(collect()); progress(); });
document.addEventListener("input", () => save(collect()));
document.getElementById("export").addEventListener("click", () => {
  const blob = new Blob([JSON.stringify(collect(), null, 2)], { type: "application/json" });
  const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = "decisions.json"; a.click();
});
restore(); progress();
"""


def _page(cards, report_id: str) -> str:
    return (f'<!doctype html><html lang="ru"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width, initial-scale=1"><title>Приёмка реплик</title>'
            f'<style>{_STYLE}</style></head><body data-report="{html.escape(report_id)}"><main>'
            f'<div class="bar"><b>Приёмка</b><span id="progress"></span>'
            f'<button id="export">Экспорт decisions.json</button></div>'
            f'<p>«Принять» — реплика идёт в пак как есть. «Брак» — опишите, что не так. '
            f'Решения сохраняются в браузере.</p>'
            f'{"".join(cards)}</main><script>{_SCRIPT}</script></body></html>\n')


@dataclass
class AcceptanceSummary:
    accepted: int = 0
    already: int = 0
    rejected: dict = field(default_factory=dict)  # слот → комментарий
    stale: list = field(default_factory=list)  # решения о звуке, который уже заменён
    undecided: int = 0


def apply_decisions(work_dir, decisions: dict) -> AcceptanceSummary:
    from voru.jobs.queue import JobQueue

    items = decisions.get("items", {})
    for slot, d in items.items():
        if d.get("verdict") not in (*VERDICTS, None):
            raise ValueError(f"{slot}: неизвестный verdict {d.get('verdict')!r}")
    queue = JobQueue(Path(work_dir) / "jobs.sqlite")
    summary = AcceptanceSummary()
    for slot, d in sorted(items.items()):
        if d.get("verdict") is None:
            summary.undecided += 1
            continue
        job = _listenable_job(queue, slot)
        if job is None or job.fingerprint != d.get("fingerprint"):
            summary.stale.append(slot)
        elif d["verdict"] == "reject":
            summary.rejected[slot] = d.get("comment", "")
        elif job.state == "accepted":
            summary.already += 1
        else:
            queue.accept(job.job_id)
            summary.accepted += 1
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    bd = sub.add_parser("build")
    bd.add_argument("--provider", required=True)
    bd.add_argument("--work-dir", type=Path, required=True)
    bd.add_argument("--out", type=Path, required=True)
    bd.add_argument("--corpus", type=Path, action="append")
    bd.add_argument("--include-accepted", action="store_true")
    ap = sub.add_parser("apply")
    ap.add_argument("--work-dir", type=Path, required=True)
    ap.add_argument("--decisions", type=Path, required=True)
    args = parser.parse_args(argv)

    if args.command == "build":
        from voru.pipeline import PILOT_CORPUS, SMOKE_CORPUS

        out = build_acceptance_page(args.corpus or [PILOT_CORPUS, SMOKE_CORPUS], args.provider, args.work_dir,
                                    args.out, args.include_accepted)
        count = len(json.loads((out / "items.json").read_text(encoding="utf-8")))
        print(f"страница: {out / 'index.html'} (реплик: {count})")
        return
    s = apply_decisions(args.work_dir, json.loads(args.decisions.read_text(encoding="utf-8")))
    print(f"принято: {s.accepted}, уже было: {s.already}, брак: {len(s.rejected)}, "
          f"устарело: {len(s.stale)}, без решения: {s.undecided}")
    for slot, comment in s.rejected.items():
        print(f"  брак {slot}: {comment}")
    for slot in s.stale:
        print(f"  устарело (звук заменён после прослушивания) {slot}")


if __name__ == "__main__":
    main()

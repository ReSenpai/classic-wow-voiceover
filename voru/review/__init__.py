"""Слепое A/B-прослушивание (дизайн §10): локальный HTML без сервера.

build_ab_report() кладёт в папку index.html, audio/ (имена не выдают модель) и key.json
(соответствие сторон A/B моделям — страница его не читает). Оценки хранятся в браузере
и выгружаются кнопкой в ratings.json; score() раскрывает ключ и считает метрики:
доля побед без ничьих (порог пилота 75%), число оценок, медианы естественности и роли.

  python -m voru.review score --key work/review/<имя>/key.json --ratings ratings.json
"""
import argparse
import hashlib
import html
import json
import random
import shutil
import statistics
from dataclasses import dataclass, field
from pathlib import Path

CRITERIA = (("natural", "Естественность"), ("role", "Соответствие роли"))


@dataclass(frozen=True)
class ReviewItem:
    item_id: str
    title: str
    npc_name: str
    raw_text: str
    spoken_text: str
    candidates: dict  # система → путь к WAV
    flags: dict = field(default_factory=dict)  # система → [причины QA]


def _audio_name(seed, item_id, side) -> str:
    return hashlib.sha256(f"{seed}|{item_id}|{side}".encode("utf-8")).hexdigest()[:16] + ".wav"


def build_ab_report(items, out_dir, seed: int) -> Path:
    items = sorted(items, key=lambda i: i.item_id)
    for item in items:
        if len(item.candidates) != 2:
            raise ValueError(f"{item.item_id}: для A/B нужно ровно 2 системы, получено {len(item.candidates)}")
    rng = random.Random(seed)
    swaps = [n % 2 == 0 for n in range(len(items))]  # поровну A/B для каждой системы
    rng.shuffle(swaps)

    out = Path(out_dir)
    shutil.rmtree(out, ignore_errors=True)
    (out / "audio").mkdir(parents=True)
    key, cards = {}, []
    for item, swap in zip(items, swaps):
        first, second = sorted(item.candidates)
        sides = {"A": second, "B": first} if swap else {"A": first, "B": second}
        key[item.item_id] = sides
        players = []
        for side, system in sides.items():
            name = _audio_name(seed, item.item_id, side)
            shutil.copyfile(item.candidates[system], out / "audio" / name)
            players.append((side, name, item.flags.get(system, [])))
        cards.append(_card(item, players))
    (out / "key.json").write_text(json.dumps(key, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                                  encoding="utf-8")
    (out / "index.html").write_text(_page(cards, f"ab-{seed}-{len(items)}"), encoding="utf-8")
    return out


def _card(item, players) -> str:
    e = html.escape
    sides = []
    for side, audio, flags in players:
        selects = "".join(
            f'<label>{e(label)} <select data-score="{side}:{code}"><option value="">—</option>'
            + "".join(f"<option>{n}</option>" for n in range(1, 6)) + "</select></label>"
            for code, label in CRITERIA)
        flag_html = "".join(f'<li class="flag">{e(f)}</li>' for f in flags)
        sides.append(f'<div class="side"><h3>{side}</h3><audio controls preload="none" src="audio/{audio}"></audio>'
                     f'<div class="scores">{selects}</div><ul>{flag_html}</ul></div>')
    choice = "".join(f'<label><input type="radio" name="c-{e(item.item_id)}" value="{v}"> {t}</label>'
                     for v, t in (("A", "Лучше A"), ("tie", "Одинаково"), ("B", "Лучше B")))
    return (f'<section class="card" data-item="{e(item.item_id)}"><header><b>{e(item.title)}</b> · {e(item.npc_name)}'
            f' <small>{e(item.item_id)}</small></header>'
            f'<details><summary>Текст</summary><p class="raw">{e(item.raw_text)}</p></details>'
            f'<p class="spoken">{e(item.spoken_text)}</p><div class="pair">{"".join(sides)}</div>'
            f'<div class="choice">{choice}</div><textarea placeholder="Комментарий: ударения, обрывы, лишние слова…">'
            f'</textarea></section>')


_STYLE = """
:root { --bg: #fafaf8; --fg: #1d1d1b; --muted: #6b6b66; --card: #ffffff; --line: #deddd8; --accent: #3b6ea8; --warn: #a8552b; }
@media (prefers-color-scheme: dark) { :root { --bg: #171716; --fg: #ecebe6; --muted: #9a998f; --card: #222220;
  --line: #3a3a36; --accent: #7aa7da; --warn: #e0915f; } }
body { margin: 0; padding: 16px; background: var(--bg); color: var(--fg); font: 15px/1.5 system-ui, sans-serif; }
main { max-width: 980px; margin: 0 auto; }
.bar { position: sticky; top: 0; background: var(--bg); padding: 8px 0; display: flex; gap: 12px; align-items: center; }
.card { background: var(--card); border: 1px solid var(--line); border-radius: 10px; padding: 14px; margin: 14px 0; }
header small { color: var(--muted); margin-left: 6px; }
.spoken { font-size: 16px; }
.raw { color: var(--muted); }
.pair { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
@media (max-width: 640px) { .pair { grid-template-columns: 1fr; } }
.side { border: 1px solid var(--line); border-radius: 8px; padding: 10px; }
.side h3 { margin: 0 0 6px; }
audio { width: 100%; }
.scores { display: flex; gap: 12px; flex-wrap: wrap; margin-top: 6px; }
.flag { color: var(--warn); }
.choice { display: flex; gap: 18px; margin: 10px 0; }
textarea { width: 100%; box-sizing: border-box; min-height: 48px; background: var(--bg); color: var(--fg);
  border: 1px solid var(--line); border-radius: 6px; padding: 6px; }
button { background: var(--accent); color: #fff; border: 0; border-radius: 6px; padding: 8px 14px; cursor: pointer; }
"""

_SCRIPT = """
const STORE = "voru-" + document.body.dataset.report;
function load() { try { return JSON.parse(localStorage.getItem(STORE)) || {}; } catch (e) { return {}; } }
function save(state) { try { localStorage.setItem(STORE, JSON.stringify(state)); } catch (e) {} }
function collect() {
  const items = {};
  document.querySelectorAll(".card").forEach(card => {
    const id = card.dataset.item, picked = card.querySelector("input[type=radio]:checked");
    const scores = {};
    card.querySelectorAll("select[data-score]").forEach(s => {
      if (!s.value) return;
      const [side, code] = s.dataset.score.split(":");
      (scores[side] = scores[side] || {})[code] = Number(s.value);
    });
    const comment = card.querySelector("textarea").value;
    if (picked || Object.keys(scores).length || comment) items[id] = { choice: picked ? picked.value : null, scores, comment };
  });
  return { items };
}
function restore() {
  const state = load().items || {};
  document.querySelectorAll(".card").forEach(card => {
    const r = state[card.dataset.item]; if (!r) return;
    if (r.choice) { const i = card.querySelector(`input[value="${r.choice}"]`); if (i) i.checked = true; }
    card.querySelectorAll("select[data-score]").forEach(s => {
      const [side, code] = s.dataset.score.split(":"); const v = (r.scores[side] || {})[code]; if (v) s.value = v;
    });
    card.querySelector("textarea").value = r.comment || "";
  });
}
function progress() {
  const done = Object.values(collect().items).filter(r => r.choice).length;
  document.getElementById("progress").textContent = done + " / " + document.querySelectorAll(".card").length;
}
document.addEventListener("change", () => { save(collect()); progress(); });
document.addEventListener("input", () => save(collect()));
document.getElementById("export").addEventListener("click", () => {
  const blob = new Blob([JSON.stringify(collect(), null, 2)], { type: "application/json" });
  const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = "ratings.json"; a.click();
});
restore(); progress();
"""


def _page(cards, report_id: str) -> str:
    return (f'<!doctype html><html lang="ru"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width, initial-scale=1"><title>Слепое A/B</title>'
            f'<style>{_STYLE}</style></head><body data-report="{html.escape(report_id)}"><main>'
            f'<div class="bar"><b>Слепое прослушивание</b><span id="progress"></span>'
            f'<button id="export">Экспорт ratings.json</button></div>'
            f'<p>Оцените пары, не зная модель. Ничья — если разница не слышна. Оценки сохраняются в браузере.</p>'
            f'{"".join(cards)}</main><script>{_SCRIPT}</script></body></html>\n')


def score(key: dict, ratings: dict) -> dict:
    systems = sorted({s for sides in key.values() for s in sides.values()})
    stats = {s: {"wins": 0, "losses": 0, "ties": 0, "rated_pairs": 0, "natural": [], "role": []} for s in systems}
    for item_id, rating in ratings.get("items", {}).items():
        if item_id not in key:
            raise ValueError(f"оценка для unknown элемента {item_id}")
        sides = key[item_id]
        choice = rating.get("choice")
        if choice in ("A", "B", "tie"):
            for side, system in sides.items():
                stats[system]["rated_pairs"] += 1
                if choice == "tie":
                    stats[system]["ties"] += 1
                else:
                    stats[system]["wins" if side == choice else "losses"] += 1
        for side, values in (rating.get("scores") or {}).items():
            for code, _ in CRITERIA:
                if code in values:
                    stats[sides[side]][code].append(values[code])

    summary = {}
    for system, s in stats.items():
        decided = s["wins"] + s["losses"]
        summary[system] = {
            "wins": s["wins"], "losses": s["losses"], "ties": s["ties"], "rated_pairs": s["rated_pairs"],
            "preference": s["wins"] / decided if decided else None,
            "median_natural": statistics.median(s["natural"]) if s["natural"] else None,
            "median_role": statistics.median(s["role"]) if s["role"] else None,
        }
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sc = sub.add_parser("score")
    sc.add_argument("--key", type=Path, required=True)
    sc.add_argument("--ratings", type=Path, required=True)
    args = parser.parse_args(argv)

    key = json.loads(args.key.read_text(encoding="utf-8"))
    summary = score(key, json.loads(args.ratings.read_text(encoding="utf-8")))
    for system, s in summary.items():
        pref = "—" if s["preference"] is None else f"{s['preference']:.0%}"
        print(f"{system:28} победы {s['wins']:3} поражения {s['losses']:3} ничьи {s['ties']:3} "
              f"предпочтение {pref:>5}  естественность {s['median_natural']}  роль {s['median_role']}  "
              f"(оценено пар: {s['rated_pairs']})")


if __name__ == "__main__":
    main()

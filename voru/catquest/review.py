"""Ревью спорных сопоставлений (дизайн CQ §7): прослушать → «текст клиента, взять» / «не то».

Страница показывает текст корпуса и текст CatQuest (субтитры) с подсветкой различий и звук из пака.
Решение привязано к хэшам текстов и звука; apply пишет его в mapping-overrides.yaml.

  python -m voru.catquest review build --source <zip> --target <jsonl>… --mapping work/catquest/match-pilot/mapping.jsonl --out work/catquest/review-pilot
  python -m voru.catquest review apply --out work/catquest/review-pilot --decisions <decisions.json>
"""
import argparse
import html
import json
import re
from pathlib import Path

import yaml

from voru.catquest.match import OVERRIDES_PATH, Decision, load_overrides
from voru.catquest.reader import PackFiles
from voru.normalize.markup import (
    Break,
    PlayerClass,
    PlayerName,
    PlayerRace,
    StageDirection,
    Text,
    WorldState,
    expand_player_gender,
    parse,
)
from voru.review import _STYLE

DISPUTED = ("needs_review", "content_mismatch")
HASHES = ("source_text_sha256", "target_text_sha256", "source_audio_sha256")
VERDICTS = {"approve": "approved_variant", "reject": "content_mismatch"}


def review_key(quest_id, stage, player_gender) -> str:
    return f"{quest_id}:{stage}:{player_gender or 'x'}"


def _show(tokens) -> str:
    parts = []
    for t in tokens:
        if isinstance(t, Text):
            parts.append(t.value)
        elif isinstance(t, Break):
            parts.append("\n")
        elif isinstance(t, (PlayerName, PlayerClass, PlayerRace)):
            parts.append("‹обращение›")
        elif isinstance(t, StageDirection):
            parts.append(f"<{t.text}>")
        elif isinstance(t, WorldState):
            parts.append(f"${t.id}w")
    return re.sub(r"\n{2,}", "\n", "".join(parts)).strip()


def target_text(raw: str, player_gender) -> str:
    """Текст корпуса так, как его увидит игрок этого пола (для общего файла — оба варианта)."""
    try:
        variants = expand_player_gender(parse(raw))
    except ValueError:
        return raw
    if player_gender is not None:
        return _show(variants.get(player_gender, variants.get(None)))
    if None in variants:
        return _show(variants[None])
    return f"[игрок-мужчина] {_show(variants['m'])}\n[игрок-женщина] {_show(variants['f'])}"


def build_review_page(pack, source, records, decisions, out_dir) -> Path:
    files = PackFiles(Path(source))
    lines = {(l.quest_id, l.stage, l.player_gender): l for l in pack.lines}
    by_npc = {(r.quest_id, r.stage, r.npc_type, r.npc_id): r for r in records}
    disputed = [d for d in decisions if d.status in DISPUTED]
    if not disputed:
        raise ValueError("нечего слушать: нет реплик needs_review / content_mismatch")

    out = Path(out_dir)
    (out / "audio").mkdir(parents=True, exist_ok=True)
    items, cards = {}, []
    for d in disputed:
        line = lines[d.key]
        record = by_npc.get((d.quest_id, d.stage, d.target_npc_type, d.target_npc_id))
        audio = f"{d.source_audio_sha256[:16]}.ogg" if d.source_audio_sha256 else None
        if audio:
            (out / "audio" / audio).write_bytes(files.read(d.source_path))
        key = review_key(*d.key)
        items[key] = {
            **{h: getattr(d, h) for h in HASHES},
            "quest_id": d.quest_id, "stage": d.stage, "player_gender": d.player_gender,
            "status": d.status, "reason": d.reason, "voice": d.voice, "audio": audio,
            "npc_name": record.npc_name if record else None, "quest_title": record.quest_title if record else None,
            "source_text": line.text, "target_text": target_text(record.raw_text, d.player_gender) if record else None,
            "diff": d.diff,
        }
        cards.append(_card(key, items[key]))
    (out / "items.json").write_text(json.dumps(items, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out / "index.html").write_text(_page(cards, f"catquest-review-{len(items)}"), encoding="utf-8")
    return out


def _marked(text, changed_words) -> str:
    """Подсветка слов, попавших в diff (сравнение без регистра и «ё»)."""
    if not text:
        return "<i>нет текста</i>"
    changed = {w for w in changed_words if w}
    out = []
    for token in re.split(r"(\w+)", text):
        canon = token.lower().replace("ё", "е")
        out.append(f"<mark>{html.escape(token)}</mark>" if canon in changed else html.escape(token))
    return "".join(out).replace("\n", "<br>")


def _card(key, item) -> str:
    e = html.escape
    target_changed = {w for a, _ in item["diff"] for w in a.split()}
    source_changed = {w for _, b in item["diff"] for w in b.split()}
    gender = {"m": " · игрок-мужчина", "f": " · игрок-женщина"}.get(item["player_gender"], " · общий файл")
    status = "другой текст?" if item["status"] == "content_mismatch" else item["reason"]
    hashes = " ".join(f'data-{h.replace("_", "-")}="{e(item[h] or "")}"' for h in HASHES)
    audio = (f'<audio controls preload="none" src="audio/{e(item["audio"])}"></audio>' if item["audio"]
             else "<p>нет звука</p>")
    choice = "".join(f'<label><input type="radio" name="v-{e(key)}" value="{v}"> {t}</label>'
                     for v, t in (("approve", "Взять (звук верный)"), ("reject", "Не брать")))
    return (f'<section class="card" data-key="{e(key)}" {hashes}>'
            f'<header><b>{e(str(item["quest_title"] or item["quest_id"]))} · {e(item["stage"])}</b>'
            f' · {e(item["npc_name"] or "")}{gender} · голос {e(item["voice"] or "?")}'
            f' <small>{e(key)} · {e(status)}</small></header>'
            f'<div class="pair"><div><h4>Корпус (vmangos)</h4><p>{_marked(item["target_text"], target_changed)}</p></div>'
            f'<div><h4>CatQuest (звучит)</h4><p>{_marked(item["source_text"], source_changed)}</p></div></div>'
            f'{audio}<div class="choice">{choice}</div>'
            f'<textarea placeholder="Почему: так в клиенте / другая реплика / ошибка в звуке…"></textarea></section>')


_SCRIPT = """
const STORE = "voru-" + document.body.dataset.report;
const HASHES = ["source_text_sha256", "target_text_sha256", "source_audio_sha256"];
function load() { try { return JSON.parse(localStorage.getItem(STORE)) || {}; } catch (e) { return {}; } }
function save(state) { try { localStorage.setItem(STORE, JSON.stringify(state)); } catch (e) {} }
function collect() {
  const items = {};
  document.querySelectorAll(".card").forEach(card => {
    const picked = card.querySelector("input[type=radio]:checked"), comment = card.querySelector("textarea").value;
    if (!picked && !comment) return;
    const item = { verdict: picked ? picked.value : null, comment };
    HASHES.forEach(h => item[h] = card.dataset[h.replace(/_(\\w)/g, (m, c) => c.toUpperCase())] || null);
    items[card.dataset.key] = item;
  });
  return { items };
}
function restore() {
  const state = load().items || {};
  document.querySelectorAll(".card").forEach(card => {
    const r = state[card.dataset.key]; if (!r || r.source_audio_sha256 !== (card.dataset.sourceAudioSha256 || null)) return;
    if (r.verdict) { const i = card.querySelector(`input[value="${r.verdict}"]`); if (i) i.checked = true; }
    card.querySelector("textarea").value = r.comment || "";
  });
}
function progress() {
  const items = Object.values(collect().items);
  document.getElementById("progress").textContent = items.filter(r => r.verdict).length + " / "
    + document.querySelectorAll(".card").length + " · не брать: " + items.filter(r => r.verdict === "reject").length;
}
document.addEventListener("change", () => { save(collect()); progress(); });
document.addEventListener("input", () => save(collect()));
document.getElementById("export").addEventListener("click", () => {
  const blob = new Blob([JSON.stringify(collect(), null, 2)], { type: "application/json" });
  const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = "decisions.json"; a.click();
});
restore(); progress();
"""

_EXTRA_STYLE = """
.pair { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.pair h4 { margin: 4px 0; font-size: 13px; opacity: .7; }
mark { background: #ffe08a; color: inherit; border-radius: 3px; padding: 0 2px; }
@media (prefers-color-scheme: dark) { mark { background: #6b5200; } }
@media (max-width: 700px) { .pair { grid-template-columns: 1fr; } }
"""


def _page(cards, report_id: str) -> str:
    return (f'<!doctype html><html lang="ru"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width, initial-scale=1"><title>Ревью CatQuest</title>'
            f'<style>{_STYLE}{_EXTRA_STYLE}</style></head><body data-report="{html.escape(report_id)}"><main>'
            f'<div class="bar"><b>Ревью CatQuest</b><span id="progress"></span>'
            f'<button id="export">Экспорт decisions.json</button></div>'
            f'<p>Слева — текст нашего корпуса (vmangos, может отличаться от клиента), справа — что звучит в CatQuest. '
            f'Жёлтым — различия. «Взять» — звук подходит к квесту и стадии в игре. «Не брать» — другая реплика или '
            f'ошибка. Решения сохраняются в браузере.</p>'
            f'{"".join(cards)}</main><script>{_SCRIPT}</script></body></html>\n')


def apply_review(decisions: dict, review_dir, overrides_path=OVERRIDES_PATH, reviewer: str = "пользователь") -> dict:
    items = json.loads((Path(review_dir) / "items.json").read_text(encoding="utf-8"))
    overrides = load_overrides(overrides_path)
    summary = {"applied": 0, "stale": [], "undecided": 0}
    for key, d in sorted(decisions.get("items", {}).items()):
        if d.get("verdict") is None:
            summary["undecided"] += 1
            continue
        if d["verdict"] not in VERDICTS:
            raise ValueError(f"{key}: неизвестный verdict {d['verdict']!r}")
        item = items.get(key)
        if item is None or any(item[h] != d.get(h) for h in HASHES):
            summary["stale"].append(key)
            continue
        default = "прослушано: звук подходит" if d["verdict"] == "approve" else "прослушано: не та реплика"
        entry = {"quest_id": item["quest_id"], "stage": item["stage"], "player_gender": item["player_gender"],
                 **{h: item[h] for h in HASHES}, "decision": VERDICTS[d["verdict"]],
                 "reason": (d.get("comment") or "").strip() or default, "reviewer": reviewer}
        overrides[(item["quest_id"], item["stage"], item["player_gender"])] = entry
        summary["applied"] += 1
    _write_overrides(overrides_path, overrides)
    return summary


def _write_overrides(path, overrides: dict):
    path = Path(path)
    header = ""
    if path.exists():
        header = "".join(l for l in path.read_text(encoding="utf-8").splitlines(keepends=True) if l.startswith("#"))
    entries = [overrides[k] for k in sorted(overrides, key=lambda k: (k[0], k[1], k[2] or ""))]
    body = yaml.safe_dump(entries, allow_unicode=True, sort_keys=False, width=120) if entries else "[]\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(header + body, encoding="utf-8")


def main(argv=None):
    from voru.catquest.reader import read_pack
    from voru.corpus.record import read_jsonl

    parser = argparse.ArgumentParser(prog="python -m voru.catquest review", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    bd = sub.add_parser("build")
    bd.add_argument("--source", type=Path, required=True)
    bd.add_argument("--target", type=Path, action="append", required=True)
    bd.add_argument("--mapping", type=Path, required=True)
    bd.add_argument("--out", type=Path, required=True)
    ap = sub.add_parser("apply")
    ap.add_argument("--out", type=Path, required=True, help="папка страницы ревью")
    ap.add_argument("--decisions", type=Path, required=True)
    ap.add_argument("--overrides", type=Path, default=OVERRIDES_PATH)
    ap.add_argument("--reviewer", default="пользователь")
    args = parser.parse_args(argv)

    if args.command == "build":
        decisions = [Decision(**{**json.loads(l), "diff": [tuple(p) for p in json.loads(l)["diff"]]})
                     for l in args.mapping.read_text(encoding="utf-8").splitlines() if l.strip()]
        records = [r for path in args.target for r in read_jsonl(path)]
        out = build_review_page(read_pack(args.source), args.source, records, decisions, args.out)
        count = len(json.loads((out / "items.json").read_text(encoding="utf-8")))
        print(f"страница: {out / 'index.html'} (реплик: {count})")
        return
    s = apply_review(json.loads(args.decisions.read_text(encoding="utf-8")), args.out, args.overrides,
                     args.reviewer)
    print(f"записано решений: {s['applied']}, устарело: {len(s['stale'])}, без решения: {s['undecided']}")
    for key in s["stale"]:
        print(f"  устарело (текст или звук изменились) {key}")

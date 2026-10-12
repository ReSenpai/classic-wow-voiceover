"""Стенд записи реплик своим голосом: сценарий + запись в браузере + сохранение в папку.

Локальный сервер (только 127.0.0.1): страница со сценарием (ударные гласные выделены),
кнопки «Записать / Стоп», плеер последней записи. Каждая запись сразу сохраняется
<out>/<квест>-<этап>[-m|-f].wav (моно, 48 кГц, без обработки браузера); повторная запись
заменяет файл. Записи — голос человека: в git не кладём (work/ в .gitignore).

  python -m voru.review.recording --voice satyr-male --out work/recordings/satyr-male
"""
import argparse
import html
import json
import os
import subprocess
import tempfile
import wave
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote

from voru.review import _STYLE

SAMPLE_RATE = 48000
MIN_PEAK_DBFS = -45.0  # тише — это не голос, а не тот микрофон / выключенный вход


@dataclass(frozen=True)
class RecordingItem:
    name: str  # имя файла без расширения
    title: str
    note: str
    spoken_text: str  # с «+» перед ударной гласной


def file_name(quest_id, stage: str, player_gender) -> str:
    return f"{quest_id}-{stage}" + (f"-{player_gender}" if player_gender else "")


def recording_items(corpus_paths, voice_id: str) -> list:
    from voru.pipeline import Report, plan

    items = []
    for p in plan(corpus_paths, "f5-tts-ru-v4", Report()):
        if p.voice_id != voice_id:
            continue
        gender = p.variant.player_gender
        items.append(RecordingItem(
            name=file_name(p.record.quest_id, p.record.stage, gender),
            title=f"Квест {p.record.quest_id} · {'взятие' if p.record.stage == 'accept' else 'сдача'}"
                  f" · {p.record.quest_title or ''}",
            note={"m": "игрок — мужчина", "f": "игрок — женщина"}.get(gender, ""),
            spoken_text=p.variant.spoken_text,
        ))
    return sorted(items, key=lambda i: i.name)


def _stressed_html(text: str) -> str:
    out, i = [], 0
    while i < len(text):
        if text[i] == "+" and i + 1 < len(text):
            out.append(f"<b>{html.escape(text[i + 1])}</b>")
            i += 2
        else:
            out.append(html.escape(text[i]).replace("\n", "<br>"))
            i += 1
    return "".join(out)


def _wav_seconds(path: Path) -> float:
    with wave.open(str(path)) as w:
        return w.getnframes() / w.getframerate()


def _to_wav(data: bytes, dst: Path):
    """Любой формат браузера (webm/ogg/wav) → WAV моно 48 кГц; атомарная замена. Брак → ValueError."""
    from voru.exporters.audio import ffmpeg_exe

    dst.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=dst.parent) as tmp:
        src, out = Path(tmp) / "upload", Path(tmp) / "out.wav"
        src.write_bytes(data)
        proc = subprocess.run([ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y", "-i", str(src),
                               "-vn", "-ac", "1", "-ar", str(SAMPLE_RATE), "-c:a", "pcm_s16le", str(out)],
                              capture_output=True)
        if proc.returncode != 0 or not out.exists() or _wav_seconds(out) <= 0:
            raise ValueError(proc.stderr.decode("utf-8", "replace")[-300:] or "пустая запись")
        peak = _peak_dbfs(out)
        if peak < MIN_PEAK_DBFS:
            raise ValueError(f"тишина (пик {peak:.0f} дБ): проверь, что выбран нужный микрофон и он включён")
        os.replace(out, dst)


def _peak_dbfs(path: Path) -> float:
    import array
    import math

    with wave.open(str(path)) as w:
        samples = array.array("h", w.readframes(w.getnframes()))
    peak = max((abs(s) for s in samples), default=0) / 32768
    return 20 * math.log10(peak) if peak else -120.0


_SCRIPT = """
const listEl = () => fetch("list").then(r => r.json());
let recorder = null, chunks = [], current = null, stream = null, analyser = null;
const MIC_KEY = "voru-mic";
async function openMic(deviceId) {
  if (stream) stream.getTracks().forEach(t => t.stop());
  stream = await navigator.mediaDevices.getUserMedia({ audio: {
    deviceId: deviceId ? { exact: deviceId } : undefined,
    channelCount: 1, echoCancellation: false, noiseSuppression: false, autoGainControl: false } });
  const ctx = new AudioContext(); analyser = ctx.createAnalyser(); analyser.fftSize = 2048;
  ctx.createMediaStreamSource(stream).connect(analyser);
  const select = document.getElementById("mic"), active = stream.getAudioTracks()[0].getSettings().deviceId;
  const devices = (await navigator.mediaDevices.enumerateDevices()).filter(d => d.kind === "audioinput");
  select.innerHTML = devices.map(d => `<option value="${d.deviceId}">${d.label || "микрофон"}</option>`).join("");
  select.value = active; try { localStorage.setItem(MIC_KEY, active); } catch (e) {}
}
function meter() {
  if (analyser) {
    const data = new Float32Array(analyser.fftSize); analyser.getFloatTimeDomainData(data);
    const peak = Math.max(...data.map(Math.abs)), db = peak > 0 ? 20 * Math.log10(peak) : -120;
    document.getElementById("level").value = Math.max(0, 60 + db);
    document.getElementById("db").textContent = db < -59 ? "тишина" : db.toFixed(0) + " дБ";
  }
  requestAnimationFrame(meter);
}
document.getElementById("mic").addEventListener("change", e => openMic(e.target.value));
document.getElementById("enable").addEventListener("click", () => {
  let saved = null; try { saved = localStorage.getItem(MIC_KEY); } catch (e) {}
  openMic(saved).catch(() => openMic(null)).catch(err => alertBox("микрофон: " + err));
});
function alertBox(text) { document.getElementById("db").textContent = text; }
meter();
function setState(card, text) { card.querySelector(".state").textContent = text; }
async function refresh() {
  const saved = await listEl();
  document.querySelectorAll(".card").forEach(card => {
    const info = saved[card.dataset.name], audio = card.querySelector("audio");
    if (info) { audio.src = "audio/" + card.dataset.name + ".wav?t=" + info.mtime; audio.hidden = false;
      setState(card, "записано, " + info.seconds.toFixed(1) + " с"); }
    else { audio.hidden = true; setState(card, "нет записи"); }
  });
  document.getElementById("progress").textContent =
    Object.keys(saved).length + " / " + document.querySelectorAll(".card").length;
}
async function start(card) {
  if (!stream) await openMic(null);
  recorder = new MediaRecorder(stream); chunks = []; current = card;
  recorder.ondataavailable = e => chunks.push(e.data);
  recorder.onstop = async () => {
    setState(card, "сохраняю…");
    const resp = await fetch("save/" + card.dataset.name, { method: "PUT", body: new Blob(chunks) });
    if (!resp.ok) setState(card, "ошибка: " + await resp.text()); else await refresh();
    document.querySelectorAll("button.rec").forEach(b => b.disabled = false);
    card.querySelector("button.rec").textContent = "Перезаписать"; recorder = null;
  };
  recorder.start();
  document.querySelectorAll("button.rec").forEach(b => b.disabled = b.closest(".card") !== card);
  card.querySelector("button.rec").textContent = "Стоп"; setState(card, "● идёт запись");
}
document.addEventListener("click", e => {
  const btn = e.target.closest("button.rec"); if (!btn) return;
  const card = btn.closest(".card");
  if (recorder && current === card) recorder.stop(); else if (!recorder) start(card).catch(err => setState(card, "микрофон: " + err));
});
refresh().then(() => document.querySelectorAll(".card").forEach(card => {
  if (!card.querySelector("audio").hidden) card.querySelector("button.rec").textContent = "Перезаписать"; }));
"""

_EXTRA_STYLE = """
.text { font-size: 19px; line-height: 1.7; }
.text b { color: var(--warn); }
.controls { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }
.state { color: var(--muted); }
button:disabled { opacity: .4; cursor: default; }
.bar { flex-wrap: wrap; }
#mic { max-width: 280px; background: var(--card); color: var(--fg); border: 1px solid var(--line); border-radius: 6px; padding: 6px; }
#level { width: 160px; }
"""


def _page(items, out_dir: Path) -> str:
    e = html.escape
    cards = "".join(
        f'<section class="card" data-name="{e(i.name)}"><header><b>{e(i.name)}</b> · {e(i.title)}'
        f'{" · " + e(i.note) if i.note else ""}</header><p class="text">{_stressed_html(i.spoken_text)}</p>'
        f'<div class="controls"><button class="rec">Записать</button><span class="state"></span>'
        f'<audio controls hidden></audio></div></section>' for i in items)
    return (f'<!doctype html><html lang="ru"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width, initial-scale=1"><title>Запись реплик</title>'
            f'<style>{_STYLE}{_EXTRA_STYLE}</style></head><body><main>'
            f'<div class="bar"><b>Запись реплик</b><span id="progress"></span>'
            f'<button id="enable">Включить микрофон</button><select id="mic"></select>'
            f'<meter id="level" min="0" max="60" low="15" high="54" optimum="40" value="0"></meter>'
            f'<span id="db"></span></div>'
            f'<p>Сначала «Включить микрофон», выбери устройство и скажи что-нибудь — полоска уровня должна '
            f'двигаться (речь ≈ −20…−6 дБ). Если стоит «тишина» — выбран не тот микрофон.</p>'
            f'<p>Ударные гласные выделены цветом. Читай слово в слово; паузы, смех и интонация — твои. '
            f'Запись сохраняется сразу в <code>{e(str(out_dir))}</code>, «Перезаписать» заменяет файл. '
            f'Обработка браузера (шумодав, автоусиление) выключена.</p>'
            f'{cards}</main><script>{_SCRIPT}</script></body></html>\n')


def make_server(items, out_dir, host: str = "127.0.0.1", port: int = 8765):
    out_dir = Path(out_dir)
    names = {i.name for i in items}
    page = _page(items, out_dir.resolve()).encode("utf-8")

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _send(self, code, body: bytes, ctype="text/plain; charset=utf-8"):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = unquote(self.path.split("?")[0])
            if path == "/":
                return self._send(200, page, "text/html; charset=utf-8")
            if path == "/list":
                saved = {n: {"seconds": round(_wav_seconds(out_dir / f"{n}.wav"), 2),
                             "mtime": int((out_dir / f"{n}.wav").stat().st_mtime)}
                         for n in sorted(names) if (out_dir / f"{n}.wav").exists()}
                return self._send(200, json.dumps(saved).encode("utf-8"), "application/json")
            if path.startswith("/audio/") and path.endswith(".wav") and path[7:-4] in names:
                file = out_dir / path[7:]
                if file.exists():
                    return self._send(200, file.read_bytes(), "audio/wav")
            self._send(404, "нет такого файла".encode("utf-8"))

        def do_PUT(self):
            path = unquote(self.path.split("?")[0])
            name = path[len("/save/"):] if path.startswith("/save/") else ""
            if name not in names:
                return self._send(404, f"нет такой реплики: {name}".encode("utf-8"))
            data = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            try:
                _to_wav(data, out_dir / f"{name}.wav")
            except ValueError as err:
                return self._send(400, f"запись не распознана: {err}".encode("utf-8"))
            self._send(200, b"ok")

    return ThreadingHTTPServer((host, port), Handler)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--voice", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--corpus", type=Path, action="append")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)

    from voru.pipeline import PILOT_CORPUS, SMOKE_CORPUS

    items = recording_items(args.corpus or [PILOT_CORPUS, SMOKE_CORPUS], args.voice)
    if not items:
        raise SystemExit(f"{args.voice}: нет реплик в корпусе")
    server = make_server(items, args.out, port=args.port)
    print(f"стенд записи: http://127.0.0.1:{server.server_address[1]}/ (реплик: {len(items)}; Ctrl+C — выход)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

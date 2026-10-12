"""Сводка очереди: python scripts/wsl/queue_report.py ~/voru-work [провайдер]

Показывает по провайдерам состояния, проблемные задания с причинами, длительность звука
и фактический RTF (по времени синтеза из результата задания).
"""
import collections
import json
import sqlite3
import sys

db = sqlite3.connect(f"{sys.argv[1]}/jobs.sqlite")
only = sys.argv[2] if len(sys.argv) > 2 else None
rows = db.execute("SELECT slot, state, attempts, last_error, result, payload FROM jobs").fetchall()
by_provider = collections.defaultdict(list)
for slot, state, attempts, error, result, payload in rows:
    provider = json.loads(payload)["provider"]
    if only and provider != only:
        continue
    by_provider[provider].append((slot, state, attempts, error, json.loads(result) if result else None))

for provider, jobs in sorted(by_provider.items()):
    states = collections.Counter(j[1] for j in jobs)
    done = [j[4] for j in jobs if j[4]]
    audio = sum(r["duration_ms"] for r in done) / 1000
    synth = sum(r["elapsed_s"] for r in done)
    rtf = f"{synth / audio:.2f}" if audio else "—"
    print(f"\n{provider}: {dict(states)} | звук {audio / 60:.1f} мин, синтез {synth / 60:.1f} мин, RTF {rtf}")
    for slot, state, attempts, error, _ in jobs:
        if state not in ("generated", "accepted") or attempts > 1:
            print(f"  {state:16} попыток {attempts}  {slot.split(':', 1)[1]}  {error or ''}")

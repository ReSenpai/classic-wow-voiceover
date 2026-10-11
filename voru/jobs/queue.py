"""Очередь заданий синтеза на SQLite (дизайн §9).

Задание = слот (одна выходная реплика: content_id + вариант пола) + fingerprint.
- Повторная постановка того же (слот, fingerprint) ничего не меняет — перезапуск не теряет
  и не переделывает работу.
- Новый fingerprint слота вытесняет (superseded) незавершённые старые задания; принятое
  остаётся опубликованным, пока не примут новое.
- Worker берёт задание в аренду (lease); просроченная аренда возвращает задание в очередь.
  Не больше MAX_ATTEMPTS попыток, затем failed — дальше решает человек.
Каждый поток/процесс открывает свой JobQueue: соединение SQLite нельзя делить между потоками.
"""
import json
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

MAX_ATTEMPTS = 3
DEFAULT_LEASE_S = 600
STATES = ("pending", "running", "generated", "qa_failed", "review_required", "accepted", "failed", "superseded")
_REPLACEABLE = ("pending", "failed", "generated", "qa_failed", "review_required")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    job_id INTEGER PRIMARY KEY AUTOINCREMENT,
    slot TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    payload TEXT NOT NULL,
    state TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    lease_owner TEXT,
    lease_expires REAL,
    last_error TEXT,
    result TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    UNIQUE (slot, fingerprint)
);
CREATE INDEX IF NOT EXISTS jobs_state ON jobs (state);
CREATE INDEX IF NOT EXISTS jobs_slot ON jobs (slot);
"""


class LeaseLost(RuntimeError):
    """Аренда задания истекла и перешла к другому worker'у — результат не принимается."""


@dataclass(frozen=True)
class Job:
    job_id: int
    slot: str
    fingerprint: str
    payload: dict
    state: str
    attempts: int
    lease_owner: Optional[str]
    lease_expires: Optional[float]
    last_error: Optional[str]
    result: Optional[dict]


def _job(row) -> Job:
    return Job(
        job_id=row["job_id"], slot=row["slot"], fingerprint=row["fingerprint"],
        payload=json.loads(row["payload"]), state=row["state"], attempts=row["attempts"],
        lease_owner=row["lease_owner"], lease_expires=row["lease_expires"], last_error=row["last_error"],
        result=json.loads(row["result"]) if row["result"] else None,
    )


class JobQueue:
    def __init__(self, path, clock=time.time):
        self.clock = clock
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), timeout=30, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        with self._tx() as db:
            for statement in filter(str.strip, _SCHEMA.split(";")):
                db.execute(statement)

    # --- транзакции ---

    class _Tx:
        def __init__(self, db):
            self.db = db

        def __enter__(self):
            self.db.execute("BEGIN IMMEDIATE")
            return self.db

        def __exit__(self, exc_type, *_):
            self.db.execute("ROLLBACK" if exc_type else "COMMIT")

    def _tx(self):
        return self._Tx(self.db)

    def _row(self, job_id):
        row = self.db.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        if row is None:
            raise KeyError(f"job {job_id} not found")
        return row

    def _update(self, job_id, **fields):
        fields["updated_at"] = self.clock()
        columns = ", ".join(f"{k} = ?" for k in fields)
        self.db.execute(f"UPDATE jobs SET {columns} WHERE job_id = ?", (*fields.values(), job_id))

    def _owned_running(self, job_id, worker):
        row = self._row(job_id)
        if row["state"] != "running" or row["lease_owner"] != worker:
            raise LeaseLost(f"job {job_id}: state {row['state']}, owner {row['lease_owner']}, not {worker}")
        return row

    # --- постановка ---

    def enqueue(self, slot: str, fingerprint: str, payload: dict) -> int:
        with self._tx() as db:
            row = db.execute("SELECT job_id, state FROM jobs WHERE slot = ? AND fingerprint = ?",
                             (slot, fingerprint)).fetchone()
            if row:
                job_id = row["job_id"]
                if row["state"] != "superseded":
                    return job_id
                self._update(job_id, state="pending", attempts=0, last_error=None, result=None)
            else:
                now = self.clock()
                job_id = db.execute(
                    "INSERT INTO jobs (slot, fingerprint, payload, state, created_at, updated_at) "
                    "VALUES (?, ?, ?, 'pending', ?, ?)",
                    (slot, fingerprint, json.dumps(payload, ensure_ascii=False, sort_keys=True), now, now),
                ).lastrowid
            db.execute(
                f"UPDATE jobs SET state = 'superseded', updated_at = ? WHERE slot = ? AND job_id != ? "
                f"AND state IN ({','.join('?' * len(_REPLACEABLE))})",
                (self.clock(), slot, job_id, *_REPLACEABLE),
            )
            return job_id

    # --- работа worker'а ---

    def claim(self, worker: str, lease_s: float = DEFAULT_LEASE_S, provider: Optional[str] = None) -> Optional[Job]:
        """provider — брать только задания этого TTS-провайдера (payload.provider)."""
        with self._tx() as db:
            while True:
                now = self.clock()
                row = db.execute(
                    "SELECT * FROM jobs WHERE (state = 'pending' OR (state = 'running' AND lease_expires < ?)) "
                    "AND (? IS NULL OR json_extract(payload, '$.provider') = ?) ORDER BY job_id LIMIT 1",
                    (now, provider, provider),
                ).fetchone()
                if row is None:
                    return None
                if row["state"] == "running" and row["attempts"] >= MAX_ATTEMPTS:
                    self._update(row["job_id"], state="failed", lease_owner=None, lease_expires=None,
                                 last_error=f"lease expired after {row['attempts']} attempts")
                    continue
                self._update(row["job_id"], state="running", lease_owner=worker,
                             lease_expires=now + lease_s, attempts=row["attempts"] + 1)
                return _job(self._row(row["job_id"]))

    def heartbeat(self, job_id: int, worker: str, lease_s: float = DEFAULT_LEASE_S):
        with self._tx():
            self._owned_running(job_id, worker)
            self._update(job_id, lease_expires=self.clock() + lease_s)

    def complete(self, job_id: int, worker: str, result: dict):
        with self._tx() as db:
            row = self._owned_running(job_id, worker)
            newer = db.execute("SELECT 1 FROM jobs WHERE slot = ? AND job_id > ?", (row["slot"], job_id)).fetchone()
            self._update(job_id, state="superseded" if newer else "generated", lease_owner=None,
                         lease_expires=None, last_error=None, result=json.dumps(result, ensure_ascii=False))

    def fail(self, job_id: int, worker: str, error: str, permanent: bool = False):
        with self._tx():
            row = self._owned_running(job_id, worker)
            final = permanent or row["attempts"] >= MAX_ATTEMPTS
            self._update(job_id, state="failed" if final else "pending", lease_owner=None,
                         lease_expires=None, last_error=error)

    # --- проверка и приёмка ---

    def set_qa_state(self, job_id: int, state: str, reason: str):
        if state not in ("qa_failed", "review_required"):
            raise ValueError(f"not a QA state: {state}")
        with self._tx():
            row = self._row(job_id)
            if row["state"] != "generated":
                raise ValueError(f"job {job_id} is {row['state']}, expected generated")
            self._update(job_id, state=state, last_error=reason)

    def accept(self, job_id: int):
        with self._tx() as db:
            row = self._row(job_id)
            if row["state"] not in ("generated", "review_required"):
                raise ValueError(f"job {job_id} is {row['state']}, cannot accept")
            db.execute("UPDATE jobs SET state = 'superseded', updated_at = ? "
                       "WHERE slot = ? AND state = 'accepted'", (self.clock(), row["slot"]))
            self._update(job_id, state="accepted")

    # --- чтение ---

    def get(self, job_id: int) -> Job:
        return _job(self._row(job_id))

    def jobs_for_slot(self, slot: str) -> list:
        rows = self.db.execute("SELECT * FROM jobs WHERE slot = ? ORDER BY job_id", (slot,)).fetchall()
        return [_job(r) for r in rows]

    def accepted(self, slot: str) -> Optional[Job]:
        row = self.db.execute("SELECT * FROM jobs WHERE slot = ? AND state = 'accepted'", (slot,)).fetchone()
        return _job(row) if row else None

    def summary(self) -> dict:
        rows = self.db.execute("SELECT state, COUNT(*) AS n FROM jobs GROUP BY state").fetchall()
        return {r["state"]: r["n"] for r in rows}

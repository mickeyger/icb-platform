"""Lightweight performance instrumentation for the costing flow.

Times the costing-critical requests (calculator page loads, /api/calculate,
trailer BOM fetches) and appends them to a JSON-lines file so the admin
Performance page can show where the time actually goes — cold-start worker
spawns vs. server compute vs. client render.

Design notes:
- Best-effort: instrumentation must NEVER raise into a real request.
- Each Passenger worker is its own process; the first requests a worker
  serves paid the spawn/import tax, so we record this worker's uptime and
  flag young-worker requests as "cold".
- All workers append to one shared file; reads take the tail.
"""
import json
import os
import time
import threading
from pathlib import Path

_LOG = Path(__file__).parent.parent / "logs" / "perf.jsonl"
_LOCK = threading.Lock()

# Per-worker process state — set once when this worker process imports the app.
_PROCESS_START = time.time()
_record_count  = 0   # this worker's append counter — drives periodic trimming

# Retention: perf records older than this are dropped automatically. This is a
# diagnostic log, not business data — a few days is a representative sample and
# keeps the file tiny. _HARD_CAP_LINES is a pathological-volume safety net.
_RETENTION_DAYS = 3
_TRIM_EVERY     = 50       # run the age-trim once per this many appended records
_HARD_CAP_LINES = 20000

# A request is treated as "cold" if the worker serving it was spawned within
# this many seconds — i.e. the user almost certainly waited for the spawn.
_COLD_WINDOW_S = 10.0


def worker_uptime() -> float:
    """Seconds since this worker process started."""
    return time.time() - _PROCESS_START


def is_cold() -> bool:
    """True if the current worker is young enough that a request now likely
    included the Passenger cold-start cost."""
    return worker_uptime() < _COLD_WINDOW_S


def _ensure_dir() -> None:
    try:
        _LOG.parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass


def _trim_old() -> None:
    """Drop records older than _RETENTION_DAYS. Called under _LOCK.

    The 'ts' field is a zero-padded 'YYYY-MM-DD HH:MM:SS' string, so a plain
    string comparison against the cutoff is also a correct chronological one."""
    try:
        if not _LOG.exists():
            return
        cutoff = time.strftime("%Y-%m-%d %H:%M:%S",
                               time.localtime(time.time() - _RETENTION_DAYS * 86400))
        orig = [ln for ln in _LOG.read_text(encoding="utf-8", errors="replace").splitlines()
                if ln.strip()]
        kept = []
        for ln in orig:
            try:
                ts = json.loads(ln).get("ts", "")
            except Exception:
                continue
            if ts >= cutoff:
                kept.append(ln)
        if len(kept) > _HARD_CAP_LINES:
            kept = kept[-_HARD_CAP_LINES:]
        if len(kept) != len(orig):
            _LOG.write_text(("\n".join(kept) + "\n") if kept else "", encoding="utf-8")
    except Exception:
        pass


def record(kind: str, path: str, duration_ms: float,
            cold: bool = False, extra: dict | None = None) -> None:
    """Append one timing record. Best-effort — swallows every error.

    kind: 'server' (measured by the request middleware) or
          'client' (reported by the calculator's beacon).
    """
    rec = {
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
        "kind": kind,
        "path": path,
        "duration_ms": round(float(duration_ms), 1),
        "cold": bool(cold),
        "worker_uptime_s": round(worker_uptime(), 1),
        "pid": os.getpid(),
    }
    if extra:
        rec.update(extra)
    global _record_count
    try:
        line = json.dumps(rec, separators=(",", ":"))
        _ensure_dir()
        with _LOCK:
            with open(_LOG, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
            _record_count += 1
            if _record_count == 1 or _record_count % _TRIM_EVERY == 0:
                _trim_old()
    except Exception:
        pass


def read_recent(limit: int = 200) -> list[dict]:
    """Return up to `limit` most-recent records, newest first."""
    try:
        if not _LOG.exists():
            return []
        lines = _LOG.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return []
    out: list[dict] = []
    for ln in lines[-limit:]:
        ln = ln.strip()
        if not ln:
            continue
        try:
            out.append(json.loads(ln))
        except Exception:
            continue
    out.reverse()
    return out

import json
import os
import queue
import re
import subprocess
import sys
import threading
from pathlib import Path

from fastapi import Request, APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import require_admin, _is_dev_mode
from ..templates_config import templates

router = APIRouter()

_ROOT = Path(__file__).parent.parent.parent  # project root


class _PreCheckState:
    def __init__(self):
        self._lock   = threading.Lock()
        self.running = False
        self._lines: list = []
        self._subs:  list = []

    def start(self):
        with self._lock:
            self.running = True
            self._lines  = []
            self._subs   = []

    def push(self, line: str):
        with self._lock:
            self._lines.append(line)
            for q in self._subs:
                q.put(line)

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue()
        with self._lock:
            for l in self._lines:
                q.put(l)
            self._subs.append(q)
        return q

    def finish(self):
        with self._lock:
            self.running = False
            for q in self._subs:
                q.put(None)


class _ReleaseState(_PreCheckState):
    pass


_pcs = _PreCheckState()
_rls = _ReleaseState()
_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def _run_precheck(skip_ssh: bool):
    try:
        cmd = [sys.executable, "-u", str(_ROOT / "tools" / "predeploy_check.py")]
        if skip_ssh:
            cmd.append("--skip-ssh")
        env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1", "PYTHONUNBUFFERED": "1"}
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", cwd=_ROOT, bufsize=1, env=env
        )
        for raw in proc.stdout:
            line = _ANSI.sub("", raw.rstrip())
            if line:
                _pcs.push(line)
        proc.wait()
        _pcs.push(f"__DONE__:{proc.returncode}")
    except Exception as ex:
        _pcs.push(f"ERROR: {ex}")
        _pcs.push("__DONE__:1")
    finally:
        _pcs.finish()


def _git(*args, cwd=None):
    result = subprocess.run(
        ["git", *args], capture_output=True, text=True,
        encoding="utf-8", errors="replace", cwd=cwd or _ROOT
    )
    return result.stdout.strip(), result.stderr.strip(), result.returncode


def _next_version() -> str:
    tags_out, _, _ = _git("tag", "--sort=-version:refname")
    tags = [t for t in tags_out.splitlines() if t.strip()]
    if not tags:
        return "v1.0"
    latest = tags[0]
    try:
        parts = latest.lstrip("v").split(".")
        major, minor = int(parts[0]), int(parts[1])
        return f"v{major}.{minor + 1}"
    except Exception:
        return "v1.0"


def _run_release(tag: str, note: str):
    push = _rls.push
    try:
        push(f"── Release {tag} ─────────────────────────────────────────")

        push("Writing VERSION file...")
        (_ROOT / "VERSION").write_text(tag, encoding="utf-8")
        push(f"  ✓ VERSION = {tag}")

        push("Staging any uncommitted changes...")
        _, err, rc = _git("add", "-A")
        if rc != 0:
            push(f"  ✗ git add failed: {err}"); _rls.push("__DONE__:1"); return

        diff_out, _, _ = _git("diff", "--cached", "--name-only")
        if diff_out.strip():
            push(f"  Committing: {len(diff_out.splitlines())} file(s)")
            _, err, rc = _git("commit", "-m", f"chore: pre-release tidy for {tag}\n\nCo-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>")
            if rc != 0:
                push(f"  ✗ Commit failed: {err}"); push("__DONE__:1"); return
            push("  ✓ Changes committed")
        else:
            push("  ✓ Working tree clean — nothing to commit")

        existing, _, _ = _git("tag", "--list", tag)
        if existing.strip():
            push(f"  ✗ Tag {tag} already exists — choose a different version"); push("__DONE__:1"); return

        push(f"Creating tag {tag}...")
        _, err, rc = _git("tag", "-a", tag, "-m", note or f"Release {tag}")
        if rc != 0:
            push(f"  ✗ Tag failed: {err}"); push("__DONE__:1"); return
        push(f"  ✓ Tag created: {tag}")

        push("Pushing to origin/main...")
        out, err, rc = _git("push", "origin", "main")
        if rc != 0:
            _git("tag", "-d", tag)
            push(f"  ✗ Push failed: {err or out}"); push("__DONE__:1"); return
        push("  ✓ Commits pushed to origin/main")

        push(f"Pushing tag {tag}...")
        out, err, rc = _git("push", "origin", tag)
        if rc != 0:
            push(f"  ⚠ Tag push failed (commits already pushed): {err or out}")
        else:
            push(f"  ✓ Tag {tag} pushed")

        push("")
        push(f"  ✓ Release {tag} complete — live at https://faje.co.za")
        push("  ✓ cPanel will auto-deploy from GitHub within ~60 seconds")
        push("__DONE__:0")
    except Exception as ex:
        push(f"ERROR: {ex}"); push("__DONE__:1")
    finally:
        _rls.finish()


def _redact_url(url: str) -> str:
    return re.sub(r"://([^:]+):([^@]+)@", r"://\1:***@", url)


@router.get("/admin/devtools", response_class=HTMLResponse)
async def devtools_page(request: Request, db: Session = Depends(get_db)):
    if not _is_dev_mode():
        raise HTTPException(status_code=403, detail="Dev Tools only available in local/dev mode.")
    user = require_admin(request, db)
    return templates.TemplateResponse("devtools.html", {"request": request, "user": user})


@router.post("/admin/devtools/run")
async def devtools_run(request: Request, db: Session = Depends(get_db)):
    if not _is_dev_mode():
        raise HTTPException(status_code=403)
    require_admin(request, db)
    if _pcs.running:
        _pcs.running = False
    body = await request.json()
    skip_ssh = body.get("skip_ssh", True)
    _pcs.start()
    threading.Thread(target=_run_precheck, args=(skip_ssh,), daemon=True).start()
    return JSONResponse({"ok": True})


@router.get("/admin/devtools/stream")
def devtools_stream(request: Request, db: Session = Depends(get_db)):
    if not _is_dev_mode():
        raise HTTPException(status_code=403)
    require_admin(request, db)
    q = _pcs.subscribe()

    def generate():
        while True:
            try:
                line = q.get(timeout=30)
                if line is None:
                    yield "data: __EOF__\n\n"
                    break
                yield f"data: {json.dumps(line)}\n\n"
            except queue.Empty:
                yield "data: __HEARTBEAT__\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/admin/devtools/schema-diff")
async def devtools_schema_diff(request: Request, db: Session = Depends(get_db)):
    if not _is_dev_mode():
        raise HTTPException(status_code=403)
    require_admin(request, db)

    body = await request.json()
    prod_url = (body.get("prod_database_url")
                or os.environ.get("PROD_DATABASE_URL")
                or os.environ.get("MYSQL_URL")
                or "").strip()
    if not prod_url:
        raise HTTPException(status_code=400,
            detail="No prod URL found. Paste one above, or set PROD_DATABASE_URL / MYSQL_URL in .env.")

    try:
        from sqlalchemy import create_engine, inspect
        from ..database import Base
        engine = create_engine(prod_url, connect_args={"connect_timeout": 10}
                               if prod_url.startswith("mysql") else {})
        insp = inspect(engine)
        prod_tables = set(insp.get_table_names())
    except Exception as e:
        return JSONResponse(status_code=502,
            content={"error": True, "detail": f"Could not connect to prod DB: {type(e).__name__}: {e}"})

    expected = {t.name: t for t in Base.metadata.tables.values()}
    expected_tables = set(expected.keys())

    missing_tables = sorted(expected_tables - prod_tables)
    extra_tables   = sorted(prod_tables - expected_tables)

    table_diffs = []
    for tname in sorted(expected_tables & prod_tables):
        model_cols = {c.name: c for c in expected[tname].columns}
        prod_cols  = {c["name"]: c for c in insp.get_columns(tname)}

        missing_cols = sorted(set(model_cols.keys()) - set(prod_cols.keys()))
        extra_cols   = sorted(set(prod_cols.keys()) - set(model_cols.keys()))

        type_mismatches = []
        for cname in sorted(set(model_cols.keys()) & set(prod_cols.keys())):
            model_t = str(model_cols[cname].type).upper()
            prod_t  = str(prod_cols[cname]["type"]).upper()
            mt = model_t.split("(")[0].strip()
            pt = prod_t.split("(")[0].strip()
            equiv = {
                ("VARCHAR","TEXT"), ("TEXT","VARCHAR"),
                ("INTEGER","BIGINT"), ("BIGINT","INTEGER"),
                ("INTEGER","INT"), ("INT","INTEGER"),
                ("FLOAT","DOUBLE"), ("DOUBLE","FLOAT"),
                ("BOOLEAN","TINYINT"), ("TINYINT","BOOLEAN"),
                ("DATETIME","TIMESTAMP"), ("TIMESTAMP","DATETIME"),
            }
            if mt != pt and (mt, pt) not in equiv:
                type_mismatches.append({"column": cname, "model": model_t, "prod": prod_t})

        if missing_cols or extra_cols or type_mismatches:
            table_diffs.append({
                "table": tname,
                "missing_in_prod": missing_cols,
                "extra_in_prod":   extra_cols,
                "type_mismatches": type_mismatches,
            })

    in_sync = not (missing_tables or extra_tables or table_diffs)

    return {
        "in_sync": in_sync,
        "prod_url_redacted": _redact_url(prod_url),
        "missing_tables_in_prod": missing_tables,
        "extra_tables_in_prod":   extra_tables,
        "table_diffs": table_diffs,
        "summary": {
            "expected_tables": len(expected_tables),
            "prod_tables":     len(prod_tables),
            "tables_with_diffs": len(table_diffs),
        },
    }


@router.get("/admin/devtools/next-version")
async def devtools_next_version(request: Request, db: Session = Depends(get_db)):
    if not _is_dev_mode():
        raise HTTPException(status_code=403)
    require_admin(request, db)
    return JSONResponse({"version": _next_version()})


@router.post("/admin/devtools/release")
async def devtools_release(request: Request, db: Session = Depends(get_db)):
    if not _is_dev_mode():
        raise HTTPException(status_code=403)
    require_admin(request, db)
    if _rls.running:
        return JSONResponse({"error": "Release already in progress."}, status_code=409)
    body = await request.json()
    tag  = (body.get("tag") or "").strip()
    note = (body.get("note") or "").strip()
    if not tag:
        return JSONResponse({"error": "Version tag is required."}, status_code=400)
    if not re.match(r"^v\d+\.\d+$", tag):
        return JSONResponse({"error": "Tag must be in format vMAJOR.MINOR e.g. v1.1"}, status_code=400)
    _rls.start()
    threading.Thread(target=_run_release, args=(tag, note), daemon=True).start()
    return JSONResponse({"ok": True})


@router.get("/admin/devtools/release/stream")
def devtools_release_stream(request: Request, db: Session = Depends(get_db)):
    if not _is_dev_mode():
        raise HTTPException(status_code=403)
    require_admin(request, db)
    q = _rls.subscribe()

    def generate():
        while True:
            try:
                line = q.get(timeout=30)
                if line is None:
                    yield "data: __EOF__\n\n"
                    break
                yield f"data: {json.dumps(line)}\n\n"
            except queue.Empty:
                yield "data: __HEARTBEAT__\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

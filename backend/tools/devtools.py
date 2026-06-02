"""
IceCold GRP Costing System — Local Dev Tools Dashboard
=======================================================
Runs on localhost:8001 ONLY.  Never deployed to production.

Requirements:
    pip install flask          (auto-installed on first run)

Start:
    python tools/devtools.py
    — or double-click —
    tools/start_devtools.bat

Then open: http://localhost:8001
"""

import json
import queue
import re
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

# ── Windows UTF-8 fix ─────────────────────────────────────────────────────────
# Must be first — reconfigure stdout/stderr before any print() so box-drawing
# characters in the startup banner don't crash on Windows CP1252 consoles.
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass

ROOT    = Path(__file__).parent.parent
LOGFILE = Path(__file__).parent / "devtools.log"


def flog(msg: str):
    """Append a timestamped line to tools/devtools.log for post-mortem debugging."""
    import datetime
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with open(LOGFILE, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {msg}\n")
    except Exception:
        pass  # never crash on logging


flog("=" * 60)
flog("devtools.py starting up")

# ── Flask: auto-install if missing ────────────────────────────────────────────
try:
    from flask import Flask, Response, jsonify, request
except ImportError:
    print("\n  Flask not found — installing now...")
    subprocess.run([sys.executable, "-m", "pip", "install", "flask", "--quiet"], check=True)
    from flask import Flask, Response, jsonify, request

app = Flask(__name__)
flog("Flask app created")


# ══════════════════════════════════════════════════════════════════════════════
#  Operation State — thread-safe event broadcaster
# ══════════════════════════════════════════════════════════════════════════════

class OperationState:
    """
    Tracks a single running operation and broadcasts SSE events to all
    subscribers (browser tabs).  Late subscribers receive all past events
    so they don't miss output that arrived before they connected.
    """

    def __init__(self):
        self._lock = threading.RLock()   # RLock = reentrant, same thread can re-acquire
        self.running = False
        self._events: list = []
        self._subscribers: list = []

    def start(self):
        with self._lock:
            self.running = True
            self._events = []
            self._subscribers = []

    def emit(self, event: dict):
        with self._lock:
            self._events.append(event)
            for sub in self._subscribers:
                sub.put(event)

    def subscribe(self) -> queue.Queue:
        """Return a Queue pre-filled with all past events, plus future ones."""
        q: queue.Queue = queue.Queue()
        with self._lock:
            for evt in self._events:
                q.put(evt)
            self._subscribers.append(q)
        return q

    def finish(self):
        with self._lock:
            self.running = False
            for sub in self._subscribers:
                sub.put({"type": "eof"})


state = OperationState()


# ══════════════════════════════════════════════════════════════════════════════
#  Git helpers
# ══════════════════════════════════════════════════════════════════════════════

def git(*args):
    result = subprocess.run(
        ["git"] + list(args), capture_output=True, text=True, cwd=ROOT
    )
    return result.stdout.strip(), result.stderr.strip(), result.returncode


def get_tags():
    stdout, _, _ = git("tag", "--sort=-version:refname")
    return [t for t in stdout.splitlines() if t.strip()]


def suggest_next_version(tags):
    if not tags:
        return "v1.0"
    m = re.match(r"v(\d+)\.(\d+)", tags[0])
    if m:
        return f"v{m.group(1)}.{int(m.group(2)) + 1}"
    return "v1.0"


# ══════════════════════════════════════════════════════════════════════════════
#  Event emitter shortcuts
# ══════════════════════════════════════════════════════════════════════════════

def e_log(level, text):   state.emit({"type": "log",  "level": level, "text": text})
def e_ok(text):           e_log("ok",   text)
def e_fail(text):         e_log("fail", text)
def e_warn(text):         e_log("warn", text)
def e_info(text):         e_log("info", text)
def e_step(idx, status, label=""):
    state.emit({"type": "step", "idx": idx, "status": status, "label": label})
def e_done(success, message):
    state.emit({"type": "done", "success": success, "message": message})


# ══════════════════════════════════════════════════════════════════════════════
#  Subprocess streaming — runs a command and emits its output line-by-line
# ══════════════════════════════════════════════════════════════════════════════

_ANSI = re.compile(r"\x1b\[[0-9;]*m")

def stream_proc(cmd, cwd=ROOT) -> int:
    # Force UTF-8 output from child processes so Unicode chars (✓ ✗ ╔ ═ ╗)
    # don't crash on Windows consoles that default to CP1252.
    env = {**__import__("os").environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", cwd=cwd, bufsize=1, env=env
    )
    for raw in proc.stdout:
        line = _ANSI.sub("", raw.rstrip())
        if not line:
            continue
        if any(m in line for m in ["✓", " passed", "PASSED", "OK"]):
            e_ok(line)
        elif any(m in line for m in ["✗", "FAILED", " failed", " Error", " error"]):
            e_fail(line)
        elif any(m in line for m in ["⚠", " warn", "WARN"]):
            e_warn(line)
        else:
            e_info(line)
    proc.wait()
    return proc.returncode


# ══════════════════════════════════════════════════════════════════════════════
#  Operations  (run in background threads)
# ══════════════════════════════════════════════════════════════════════════════

# ── Pre-deploy check ──────────────────────────────────────────────────────────

def run_precheck(skip_ssh: bool):
    flog(f"run_precheck() thread started (skip_ssh={skip_ssh})")
    try:
        e_step(0, "running", "Pre-deploy checks")
        cmd = [sys.executable, str(ROOT / "tools" / "predeploy_check.py")]
        if skip_ssh:
            cmd.append("--skip-ssh")
        flog(f"  running: {' '.join(cmd)}")
        rc = stream_proc(cmd)
        flog(f"  predeploy_check.py exited with rc={rc}")
        if rc == 0:
            e_step(0, "done")
            e_done(True, "All pre-deploy checks passed — safe to release.")
        else:
            e_step(0, "fail")
            e_done(False, "Pre-deploy checks failed — fix the issues above before releasing.")
    except Exception as ex:
        flog(f"  EXCEPTION in run_precheck: {ex}")
        e_fail(f"Unexpected error: {ex}")
        e_done(False, str(ex))
    finally:
        flog("run_precheck() thread finished")
        state.finish()


# ── Release ───────────────────────────────────────────────────────────────────

def run_release(version: str, note: str, skip_ssh: bool):
    try:
        cfg = json.loads((ROOT / "deploy_config.json").read_text())
        live_url = cfg.get("live_url", "https://faje.co.za")

        # Step 0 — Pre-deploy checks ──────────────────────────────────────────
        e_step(0, "running", "Pre-deploy checks")
        cmd = [sys.executable, str(ROOT / "tools" / "predeploy_check.py")]
        if skip_ssh:
            cmd.append("--skip-ssh")
        if stream_proc(cmd) != 0:
            e_step(0, "fail")
            e_done(False, "Pre-deploy checks failed. Fix issues then retry.")
            return
        e_step(0, "done")

        # Step 1 — Tag & push ─────────────────────────────────────────────────
        e_step(1, "running", "Create & push tag")

        # Commit outstanding changes (if any)
        _, _, rc_diff        = git("diff",         "--quiet")
        _, _, rc_diff_cached = git("diff", "--cached", "--quiet")
        if rc_diff != 0 or rc_diff_cached != 0:
            git("add", "-A")
            _, stderr, rc = git(
                "commit", "-m",
                f"chore: pre-release tidy for {version}\n\n"
                "Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
            )
            e_ok("Committed outstanding changes.") if rc == 0 else e_warn(f"Commit: {stderr}")

        # Create annotated tag
        _, stderr, rc = git("tag", "-a", version, "-m", note)
        if rc != 0:
            e_fail(f"Tag creation failed: {stderr}")
            e_step(1, "fail")
            e_done(False, f"Could not create tag {version}: {stderr}")
            return
        e_ok(f"Tag created: {version}")

        # Push commits
        e_info("Pushing commits to origin/main...")
        _, stderr, rc = git("push", "origin", "main")
        if rc != 0:
            e_fail(f"Push failed: {stderr}")
            git("tag", "-d", version)
            e_warn(f"Tag {version} removed locally. Fix push issue and retry.")
            e_step(1, "fail")
            e_done(False, "Push to origin/main failed.")
            return
        e_ok("Commits pushed to origin/main")

        # Push tag
        _, stderr, rc = git("push", "origin", version)
        if rc != 0:
            e_warn(f"Tag push failed — run manually: git push origin {version}")
        else:
            e_ok(f"Tag {version} pushed")
        e_step(1, "done")

        # Step 2 — Wait ───────────────────────────────────────────────────────
        e_step(2, "running", "Waiting for server restart")
        for remaining in range(15, 0, -3):
            e_info(f"  Waiting... {remaining}s remaining")
            time.sleep(3)
        e_step(2, "done")

        # Step 3 — Smoke test ─────────────────────────────────────────────────
        e_step(3, "running", "Smoke test")
        e_info("Testing live site...")
        rc = stream_proc([sys.executable, str(ROOT / "tools" / "smoke_test.py")])
        if rc == 0:
            e_step(3, "done")
            e_done(True, f"Release {version} complete!  Live at {live_url}")
        else:
            e_step(3, "fail")
            e_done(False, f"Release {version} pushed but smoke test reported issues. Check {live_url}")

    except Exception as ex:
        e_fail(f"Unexpected error: {ex}")
        e_done(False, str(ex))
    finally:
        state.finish()


# ── Rollback ──────────────────────────────────────────────────────────────────

def run_rollback(target_tag: str):
    try:
        tags = get_tags()
        current_tag = tags[0] if tags else "unknown"

        # Step 0 — Validate ───────────────────────────────────────────────────
        e_step(0, "running", "Validate tag")
        if target_tag not in tags:
            e_fail(f"Tag '{target_tag}' not found in git.")
            e_step(0, "fail")
            e_done(False, f"Tag '{target_tag}' does not exist.")
            return
        e_ok(f"Tag validated: {target_tag}")
        e_info(f"Rolling back:  {current_tag}  →  {target_tag}")
        e_step(0, "done")

        # Step 1 — Checkout & commit ──────────────────────────────────────────
        e_step(1, "running", "Checkout & commit revert")
        _, stderr, rc = git("checkout", target_tag, "--", ".")
        if rc != 0:
            e_fail(f"Checkout failed: {stderr}")
            e_step(1, "fail")
            e_done(False, f"Could not checkout {target_tag}")
            return
        e_ok(f"Files restored from {target_tag}")

        git("add", "-A")
        commit_msg = (
            f"revert: rollback to {target_tag} from {current_tag}\n\n"
            f"Emergency rollback. Previous version was {current_tag}.\n"
            f"To re-apply: git revert HEAD then push.\n\n"
            f"Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
        )
        _, stderr, rc = git("commit", "-m", commit_msg)
        e_ok("Revert commit created") if rc == 0 else e_warn(f"Commit: {stderr}")
        e_step(1, "done")

        # Step 2 — Push ───────────────────────────────────────────────────────
        e_step(2, "running", "Push to origin")
        e_info("Pushing rollback to origin/main...")
        _, stderr, rc = git("push", "origin", "main")
        if rc != 0:
            e_fail(f"Push failed: {stderr}")
            e_step(2, "fail")
            e_done(False, "Push failed. Rollback commit is local only — run: git push origin main")
            return
        e_ok("Rollback pushed to origin/main")
        e_step(2, "done")

        # Step 3 — Wait ───────────────────────────────────────────────────────
        e_step(3, "running", "Waiting for server restart")
        for remaining in range(15, 0, -3):
            e_info(f"  Waiting... {remaining}s remaining")
            time.sleep(3)
        e_step(3, "done")

        # Step 4 — Smoke test ─────────────────────────────────────────────────
        e_step(4, "running", "Smoke test")
        e_info("Testing live site...")
        rc = stream_proc([sys.executable, str(ROOT / "tools" / "smoke_test.py")])
        if rc == 0:
            e_step(4, "done")
            e_done(True, f"Rollback to {target_tag} complete!")
        else:
            e_step(4, "fail")
            e_done(False, f"Rollback to {target_tag} pushed but smoke test reported issues.")

    except Exception as ex:
        e_fail(f"Unexpected error: {ex}")
        e_done(False, str(ex))
    finally:
        state.finish()


# ══════════════════════════════════════════════════════════════════════════════
#  Flask routes
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/")
def index():
    flog("GET / — serving dashboard HTML")
    return HTML


@app.route("/api/ping")
def api_ping():
    """Simple connectivity test — writes a file and returns JSON."""
    flog("GET /api/ping — ping received")
    ping_file = Path(__file__).parent / "ping_test.txt"
    try:
        import datetime
        ping_file.write_text(f"Ping OK at {datetime.datetime.now()}\n", encoding="utf-8")
        flog("  ping_test.txt written OK")
        return jsonify({"ok": True, "msg": "Server is reachable. ping_test.txt written to tools folder."})
    except Exception as ex:
        flog(f"  ping write failed: {ex}")
        return jsonify({"ok": False, "msg": str(ex)})


@app.route("/api/status")
def api_status():
    flog(f"GET /api/status — running={state.running}")
    tags = get_tags()
    try:
        cfg = json.loads((ROOT / "deploy_config.json").read_text())
        live_url = cfg.get("live_url", "https://faje.co.za")
    except Exception:
        live_url = "https://faje.co.za"
    return jsonify({
        "running":           state.running,
        "tags":              tags,
        "suggested_version": suggest_next_version(tags),
        "live_url":          live_url,
    })


@app.route("/api/run/precheck", methods=["POST"])
def api_run_precheck():
    flog("POST /api/run/precheck received")
    try:
        with state._lock:
            if state.running:
                flog("  REJECTED - already running")
                return jsonify({"error": "An operation is already running."}), 409
            # Inline state.start() - avoids re-entrant lock issue
            state.running = True
            state._events = []
            state._subscribers = []
        data = request.get_json(silent=True) or {}
        skip = data.get("skip_ssh", True)
        flog(f"  starting precheck (skip_ssh={skip})")
        threading.Thread(target=run_precheck, args=(skip,), daemon=True).start()
        return jsonify({"ok": True})
    except Exception as ex:
        flog(f"  EXCEPTION in api_run_precheck: {ex}")
        return jsonify({"error": str(ex)}), 500


@app.route("/api/run/release", methods=["POST"])
def api_run_release():
    with state._lock:
        if state.running:
            return jsonify({"error": "An operation is already running."}), 409
        state.start()
    data = request.get_json() or {}
    version = data.get("version", "").strip()
    if not re.match(r"^v\d+\.\d+$", version):
        with state._lock:
            state.running = False
        return jsonify({"error": f"Invalid version format: '{version}'. Use vMAJOR.MINOR"}), 400
    note = data.get("note", f"Release {version}").strip()
    threading.Thread(
        target=run_release, args=(version, note, data.get("skip_ssh", True)), daemon=True
    ).start()
    return jsonify({"ok": True})


@app.route("/api/run/rollback", methods=["POST"])
def api_run_rollback():
    with state._lock:
        if state.running:
            return jsonify({"error": "An operation is already running."}), 409
        state.start()
    data = request.get_json() or {}
    tag = data.get("tag", "").strip()
    if not tag:
        with state._lock:
            state.running = False
        return jsonify({"error": "No tag specified."}), 400
    threading.Thread(target=run_rollback, args=(tag,), daemon=True).start()
    return jsonify({"ok": True})


@app.route("/api/reset", methods=["POST"])
def api_reset():
    """Force-clear the running state (use if an operation got stuck)."""
    with state._lock:
        state.running = False
        state._events = []
        state._subscribers = []
    return jsonify({"ok": True})


@app.route("/api/stream")
def api_stream():
    """Server-Sent Events — streams all operation events to the browser."""
    q = state.subscribe()

    def generate():
        while True:
            try:
                event = q.get(timeout=30)
                yield f"data: {json.dumps(event)}\n\n"
                if event.get("type") in ("done", "eof"):
                    break
            except queue.Empty:
                # Heartbeat keeps the connection alive during long waits
                yield 'data: {"type":"heartbeat"}\n\n'

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ══════════════════════════════════════════════════════════════════════════════
#  Embedded HTML/CSS/JS  (single-file — no templates directory needed)
# ══════════════════════════════════════════════════════════════════════════════

HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>IceCold GRP — Dev Tools</title>
<style>
:root {
  --bg:       #0d0f1a;
  --surface:  #151929;
  --surface2: #1c2135;
  --border:   #252d45;
  --text:     #e2e8f0;
  --muted:    #64748b;
  --accent:   #3b82f6;
  --green:    #22c55e;
  --red:      #ef4444;
  --amber:    #f59e0b;
  --radius:   10px;
}
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
body {
  background: var(--bg);
  color: var(--text);
  font-family: system-ui, -apple-system, sans-serif;
  font-size: 14px;
  min-height: 100vh;
}

/* ── Header ──────────────────────────────────────────────────── */
.header {
  background: var(--surface);
  border-bottom: 1px solid var(--border);
  padding: 14px 28px;
  display: flex;
  align-items: center;
  gap: 14px;
}
.header-icon { font-size: 22px; }
.header-title { font-size: 17px; font-weight: 700; letter-spacing: -0.01em; }
.header-sub { font-size: 12px; color: var(--muted); margin-top: 1px; }
.header-badge {
  margin-left: auto;
  background: rgba(239,68,68,.12);
  border: 1px solid rgba(239,68,68,.35);
  color: #fca5a5;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: .08em;
  padding: 4px 10px;
  border-radius: 20px;
  text-transform: uppercase;
}
.live-link {
  font-size: 12px;
  color: var(--accent);
  text-decoration: none;
  display: flex;
  align-items: center;
  gap: 4px;
}
.live-link:hover { text-decoration: underline; }

/* ── Server status pill ──────────────────────────────────────── */
.server-pill {
  display: flex;
  align-items: center;
  gap: 7px;
  font-size: 12px;
  font-weight: 600;
  padding: 5px 12px;
  border-radius: 20px;
  border: 1px solid var(--border);
  background: var(--surface2);
  color: var(--muted);
  transition: all .3s;
}
.server-pill.ok     { color: #86efac; border-color: rgba(34,197,94,.4);  background: rgba(34,197,94,.07); }
.server-pill.error  { color: #fca5a5; border-color: rgba(239,68,68,.4);  background: rgba(239,68,68,.07); }
.server-pill-dot {
  width: 7px; height: 7px; border-radius: 50%;
  background: currentColor;
}
.server-pill.ok .server-pill-dot { animation: pulse 2s infinite; }

/* ── Inline error banner ─────────────────────────────────────── */
.inline-error {
  display: none;
  background: rgba(239,68,68,.1);
  border: 1px solid rgba(239,68,68,.35);
  color: #fca5a5;
  font-size: 12px;
  border-radius: 6px;
  padding: 9px 13px;
  margin-bottom: 10px;
  line-height: 1.5;
}
.inline-error.visible { display: block; }

/* ── Main layout ─────────────────────────────────────────────── */
.main { max-width: 1000px; margin: 0 auto; padding: 28px 24px; }

/* ── Cards ───────────────────────────────────────────────────── */
.card-row { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 16px; margin-bottom: 20px; }
.card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 22px;
  display: flex;
  flex-direction: column;
  gap: 0;
}
.card-title {
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: .09em;
  color: var(--muted);
  margin-bottom: 14px;
}
.card-desc { font-size: 12px; color: var(--muted); margin-bottom: 14px; line-height: 1.5; }

/* ── Form elements ───────────────────────────────────────────── */
label { display: block; font-size: 12px; color: var(--muted); margin-bottom: 5px; }
input[type="text"], select, input[type="password"] {
  width: 100%;
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 6px;
  color: var(--text);
  padding: 8px 11px;
  font-size: 13px;
  margin-bottom: 13px;
  outline: none;
  transition: border-color .15s;
  font-family: inherit;
}
input[type="text"]:focus, select:focus { border-color: var(--accent); }
select option { background: var(--surface); }
.cb-row {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: var(--muted);
  cursor: pointer;
  margin-bottom: 16px;
  user-select: none;
}
input[type="checkbox"] { accent-color: var(--accent); width: 14px; height: 14px; cursor: pointer; }

/* ── Buttons ─────────────────────────────────────────────────── */
.btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 7px;
  padding: 9px 18px;
  border-radius: 7px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  border: none;
  transition: background .15s, opacity .15s;
  width: 100%;
  margin-top: auto;
  font-family: inherit;
}
.btn-primary { background: var(--accent); color: #fff; }
.btn-primary:hover:not(:disabled) { background: #2563eb; }
.btn-danger  { background: #b91c1c; color: #fff; }
.btn-danger:hover:not(:disabled)  { background: #991b1b; }
.btn-ghost   { background: transparent; border: 1px solid var(--border); color: var(--muted); }
.btn-ghost:hover:not(:disabled)   { background: var(--border); color: var(--text); }
.btn:disabled { opacity: .35; cursor: not-allowed; }

/* ── Progress section ────────────────────────────────────────── */
.progress-section {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 22px;
  margin-bottom: 16px;
  display: none;
}
.progress-section.visible { display: block; }
.progress-op-label {
  font-size: 13px;
  font-weight: 600;
  color: var(--text);
  margin-bottom: 18px;
  display: flex;
  align-items: center;
  gap: 8px;
}
.steps { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 18px; }
.step {
  display: flex;
  align-items: center;
  gap: 7px;
  font-size: 12px;
  color: var(--muted);
  background: var(--surface2);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 6px 12px;
  transition: all .2s;
}
.step.running { color: var(--accent); border-color: rgba(59,130,246,.4); background: rgba(59,130,246,.07); }
.step.done    { color: var(--green);  border-color: rgba(34,197,94,.4);  background: rgba(34,197,94,.07); }
.step.fail    { color: var(--red);    border-color: rgba(239,68,68,.4);  background: rgba(239,68,68,.07); }
.step-icon { font-size: 13px; }
@keyframes spin { to { transform: rotate(360deg); } }
@keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.4} }
.step.running .step-icon { animation: pulse 1.2s infinite; }

/* progress bar */
.progress-bar-wrap {
  background: var(--bg);
  border-radius: 99px;
  height: 5px;
  overflow: hidden;
  margin-bottom: 0;
}
.progress-bar-fill {
  height: 100%;
  background: var(--accent);
  border-radius: 99px;
  width: 0%;
  transition: width .4s ease, background .3s;
}
.progress-bar-fill.success { background: var(--green); }
.progress-bar-fill.error   { background: var(--red); }

/* result banner */
.result-banner {
  margin-top: 16px;
  padding: 12px 16px;
  border-radius: 7px;
  font-size: 13px;
  font-weight: 600;
  display: none;
  line-height: 1.5;
}
.result-banner.success { background: rgba(34,197,94,.1);  border: 1px solid rgba(34,197,94,.3);  color: #86efac; }
.result-banner.error   { background: rgba(239,68,68,.1);  border: 1px solid rgba(239,68,68,.3);  color: #fca5a5; }

/* ── Log terminal ────────────────────────────────────────────── */
.log-section {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  overflow: hidden;
}
.log-header {
  padding: 10px 18px;
  border-bottom: 1px solid var(--border);
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.log-header-left {
  display: flex;
  align-items: center;
  gap: 10px;
}
.log-header-title {
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: .09em;
  color: var(--muted);
}
.log-status-dot {
  width: 7px; height: 7px;
  border-radius: 50%;
  background: var(--muted);
}
.log-status-dot.live { background: var(--green); animation: pulse 1.5s infinite; }
.log-actions { display: flex; gap: 8px; }
.btn-sm {
  padding: 5px 12px;
  font-size: 11px;
  font-weight: 600;
  border-radius: 5px;
  cursor: pointer;
  border: 1px solid var(--border);
  background: transparent;
  color: var(--muted);
  transition: all .15s;
  font-family: inherit;
}
.btn-sm:hover { background: var(--border); color: var(--text); }
.btn-sm.copied { color: var(--green); border-color: rgba(34,197,94,.4); }
.log-box {
  background: #080a12;
  font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
  font-size: 12px;
  line-height: 1.65;
  padding: 14px 18px;
  height: 380px;
  overflow-y: auto;
  white-space: pre-wrap;
  word-break: break-word;
}
.log-line { margin: 0; padding: 0; }
.log-ok   { color: #86efac; }
.log-fail { color: #fca5a5; }
.log-warn { color: #fcd34d; }
.log-info { color: #94a3b8; }
.log-empty { color: var(--muted); text-align: center; padding: 70px 0; font-family: system-ui; }

/* ── Responsive ──────────────────────────────────────────────── */
@media (max-width: 700px) {
  .card-row { grid-template-columns: 1fr; }
}
</style>
</head>
<body>

<!-- ── Header ──────────────────────────────────────────────────────── -->
<div class="header">
  <div class="header-icon">🧊</div>
  <div>
    <div class="header-title">IceCold GRP — Dev Tools</div>
    <div class="header-sub">Local deployment dashboard &nbsp;·&nbsp; localhost:8001</div>
  </div>
  <a class="live-link" id="live-link" href="https://faje.co.za" target="_blank">
    ↗ Live site
  </a>
  <div id="server-pill" class="server-pill" title="Devtools server connection status">
    <span class="server-pill-dot"></span>
    <span id="server-pill-text">Connecting…</span>
  </div>
  <button onclick="testPing()" style="background:none;border:1px solid var(--border);color:var(--muted);border-radius:6px;padding:4px 11px;font-size:11px;cursor:pointer;font-family:inherit" title="Write ping_test.txt to confirm server is reachable">🔌 Test Connection</button>
  <div class="header-badge">DEV ONLY</div>
</div>
<div id="ping-banner" style="display:none;background:rgba(59,130,246,.1);border-bottom:1px solid rgba(59,130,246,.3);color:#93c5fd;font-size:12px;padding:8px 28px">
  <span id="ping-msg"></span>
</div>

<!-- ── Main ────────────────────────────────────────────────────────── -->
<div class="main">

  <!-- Operation cards -->
  <div class="card-row">

    <!-- Pre-check -->
    <div class="card">
      <div class="card-title">Pre-Deploy Check</div>
      <div class="card-desc">
        Verify git status, secrets, dependencies, and server config before releasing.
      </div>
      <div class="inline-error" id="precheck-error"></div>
      <label class="cb-row">
        <input type="checkbox" id="precheck-skip-ssh" checked>
        Skip SSH server checks
      </label>
      <button class="btn btn-ghost" id="btn-precheck" onclick="runPrecheck()">
        ▶&nbsp; Run Check
      </button>
    </div>

    <!-- Release -->
    <div class="card">
      <div class="card-title">Release</div>
      <label for="release-version">Version tag</label>
      <input type="text" id="release-version" placeholder="v1.1" autocomplete="off" />
      <label for="release-note">Release note</label>
      <input type="text" id="release-note" placeholder="Brief description of changes" autocomplete="off" />
      <label class="cb-row">
        <input type="checkbox" id="release-skip-ssh" checked>
        Skip SSH server checks
      </label>
      <div class="inline-error" id="release-error"></div>
      <button class="btn btn-primary" id="btn-release" onclick="runRelease()">
        🚀&nbsp; Release
      </button>
    </div>

    <!-- Rollback -->
    <div class="card">
      <div class="card-title">Rollback</div>
      <div class="card-desc">
        Revert production to a previous tagged version.<br>
        The database is <strong>not</strong> affected.
      </div>
      <label for="rollback-tag">Roll back to</label>
      <select id="rollback-tag" onchange="updateRollbackInfo()">
        <option value="">Loading tags…</option>
      </select>
      <div id="rollback-info" style="font-size:11px;color:var(--muted);margin-top:-8px;margin-bottom:14px;"></div>
      <div class="inline-error" id="rollback-error"></div>
      <button class="btn btn-danger" id="btn-rollback" onclick="runRollback()">
        ↩&nbsp; Rollback
      </button>
    </div>

  </div>

  <!-- Progress tracker -->
  <div class="progress-section" id="progress-section">
    <div class="progress-op-label" style="justify-content:space-between">
      <span id="progress-op-text">Running…</span>
      <button class="btn-sm" onclick="resetState()" title="Force-reset if operation appears stuck" style="font-size:10px;opacity:.6">✕ Reset</button>
    </div>
    <div class="steps" id="steps-container"></div>
    <div class="progress-bar-wrap">
      <div class="progress-bar-fill" id="progress-bar"></div>
    </div>
    <div class="result-banner" id="result-banner"></div>
  </div>

  <!-- Log terminal -->
  <div class="log-section">
    <div class="log-header">
      <div class="log-header-left">
        <div class="log-status-dot" id="log-dot"></div>
        <span class="log-header-title">Live Log</span>
      </div>
      <div class="log-actions">
        <button class="btn-sm" onclick="clearLog()">Clear</button>
        <button class="btn-sm" id="btn-copy" onclick="copyLog()">Copy Log</button>
      </div>
    </div>
    <div class="log-box" id="log-box">
      <div class="log-empty">No operation running — output will appear here.</div>
    </div>
  </div>

</div><!-- /main -->

<script>
// ── State ──────────────────────────────────────────────────────────
let logLines    = [];
let stepDefs    = [];
let stepStatus  = {};
let totalTags   = [];
let sse         = null;
let serverAlive = false;

// ── Init ───────────────────────────────────────────────────────────
window.addEventListener('DOMContentLoaded', () => {
  loadStatus();
  // Poll server status every 5s so the pill stays accurate
  setInterval(pingServer, 5000);
});

function setServerPill(alive, extra) {
  serverAlive = alive;
  const pill = document.getElementById('server-pill');
  const text = document.getElementById('server-pill-text');
  pill.className = 'server-pill ' + (alive ? 'ok' : 'error');
  text.textContent = alive ? ('Server running' + (extra ? ' · ' + extra : '')) : 'Server offline — restart start_devtools.bat';
}

async function pingServer() {
  try {
    const r = await fetch('/api/status', { cache: 'no-store' });
    if (r.ok) {
      const d = await r.json();
      setServerPill(true, d.running ? 'operation running' : '');
      if (d.running) setButtonsDisabled(true);
    } else {
      setServerPill(false);
    }
  } catch(e) {
    setServerPill(false);
  }
}

async function loadStatus() {
  try {
    const r = await fetch('/api/status', { cache: 'no-store' });
    if (!r.ok) { setServerPill(false); return; }
    const d = await r.json();

    setServerPill(true, d.running ? 'operation running' : '');

    // Live link
    if (d.live_url) {
      const a = document.getElementById('live-link');
      a.href = d.live_url;
      a.textContent = '↗ ' + d.live_url.replace('https://', '');
    }

    // Release version suggestion
    document.getElementById('release-version').value = d.suggested_version || 'v1.0';

    // Rollback dropdown
    totalTags = d.tags || [];
    const sel = document.getElementById('rollback-tag');
    if (totalTags.length > 0) {
      sel.innerHTML = totalTags.map((t, i) =>
        `<option value="${t}">${t}${i === 0 ? '  (current)' : ''}</option>`
      ).join('');
      if (totalTags.length > 1) sel.value = totalTags[1];
    } else {
      sel.innerHTML = '<option value="">No tags found</option>';
    }
    updateRollbackInfo();

    if (d.running) setButtonsDisabled(true);
  } catch(e) {
    setServerPill(false);
    console.error('loadStatus failed', e);
  }
}

function updateRollbackInfo() {
  const sel = document.getElementById('rollback-tag');
  const cur = totalTags[0] || '?';
  const info = document.getElementById('rollback-info');
  if (sel.value && sel.value !== cur) {
    info.textContent = `Current: ${cur}  →  will roll back to: ${sel.value}`;
  } else if (sel.value === cur) {
    info.textContent = 'This is already the current version.';
  } else {
    info.textContent = '';
  }
}

// ── Inline error helpers ───────────────────────────────────────────
function showError(id, msg) {
  const el = document.getElementById(id);
  if (!el) return;
  el.textContent = msg;
  el.classList.add('visible');
}
function clearError(id) {
  const el = document.getElementById(id);
  if (el) { el.textContent = ''; el.classList.remove('visible'); }
}

// ── Run operations ─────────────────────────────────────────────────
async function runPrecheck() {
  clearError('precheck-error');
  if (!serverAlive) {
    showError('precheck-error', '✗ Cannot connect to devtools server. Make sure start_devtools.bat is running, then reload this page.');
    return;
  }
  const skipSSH = document.getElementById('precheck-skip-ssh').checked;
  const started = await startOp(
    '/api/run/precheck',
    { skip_ssh: skipSSH },
    ['Pre-deploy checks'],
    'Pre-Deploy Check',
    'precheck-error'
  );
  if (started) listenSSE();
}

async function runRelease() {
  clearError('release-error');
  if (!serverAlive) {
    showError('release-error', '✗ Cannot connect to devtools server. Make sure start_devtools.bat is running, then reload this page.');
    return;
  }
  const version = document.getElementById('release-version').value.trim();
  const note    = document.getElementById('release-note').value.trim() || `Release ${version}`;
  const skipSSH = document.getElementById('release-skip-ssh').checked;

  if (!/^v\\d+\\.\\d+$/.test(version)) {
    showError('release-error', `✗ Invalid version format: "${version}" — use v1.0, v1.1, v2.0 etc.`);
    return;
  }
  if (!confirm(`Release ${version} to production?\n\nNote: "${note}"\n\nThis will push to GitHub and deploy live.`)) return;

  const started = await startOp(
    '/api/run/release',
    { version, note, skip_ssh: skipSSH },
    ['Pre-deploy checks', 'Create & push tag', 'Wait for server restart', 'Smoke test'],
    `Release ${version}`,
    'release-error'
  );
  if (started) listenSSE();
}

async function runRollback() {
  clearError('rollback-error');
  if (!serverAlive) {
    showError('rollback-error', '✗ Cannot connect to devtools server. Make sure start_devtools.bat is running, then reload this page.');
    return;
  }
  const tag = document.getElementById('rollback-tag').value;
  if (!tag) { showError('rollback-error', '✗ Please select a tag to roll back to.'); return; }
  if (!confirm(`Roll back production to ${tag}?\n\nAll app code will revert. The database is NOT affected.`)) return;

  const started = await startOp(
    '/api/run/rollback',
    { tag },
    ['Validate tag', 'Checkout & commit revert', 'Push to origin', 'Wait for server restart', 'Smoke test'],
    `Rollback  →  ${tag}`,
    'rollback-error'
  );
  if (started) listenSSE();
}

async function startOp(endpoint, body, steps, opLabel, errorId) {
  // Show spinner feedback while waiting for server response
  const btnMap = {'/api/run/precheck':'btn-precheck', '/api/run/release':'btn-release', '/api/run/rollback':'btn-rollback'};
  const btnEl = document.getElementById(btnMap[endpoint]);
  const origText = btnEl ? btnEl.innerHTML : '';
  if (btnEl) { btnEl.innerHTML = '⏳ Starting…'; btnEl.disabled = true; }

  try {
    const r = await fetch(endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    });
    const d = await r.json();
    if (!r.ok) {
      if (btnEl) { btnEl.innerHTML = origText; btnEl.disabled = false; }
      showError(errorId, '✗ ' + (d.error || 'Failed to start operation.'));
      return false;
    }

    clearLog();
    setupSteps(steps, opLabel);
    setButtonsDisabled(true);
    document.getElementById('log-dot').classList.add('live');
    return true;
  } catch(e) {
    if (btnEl) { btnEl.innerHTML = origText; btnEl.disabled = false; }
    showError(errorId, '✗ Could not reach devtools server — is start_devtools.bat running?');
    setServerPill(false);
    return false;
  }
}

// ── Connection ping test ───────────────────────────────────────────
async function testPing() {
  const banner = document.getElementById('ping-banner');
  const msg    = document.getElementById('ping-msg');
  banner.style.display = 'block';
  banner.style.background = 'rgba(59,130,246,.1)';
  banner.style.borderBottomColor = 'rgba(59,130,246,.3)';
  banner.style.color = '#93c5fd';
  msg.textContent = '⏳ Testing connection to server…';
  try {
    const r = await fetch('/api/ping', { cache: 'no-store' });
    const d = await r.json();
    if (d.ok) {
      banner.style.background = 'rgba(34,197,94,.1)';
      banner.style.borderBottomColor = 'rgba(34,197,94,.3)';
      banner.style.color = '#86efac';
      msg.textContent = '✓ ' + d.msg + '  —  Server IS reachable. If Run Check still fails, check tools/devtools.log for details.';
      setServerPill(true);
    } else {
      banner.style.background = 'rgba(239,68,68,.1)';
      banner.style.borderBottomColor = 'rgba(239,68,68,.3)';
      banner.style.color = '#fca5a5';
      msg.textContent = '✗ Server responded but ping failed: ' + d.msg;
    }
  } catch(e) {
    banner.style.background = 'rgba(239,68,68,.1)';
    banner.style.borderBottomColor = 'rgba(239,68,68,.3)';
    banner.style.color = '#fca5a5';
    msg.textContent = '✗ Cannot reach server at all. Make sure start_devtools.bat is running in a terminal window.';
    setServerPill(false);
  }
  setTimeout(() => { banner.style.display = 'none'; }, 8000);
}

// ── Reset stuck operation ──────────────────────────────────────────
function resetState() {
  if (sse) { sse.close(); sse = null; }
  document.getElementById('progress-section').classList.remove('visible');
  document.getElementById('log-dot').classList.remove('live');
  setButtonsDisabled(false);
  loadStatus();
}

// ── SSE listener ───────────────────────────────────────────────────
function listenSSE() {
  if (sse) sse.close();
  sse = new EventSource('/api/stream');

  sse.onmessage = (e) => {
    try { handleEvent(JSON.parse(e.data)); } catch(err) {}
  };
  sse.onerror = () => {
    appendLog('warn', '⚠ Connection interrupted — the operation may still be running.');
    sse.close();
  };
}

function handleEvent(msg) {
  switch (msg.type) {
    case 'log':  appendLog(msg.level, msg.text);         break;
    case 'step': updateStep(msg.idx, msg.status);        break;
    case 'done': handleDone(msg.success, msg.message);   break;
  }
}

// ── Log ────────────────────────────────────────────────────────────
function appendLog(level, text) {
  logLines.push({ level, text });
  const box = document.getElementById('log-box');
  const empty = box.querySelector('.log-empty');
  if (empty) empty.remove();

  const p = document.createElement('p');
  p.className = `log-line log-${level}`;
  const pfx = { ok:'✓ ', fail:'✗ ', warn:'⚠ ', info:'  ' }[level] || '  ';
  p.textContent = pfx + text;
  box.appendChild(p);
  box.scrollTop = box.scrollHeight;
}

function clearLog() {
  logLines = [];
  document.getElementById('log-box').innerHTML =
    '<div class="log-empty">No operation running — output will appear here.</div>';
}

function copyLog() {
  const text = logLines.map(l => {
    const pfx = { ok:'✓ ', fail:'✗ ', warn:'⚠ ', info:'  ' }[l.level] || '  ';
    return pfx + l.text;
  }).join('\n');
  if (!text) { alert('Nothing in the log to copy.'); return; }
  navigator.clipboard.writeText(text).then(() => {
    const btn = document.getElementById('btn-copy');
    btn.textContent = 'Copied!';
    btn.classList.add('copied');
    setTimeout(() => { btn.textContent = 'Copy Log'; btn.classList.remove('copied'); }, 2000);
  });
}

// ── Progress steps ─────────────────────────────────────────────────
function setupSteps(steps, opLabel) {
  stepDefs   = steps;
  stepStatus = {};
  const section = document.getElementById('progress-section');
  section.classList.add('visible');
  document.getElementById('progress-op-text').textContent = opLabel;

  document.getElementById('steps-container').innerHTML = steps.map((label, i) =>
    `<div class="step pending" id="step-${i}">
       <span class="step-icon">○</span>
       <span>${label}</span>
     </div>`
  ).join('');

  const bar = document.getElementById('progress-bar');
  bar.style.width = '0%';
  bar.className = 'progress-bar-fill';

  const banner = document.getElementById('result-banner');
  banner.style.display = 'none';
  banner.className = 'result-banner';
}

const ICONS = { pending:'○', running:'●', done:'✓', fail:'✗' };

function updateStep(idx, status) {
  stepStatus[idx] = status;
  const el = document.getElementById(`step-${idx}`);
  if (!el) return;
  el.className = `step ${status}`;
  el.querySelector('.step-icon').textContent = ICONS[status] || '○';

  // Update progress bar width
  const doneCount = Object.values(stepStatus).filter(s => s === 'done').length;
  const pct = stepDefs.length > 0 ? Math.round((doneCount / stepDefs.length) * 100) : 0;
  document.getElementById('progress-bar').style.width = pct + '%';
}

function handleDone(success, message) {
  if (sse) { sse.close(); sse = null; }
  document.getElementById('log-dot').classList.remove('live');

  const bar = document.getElementById('progress-bar');
  bar.style.width = '100%';
  bar.classList.add(success ? 'success' : 'error');

  const banner = document.getElementById('result-banner');
  banner.textContent = (success ? '✓  ' : '✗  ') + message;
  banner.className = 'result-banner ' + (success ? 'success' : 'error');
  banner.style.display = 'block';

  setButtonsDisabled(false);
  loadStatus(); // refresh tags after a release/rollback
}

function setButtonsDisabled(disabled) {
  ['btn-precheck', 'btn-release', 'btn-rollback'].forEach(id => {
    document.getElementById(id).disabled = disabled;
  });
}
</script>
</body>
</html>"""


# ══════════════════════════════════════════════════════════════════════════════
#  Entry point
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    flog("Starting Flask on http://127.0.0.1:8001")
    print()
    print("  ╔══════════════════════════════════════════════════╗")
    print("  ║   IceCold GRP — Dev Tools Dashboard             ║")
    print("  ║   http://localhost:8001                         ║")
    print("  ║   Press Ctrl+C to stop                         ║")
    print("  ╚══════════════════════════════════════════════════╝")
    print()
    print(f"  Diagnostic log: {LOGFILE}")
    print()
    webbrowser.open("http://localhost:8001")
    app.run(host="127.0.0.1", port=8001, debug=False, threaded=True)

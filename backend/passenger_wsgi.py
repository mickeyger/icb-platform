"""Passenger WSGI entry point for the faje.co.za cPanel deploy (WO v4.30 §3.2).

HostAfrica's cPanel hosting uses Phusion Passenger, which speaks **WSGI**. icb-platform's app
(``app.main:app``) is FastAPI = **ASGI**, so we bridge it to a WSGI callable named ``application`` via
``a2wsgi.ASGIMiddleware`` — mirroring the legacy GRP-Costing-System ``passenger_wsgi.py`` so behaviour is
preserved at cutover.

cPanel Python Setup (path (c) — Application root points at this file's directory):
  - Application root:         <…/icb-platform/backend>   (confirm the on-disk path on cutover day)
  - Application startup file:  passenger_wsgi.py
  - Application Entry point:   application
  - Python:                    3.11 (HostAfrica)         (also runs on 3.12+ locally)

This file lives at ``backend/`` so ``BASE_DIR`` == the backend package root: ``app`` and ``.env`` resolve
from here, matching ``app/config.py`` (which loads ``backend/.env``). It is NOT used by the local uvicorn
dev server or by CI's test run — only the cPanel deploy imports it. See docs/runbooks/faje-deploy.md.
"""
import logging
import os
import sys

# backend/ is the import + working root: app/ and .env live here.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
os.environ["PYTHONPATH"] = BASE_DIR + os.pathsep + os.environ.get("PYTHONPATH", "")
os.chdir(BASE_DIR)

# Passenger swallows stdout; capture startup state + failures to files (mirrors the legacy).
LOG_FILE = os.path.join(BASE_DIR, "passenger_errors.log")
logging.basicConfig(filename=LOG_FILE, level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("passenger_wsgi")
try:
    sys.stderr = open(os.path.join(BASE_DIR, "passenger_stderr.log"), "a")
except OSError:
    pass

try:
    logger.info("=== Passenger starting (icb-platform) ===")
    logger.info("Python: %s", sys.version)
    logger.info("BASE_DIR: %s", BASE_DIR)

    # Load backend/.env BEFORE importing app.main: app/config.py needs DATABASE_URL + SESSION_SECRET at
    # import time (config.py also loads it, but doing it here guarantees order under Passenger).
    from dotenv import load_dotenv
    load_dotenv(os.path.join(BASE_DIR, ".env"))
    logger.info(".env loaded")

    # Import the FastAPI (ASGI) app and wrap it as a WSGI callable for Passenger.
    from app.main import app as fastapi_app
    from a2wsgi import ASGIMiddleware
    application = ASGIMiddleware(fastapi_app)
    logger.info("WSGI application ready")

except Exception as exc:  # pragma: no cover - deploy-time guard
    logger.exception("FATAL: Passenger failed to start: %s", exc)
    _err = str(exc)

    # Minimal WSGI app that surfaces the startup error instead of a blank 500.
    def application(environ, start_response):  # noqa: F811
        start_response("500 Internal Server Error", [("Content-Type", "text/plain")])
        return [f"Passenger startup failed:\n{_err}".encode("utf-8")]

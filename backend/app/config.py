"""Central application configuration (WO v4.12 §3.6).

Every environment-variable read in the backend goes through ``settings`` defined
here — this is the ONE place that touches the environment. Two variables are
*required* and the app refuses to boot if either is missing:

    DATABASE_URL      e.g. postgresql+psycopg://icb_app:***@localhost:5433/icb
    SESSION_SECRET    cookie/session signing key

All other variables have safe local-dev defaults. See ``.env.example``.
"""
from pathlib import Path
from typing import Annotated, List

from dotenv import load_dotenv
from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# backend/.env lives one level up from backend/app/. Load it into os.environ too
# so any remaining legacy os.environ readers see the same values during Phase 1.
_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=_ENV_FILE)

# Default location of the built React SPA (frontend/dist at the repo root).
_FRONTEND_DIST = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE), env_file_encoding="utf-8", extra="ignore"
    )

    # ── Deployment ──
    DEPLOYMENT_MODE: str = "cloud"            # cloud | on_prem  (surfaces in the UI footer)
    APP_PORT: int = 8000

    # ── Database (REQUIRED — no default) ──
    DATABASE_URL: str                         # postgresql+psycopg://...

    # ── Auth ──
    AUTH_PROVIDER: str = "email_password"     # email_password | ldap (ldap = Phase 3)
    SESSION_SECRET: str                       # REQUIRED — fail fast if missing

    # ── Storage (Phase 3 expands this) ──
    FILE_STORE: str = "./local_files"

    # ── Outbound integrations ──
    SMTP_URL: str = ""                        # empty = no email sent (dev mode)
    SAP_ENABLED: bool = False
    SAP_BASE_URL: str = ""

    # ── Branch defaults ──
    DEFAULT_BRANCH_CODE: str = "JHB"

    # ── Feature flags (Phase 4+) ──
    FEATURE_NEW_CALCULATOR: bool = False

    # ── Frontend (React build served by FastAPI at /mes-app/) ──
    FRONTEND_DIST: str = str(_FRONTEND_DIST)

    # ── AI Help assistant (optional; floating Help button hidden if unset) ──
    ANTHROPIC_API_KEY: str = ""

    # ── Feedback Portal (WO v4.38; all optional — empty = that channel is skipped) ──
    ANTHROPIC_FEEDBACK_MODEL: str = ""   # optional classify-model override; falls back to Haiku
    FEEDBACK_NOTIFY_EMAIL: str = ""      # ticket emails land here (the BA); empty = no email sent
    FEEDBACK_NOTIFY_WHATSAPP: str = ""   # WhatsApp ping target e.g. whatsapp:+27…; empty = no ping
    FEEDBACK_SCREENSHOT_DIR: str = ""    # blob dir for screenshots; empty = <FILE_STORE>/feedback
    TWILIO_ACCOUNT_SID: str = ""
    TWILIO_AUTH_TOKEN: str = ""
    TWILIO_WHATSAPP_FROM: str = ""       # Twilio WhatsApp sender e.g. whatsapp:+1415…

    # ── CORS (accepts a JSON array or a comma-separated string in .env) ──
    ALLOWED_ORIGINS: Annotated[List[str], NoDecode] = [
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:4173",
        "http://127.0.0.1:4173",
    ]

    @field_validator("ALLOWED_ORIGINS", mode="before")
    @classmethod
    def _split_origins(cls, v):
        if isinstance(v, str):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v


settings = Settings()

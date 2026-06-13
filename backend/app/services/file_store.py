"""WO v4.28 §3.4 — chassis photo storage.

Local filesystem now: backend/uploads/chassis/{record_id}/{cycle}/{event_type}/{photo_id}-{filename}.
This module is the ONLY storage seam.

TODO(§5.3 / v4.31): swap to a file-store abstraction (e.g. S3 / MinIO) — replace the two functions
below with the abstraction's put/get; nothing else in the app touches the filesystem directly.
"""
import re
import shutil
from pathlib import Path

# app/services/file_store.py -> parents[2] = backend/
_UPLOADS_ROOT = Path(__file__).resolve().parents[2] / "uploads" / "chassis"


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", name or "file")[:120]


def save_chassis_photo(record_id: int, cycle: int, event_type: str, photo_id: int,
                       filename: str, fileobj) -> str:
    """Persist a photo's bytes; return the relative path stored in chassis_photos.file_path."""
    rel = Path(str(record_id)) / str(cycle) / str(event_type) / f"{photo_id}-{_safe(filename)}"
    dest = _UPLOADS_ROOT / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    with open(dest, "wb") as out:
        shutil.copyfileobj(fileobj, out)
    return str(rel).replace("\\", "/")


def chassis_photo_abspath(rel_path: str) -> Path:
    return _UPLOADS_ROOT / rel_path


# ── WO v4.33 §3.6 — Pre-Job Card PDF snapshots (same local-FS seam) ──────────
_PREJOB_ROOT = Path(__file__).resolve().parents[2] / "uploads" / "prejob"


def save_prejob_pdf(card_id: int, data: bytes) -> str:
    """Persist the records-copy PDF generated at Submit-for-Check (§0.11 — the email's
    attachment source). Overwrites on re-submit (latest content wins); returns the relative
    path stored in prejob_cards.pdf_file_id."""
    rel = Path(str(card_id)) / f"prejob-card-{card_id}.pdf"
    dest = _PREJOB_ROOT / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return str(rel).replace("\\", "/")


def prejob_pdf_abspath(rel_path: str) -> Path:
    return _PREJOB_ROOT / rel_path

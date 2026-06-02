"""Pluggable file-storage interface (WO v4.12).

Phase 1 defines the interface ONLY. Concrete implementations — a local network
share for on-prem, object storage (S3) for cloud — arrive in Phase 3, selected
by settings.FILE_STORE. The costing app's current file handling is unchanged in
Phase 1; this Protocol simply marks the seam for that future work.
"""
from __future__ import annotations

from typing import BinaryIO, Protocol, runtime_checkable


@runtime_checkable
class FileStore(Protocol):
    """Abstract store for binary assets (drawings, DXFs, photos, PDFs)."""

    def save(self, path: str, data: BinaryIO) -> str:
        """Persist ``data`` at ``path``; return the stored path/key."""
        ...

    def open(self, path: str) -> BinaryIO:
        """Open ``path`` for binary reading."""
        ...

    def exists(self, path: str) -> bool:
        ...

    def url(self, path: str) -> str:
        """Return a URL/UNC reference a client can use to fetch the file."""
        ...

    def delete(self, path: str) -> None:
        ...

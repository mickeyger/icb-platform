"""Storage interfaces.

Phase 1 ships the FileStore Protocol only. Phase 3 adds concrete
implementations (local network share / S3) selected by settings.FILE_STORE.
"""
from .base import FileStore  # noqa: F401

__all__ = ["FileStore"]

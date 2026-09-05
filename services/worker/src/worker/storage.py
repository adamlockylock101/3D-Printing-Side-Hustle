"""Upload storage.

Local disk, keyed by content hash. Deliberately simple for phases 0-2 where the worker runs on
one box; swapping in S3/R2 means replacing the three functions here. Content addressing means
re-uploading the same mesh reuses the analysis and the cached slice for free.
"""

from __future__ import annotations

import hashlib
import os
import shutil
from pathlib import Path

from .config import repo_root

ALLOWED_SUFFIXES = {".stl", ".3mf", ".obj", ".ply", ".off"}
MAX_UPLOAD_BYTES = 200 * 1024 * 1024


class UploadRejected(ValueError):
    pass


def upload_dir() -> Path:
    path = Path(os.environ.get("PRINTSHOP_UPLOAD_DIR") or (repo_root() / "uploads"))
    path.mkdir(parents=True, exist_ok=True)
    return path


def store(filename: str, data: bytes) -> tuple[str, Path]:
    """Save an uploaded mesh and return (upload_id, path). The id is the content hash."""
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise UploadRejected(
            f"{suffix or 'That file type'} is not supported. "
            f"Send one of: {', '.join(sorted(ALLOWED_SUFFIXES))}."
        )
    if len(data) > MAX_UPLOAD_BYTES:
        raise UploadRejected(
            f"That file is {len(data) / 1e6:.0f} MB, over the "
            f"{MAX_UPLOAD_BYTES / 1e6:.0f} MB limit."
        )
    if not data:
        raise UploadRejected("That file is empty.")

    digest = hashlib.sha256(data).hexdigest()[:32]
    upload_id = f"{digest}{suffix}"
    path = upload_dir() / upload_id
    if not path.exists():
        path.write_bytes(data)
    return upload_id, path


def resolve(upload_id: str) -> Path:
    """Look up a stored upload. Rejects anything that tries to escape the upload directory."""
    candidate = (upload_dir() / upload_id).resolve()
    if candidate.parent != upload_dir().resolve() or not candidate.exists():
        raise FileNotFoundError(f"No upload with id {upload_id!r}")
    return candidate


def purge(older_than_days: int) -> int:
    """Delete uploads past the retention window.

    Wire to a cron job; the window itself is docs/open-questions.md Q32.
    """
    import time

    cutoff = time.time() - older_than_days * 86400
    removed = 0
    for path in upload_dir().iterdir():
        if path.is_file() and path.stat().st_mtime < cutoff:
            path.unlink()
            removed += 1
        elif path.is_dir() and path.stat().st_mtime < cutoff:
            shutil.rmtree(path, ignore_errors=True)
            removed += 1
    return removed

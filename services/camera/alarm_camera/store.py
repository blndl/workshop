"""Snapshot storage with a retention limit."""

from __future__ import annotations

import hashlib
import os
import time
from pathlib import Path

DEFAULT_RETENTION_DAYS = 30  # CNIL guidance for video surveillance: one month at most


class SnapshotStore:
    def __init__(self, root: Path, retention_days: float = DEFAULT_RETENTION_DAYS):
        self.root = Path(root)
        self.retention = retention_days * 86400
        self.root.mkdir(parents=True, exist_ok=True)

    def save(self, jpeg: bytes, reason: str, ts: float) -> tuple[Path, str]:
        """Write the image; returns (path, sha256 hex)."""
        day = time.strftime("%Y-%m-%d", time.localtime(ts))
        stamp = time.strftime("%H%M%S", time.localtime(ts)) + f"_{int(ts * 1000) % 1000:03d}"
        folder = self.root / day
        folder.mkdir(exist_ok=True)
        path = folder / f"{stamp}_{reason}.jpg"
        n = 1
        while path.exists():
            path = folder / f"{stamp}_{reason}_{n}.jpg"
            n += 1
        tmp = path.with_suffix(".tmp")
        with tmp.open("wb") as f:
            f.write(jpeg)
            f.flush()
            os.fsync(f.fileno())
        tmp.rename(path)
        return path, hashlib.sha256(jpeg).hexdigest()

    def prune(self, now: float) -> list[Path]:
        """Delete snapshots older than the retention period."""
        removed = []
        for p in self.root.glob("*/*.jpg"):
            if now - p.stat().st_mtime > self.retention:
                p.unlink()
                removed.append(p)
        for d in self.root.iterdir():
            if d.is_dir() and not any(d.iterdir()):
                d.rmdir()
        return removed

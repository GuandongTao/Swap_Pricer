"""Run manifest: per-run audit record committed alongside outputs."""

from __future__ import annotations

import hashlib
import json
import subprocess
import uuid
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=Path(__file__).resolve().parent, stderr=subprocess.DEVNULL
        ).decode().strip()
    except Exception:
        return "unversioned"


def file_sha256(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass
class RunManifest:
    run_id: str
    val_date: date
    run_date: datetime
    git_sha: str
    trade_count: int = 0
    status: str = "started"
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    finished_at: datetime | None = None
    input_files: dict[str, str] = field(default_factory=dict)
    outputs: dict[str, str] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    timings: dict[str, float] = field(default_factory=dict)
    per_trade_timings: dict[str, float] = field(default_factory=dict)

    @staticmethod
    def new(val_date: date) -> "RunManifest":
        now = datetime.now(timezone.utc)
        return RunManifest(
            run_id=str(uuid.uuid4()),
            val_date=val_date,
            run_date=now,
            git_sha=_git_sha(),
        )

    def add_input(self, label: str, path: str | Path) -> None:
        p = Path(path)
        self.input_files[label] = file_sha256(p) if p.exists() else "missing"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["val_date"] = self.val_date.isoformat()
        d["run_date"] = self.run_date.isoformat()
        d["started_at"] = self.started_at.isoformat()
        d["finished_at"] = self.finished_at.isoformat() if self.finished_at else None
        return d

    def write(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2, default=str), encoding="utf-8")

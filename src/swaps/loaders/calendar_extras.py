"""Helpers to load extra-holiday lists for per-trade customized calendars.

Supported file formats:
  - .csv with a header column named 'date' (case-insensitive)
  - .txt with one ISO date per line (blank lines and '#' comments ignored)
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import pandas as pd


def load_extra_holidays(path: str | Path) -> list[date]:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Calendar extras file not found: {p}")

    if p.suffix.lower() in {".csv", ".xlsx", ".xls"}:
        if p.suffix.lower() == ".csv":
            df = pd.read_csv(p)
        else:
            df = pd.read_excel(p)
        cols = {c.lower(): c for c in df.columns}
        if "date" not in cols:
            raise ValueError(f"{p}: extras file needs a 'date' column")
        series = df[cols["date"]].dropna()
        return [_to_date(v) for v in series.tolist()]

    # plain text: one date per line
    out: list[date] = []
    for raw_line in p.read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        out.append(_to_date(line))
    return out


def _to_date(v: object) -> date:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    return datetime.strptime(str(v).strip(), "%Y-%m-%d").date()

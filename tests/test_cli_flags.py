"""CLI flag handling and exit codes for the single-date pricer script."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _load_main():
    """Load scripts/price_portfolio.py as a module (it isn't a package)."""
    spec = importlib.util.spec_from_file_location(
        "price_portfolio_script", ROOT / "scripts" / "price_portfolio.py"
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod.main


def test_bad_val_date_returns_2():
    main = _load_main()
    assert main(["--val-date", "not-a-date"]) == 2


def test_missing_required_arg_exits_2_via_argparse():
    main = _load_main()
    with pytest.raises(SystemExit) as ei:
        main([])  # missing --val-date -> argparse SystemExit(2)
    assert ei.value.code == 2


def test_pillar_dates_flag_routes_to_dated_loader_and_errors_on_missing_file(tmp_path):
    """With --pillar-dates pointing at an empty curves dir, the loader raises
    FileNotFoundError; the script catches it and returns 1 (hard failure)."""
    (tmp_path / "curves").mkdir()
    (tmp_path / "fixings").mkdir()
    (tmp_path / "trades").mkdir()
    # Minimal fixings file with the expected name so the fixing loader stage is reachable.
    (tmp_path / "fixings" / "fixing_cail_USD-FEDFUNDS-ON.csv").write_text(
        "ticker,date,rate\nUSD-FEDFUNDS-ON,2026-03-30,0.04\n", encoding="utf-8"
    )

    main = _load_main()
    rc = main([
        "--val-date", "2026-03-31",
        "--data-dir", str(tmp_path),
        "--out-dir", str(tmp_path / "out"),
        "--pillar-dates",
        "--no-detail", "--no-parquet",
    ])
    assert rc == 1

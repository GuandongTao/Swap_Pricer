"""Output submission-versioning: folder/file/header version stamp.

The version is a 5-digit submission sequence per ``(val_date, data source)``.
It auto-increments past prior runs for the same as-of date, can be overridden
explicitly, and the SAME stamp drives the run folder name, the feed filename,
and header-row cell 4.
"""

from datetime import date
from pathlib import Path

import pytest

from swaps.loaders.excel import ExcelCurveLoader, ExcelFixingLoader
from swaps.loaders.yaml_trades import YamlTradeLoader
from swaps.portfolio import Portfolio, _next_version, _fmt_version


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
VAL = date(2026, 3, 31)


# --- _next_version unit tests (no full run needed) --------------------------

def _mk(base: Path, name: str) -> None:
    (base / name).mkdir(parents=True)


def test_next_version_empty_dir_starts_at_one(tmp_path):
    assert _next_version(tmp_path, VAL, "") == "00001"


def test_next_version_increments_past_highest(tmp_path):
    _mk(tmp_path, "valdate_2026-03-31_rundate_2026-04-01_ver_00001")
    _mk(tmp_path, "valdate_2026-03-31_rundate_2026-04-05_ver_00002")
    # Out-of-order / gap: highest wins, not count.
    _mk(tmp_path, "valdate_2026-03-31_rundate_2026-04-09_ver_00007")
    assert _next_version(tmp_path, VAL, "") == "00008"


def test_next_version_ignores_legacy_unversioned_folders(tmp_path):
    # Folders created BEFORE versioning have no ``_ver_<NNNNN>`` suffix. We
    # cannot derive a sequence number from them, so detection starts fresh at
    # 00001 (and the new ``..._ver_00001`` folder is a distinct name -- the
    # legacy folder is never overwritten).
    _mk(tmp_path, "valdate_2026-03-31_rundate_2026-04-01")
    _mk(tmp_path, "valdate_2026-03-31_rundate_2026-04-02 BBG")
    assert _next_version(tmp_path, VAL, "") == "00001"
    assert _next_version(tmp_path, VAL, " BBG") == "00001"


def test_next_version_is_per_val_date(tmp_path):
    _mk(tmp_path, "valdate_2026-03-31_rundate_2026-04-01_ver_00003")
    # A different val_date must not bleed into this date's sequence.
    _mk(tmp_path, "valdate_2026-06-30_rundate_2026-04-01_ver_00009")
    assert _next_version(tmp_path, VAL, "") == "00004"


def test_next_version_separates_data_sources(tmp_path):
    # Non-BBG and BBG lineages version independently.
    _mk(tmp_path, "valdate_2026-03-31_rundate_2026-04-01_ver_00001")
    _mk(tmp_path, "valdate_2026-03-31_rundate_2026-04-01 BBG_ver_00001")
    _mk(tmp_path, "valdate_2026-03-31_rundate_2026-04-02 BBG_ver_00002")
    assert _next_version(tmp_path, VAL, "") == "00002"        # only the non-BBG one
    assert _next_version(tmp_path, VAL, " BBG") == "00003"    # only the BBG ones


def test_fmt_version_pads_to_five():
    assert _fmt_version(1) == "00001"
    assert _fmt_version(42) == "00042"


# --- end-to-end wiring through Portfolio.run --------------------------------

@pytest.fixture(scope="module")
def loaders():
    return (
        ExcelCurveLoader(DATA / "curves"),
        ExcelFixingLoader(DATA / "fixings" / "fixing_cail_USD-FEDFUNDS-ON.csv"),
        YamlTradeLoader(DATA / "trades"),
    )


def _header_version(prod_csv: Path) -> str:
    first = prod_csv.read_text(encoding="utf-8").splitlines()[0].split(",")
    # H | yyyymmdd | filename | <version> | KPMG
    return first[3]


def test_run_auto_increments_and_stamps_everywhere(loaders, tmp_path):
    cl, fl, tl = loaders
    pf = Portfolio(cl, fl, tl)

    _, m1 = pf.run(VAL, out_dir=tmp_path, write_prod=True)
    _, m2 = pf.run(VAL, out_dir=tmp_path, write_prod=True)

    assert m1.version == "00001"
    assert m2.version == "00002"

    rd1 = Path(m1.outputs["run_dir"])
    rd2 = Path(m2.outputs["run_dir"])
    assert rd1.name.endswith("_ver_00001")
    assert rd2.name.endswith("_ver_00002")

    p1 = Path(m1.outputs["prod_csv"])
    p2 = Path(m2.outputs["prod_csv"])
    assert p1.name == "IRS_Valuation_2026-03-31-00001.csv"
    assert p2.name == "IRS_Valuation_2026-03-31-00002.csv"
    # Folder, filename, and header-cell-4 all carry the same stamp.
    assert _header_version(p1) == "00001"
    assert _header_version(p2) == "00002"


def test_run_explicit_version_override(loaders, tmp_path):
    cl, fl, tl = loaders
    pf = Portfolio(cl, fl, tl)

    _, m = pf.run(VAL, out_dir=tmp_path, write_prod=True, version=7)

    assert m.version == "00007"
    rd = Path(m.outputs["run_dir"])
    assert rd.name.endswith("_ver_00007")
    p = Path(m.outputs["prod_csv"])
    assert p.name == "IRS_Valuation_2026-03-31-00007.csv"
    assert _header_version(p) == "00007"

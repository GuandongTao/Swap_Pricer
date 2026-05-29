"""Netting database loader."""

from __future__ import annotations

import pytest

from swaps.netting_db import load_netting_db


_HEADER = (
    "CHATHAM/Quantum Listing,Netting Agreement\n"
    "CHATHAM/Quantum Listing,Amex Entity,AMEX Legal Entity name,External name,"
    "CPTY Code (as per Quantum) ,Product,Netting ID,Position Netting Allowed,"
    "Multiple Transactions Netting Allowed,Netting Entity,AXP code,Counterparty code\n"
)


def _w(tmp_path, body: str):
    p = tmp_path / "Netting_Database.csv"
    p.write_text(_HEADER + body, encoding="utf-8")
    return p


def test_loads_one_row(tmp_path):
    p = _w(tmp_path,
        "Bank of America,1000,American Express Parent,Bank of America,BAML4,"
        "Swap,S04638,Y,Y,1000,38,46,\n"
    )
    db = load_netting_db(p)
    assert set(db) == {"S04638"}
    r = db["S04638"]
    assert r.cash_flow_netting_allowed == "Y"
    assert r.position_netting_allowed == "Y"
    assert r.netting_entity == "1000"
    assert r.amex_legal_entity_name == "American Express Parent"
    assert r.external_name == "Bank of America"


def test_skips_blank_rows_and_blank_netting_ids(tmp_path):
    p = _w(tmp_path,
        "Bank A,1000,Parent,Bank A,A,Swap,S001,Y,Y,1000,38,46,\n"
        ",,,,,,,,,,,,\n"                 # all-blank row
        "Bank B,1000,Parent,Bank B,B,Swap,,Y,Y,1000,38,47,\n"  # blank netting_id
        "Bank C,1000,Parent,Bank C,C,Swap,S002,N,Y,1000,38,48,\n"
    )
    db = load_netting_db(p)
    assert set(db) == {"S001", "S002"}
    assert db["S002"].position_netting_allowed == "N"


def test_duplicate_netting_id_raises(tmp_path):
    p = _w(tmp_path,
        "Bank A,1000,Parent,Bank A,A,Swap,S001,Y,Y,1000,38,46,\n"
        "Bank B,1000,Parent,Bank B,B,Swap,S001,Y,Y,1000,38,47,\n"
    )
    with pytest.raises(ValueError, match="duplicate netting_id"):
        load_netting_db(p)


def test_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_netting_db(tmp_path / "nope.csv")


def test_missing_required_column_raises(tmp_path):
    # Drop "Netting Entity" from the header row.
    p = tmp_path / "bad.csv"
    p.write_text(
        "title row\n"
        "Amex Entity,External name,Netting ID,Position Netting Allowed,"
        "Multiple Transactions Netting Allowed,AMEX Legal Entity name,Product\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="missing required columns"):
        load_netting_db(p)


def test_fx_rows_are_filtered_out(tmp_path):
    p = _w(tmp_path,
        "ANZ,1021,Overseas,ANZ,AANZ,FX,F04337,Y,Y,1021,37,43,\n"
        "BankAmerica,1000,Parent,BAML,BAML4,Swap,S04638,Y,Y,1000,38,46,\n"
        "DB,1000,Parent,Deutsche,DBBK,Swap,S07238,Y,Y,1000,38,72,\n"
    )
    db = load_netting_db(p)
    assert set(db) == {"S04638", "S07238"}    # F04337 (FX) skipped
    assert "F04337" not in db

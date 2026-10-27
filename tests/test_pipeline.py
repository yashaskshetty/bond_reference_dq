"""End-to-end pipeline tests, including the reconciliation guarantee."""

import csv
import sqlite3
import sys
from pathlib import Path

import pytest

import generate_data
import reference as ref
import run_pipeline

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    """Generate a small file, run the pipeline, hand back the connection."""
    tmp = tmp_path_factory.mktemp("dq")
    csv_path = tmp / "bond_master.csv"
    db_path = tmp / "bond_reference.db"

    records, defect_log = generate_data.generate(
        rows=1200, defect_rate=0.10, seed=99,
    )
    fields = ["row_num"] + ref.ALL_FIELDS
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for rec in records:
            writer.writerow({k: rec.get(k, "") for k in fields})

    conn, run_id = run_pipeline.run(csv_path, db_path, quiet=True)
    yield conn, run_id, dict(defect_log), len(records)
    conn.close()


def test_every_row_lands_in_staging(built):
    conn, _, _, total = built
    count = conn.execute("SELECT COUNT(*) FROM stg_bond_master").fetchone()[0]
    assert count == total


def test_loaded_plus_rejected_equals_read(built):
    conn, run_id, _, _ = built
    read, loaded, rejected = conn.execute(
        "SELECT rows_read, rows_loaded, rows_rejected FROM dq_run_log "
        "WHERE run_id=?", (run_id,)
    ).fetchone()
    assert loaded + rejected == read


def test_no_false_negatives(built):
    """Every seeded defect is detected."""
    conn, run_id, seeded, _ = built
    detected = {
        r[0] for r in conn.execute(
            "SELECT DISTINCT row_num FROM dq_reject_log "
            "WHERE run_id=? AND severity='REJECT'", (run_id,)
        )
    }
    assert set(seeded) - detected == set()


def test_no_false_positives(built):
    """No clean row is rejected."""
    conn, run_id, seeded, _ = built
    detected = {
        r[0] for r in conn.execute(
            "SELECT DISTINCT row_num FROM dq_reject_log "
            "WHERE run_id=? AND severity='REJECT'", (run_id,)
        )
    }
    assert detected - set(seeded) == set()


def test_every_loaded_isin_is_valid(built):
    """Nothing with a broken check digit can reach the dimension."""
    import isin as isin_mod
    conn, _, _, _ = built
    for (value,) in conn.execute("SELECT isin FROM dim_bond"):
        assert isin_mod.is_valid(value)


def test_dim_bond_has_no_duplicates(built):
    conn, _, _, _ = built
    dupes = conn.execute(
        "SELECT COUNT(*) FROM (SELECT isin FROM dim_bond "
        "GROUP BY isin HAVING COUNT(*) > 1)"
    ).fetchone()[0]
    assert dupes == 0


def test_every_rejection_has_a_reason(built):
    conn, run_id, _, _ = built
    blank = conn.execute(
        "SELECT COUNT(*) FROM dq_reject_log "
        "WHERE run_id=? AND (reason IS NULL OR TRIM(reason)='')", (run_id,)
    ).fetchone()[0]
    assert blank == 0


def test_maturity_always_after_issue_in_dim(built):
    conn, _, _, _ = built
    bad = conn.execute(
        "SELECT COUNT(*) FROM dim_bond WHERE maturity_date <= issue_date"
    ).fetchone()[0]
    assert bad == 0


def test_completeness_recorded_for_every_field(built):
    conn, run_id, _, _ = built
    count = conn.execute(
        "SELECT COUNT(*) FROM dq_field_completeness WHERE run_id=?", (run_id,)
    ).fetchone()[0]
    assert count == len(ref.ALL_FIELDS)


def test_run_log_closed_successfully(built):
    conn, run_id, _, _ = built
    status, finished = conn.execute(
        "SELECT status, finished_at FROM dq_run_log WHERE run_id=?", (run_id,)
    ).fetchone()
    assert status == "SUCCESS"
    assert finished is not None


def test_schema_check_constraints_reject_bad_coupon(built):
    """The database is the last line of defence, not just the rule engine."""
    conn, _, _, _ = built
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO dim_bond (isin,issuer_name,instrument_type,currency,"
            "coupon_rate,coupon_frequency,issue_date,maturity_date,face_value,"
            "country,credit_rating,day_count,term_years,loaded_at) "
            "VALUES ('US0378331005','X','Bond','USD',450.0,2,'2020-01-01',"
            "'2030-01-01',1000,'US','AAA','30/360',10,'now')"
        )
    conn.rollback()

"""End-to-end load: CSV -> staging -> validation -> dim_bond + DQ logs.

Mirrors how a reference-data feed is processed in production:

    1. land the file in all-TEXT staging so nothing fails at the door
    2. run every validation rule over the batch
    3. load only clean records into the typed, constrained dimension
    4. log every rejection with a rule code and a human-readable reason
    5. record per-field completeness and close the run audit row

Run:  python src/run_pipeline.py --csv data/bond_master.csv
"""

import argparse
import csv
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import reference as ref
import validate as v

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "sql" / "01_schema.sql"


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def build_schema(conn):
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    conn.commit()


def load_staging(conn, csv_path):
    """Land the raw file in staging exactly as supplied."""
    fields = ["row_num"] + ref.ALL_FIELDS
    rows = []
    with Path(csv_path).open(newline="", encoding="utf-8") as fh:
        for rec in csv.DictReader(fh):
            rows.append(tuple(rec.get(f, "") for f in fields))

    placeholders = ",".join("?" * len(fields))
    conn.executemany(
        f"INSERT INTO stg_bond_master ({','.join(fields)}) "
        f"VALUES ({placeholders})",
        rows,
    )
    conn.commit()
    return len(rows)


def read_staging(conn):
    cur = conn.execute("SELECT * FROM stg_bond_master ORDER BY row_num")
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def run(csv_path, db_path, quiet=False):
    db = Path(db_path)
    if db.exists():
        db.unlink()
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA foreign_keys = ON")

    build_schema(conn)

    started = _now()
    cur = conn.execute(
        "INSERT INTO dq_run_log (started_at, source_file) VALUES (?,?)",
        (started, str(csv_path)),
    )
    run_id = cur.lastrowid
    conn.commit()

    rows_read = load_staging(conn, csv_path)
    records = read_staging(conn)

    violations_by_row = v.validate_batch(records)

    reject_rows = []
    clean_rows = []
    logged_at = _now()

    for rec in records:
        violations = violations_by_row.get(rec["row_num"], [])
        for violation in violations:
            reject_rows.append((
                run_id, rec["row_num"], rec.get("isin"),
                violation.rule_code, violation.rule_name, violation.severity,
                violation.field_name, violation.field_value, violation.reason,
                logged_at,
            ))
        if v.is_rejected(violations):
            continue
        clean_rows.append((
            rec["isin"].strip(),
            rec["issuer_name"].strip(),
            rec["instrument_type"].strip(),
            rec["currency"].strip(),
            float(rec["coupon_rate"]),
            int(float(rec["coupon_frequency"] or 0)),
            rec["issue_date"].strip(),
            rec["maturity_date"].strip(),
            float(rec["face_value"]),
            rec["country"].strip(),
            rec["credit_rating"].strip(),
            (rec["day_count"] or "ACT/ACT").strip(),
            v.term_years(rec["issue_date"], rec["maturity_date"]),
            logged_at,
        ))

    conn.executemany(
        "INSERT INTO dq_reject_log (run_id,row_num,isin,rule_code,rule_name,"
        "severity,field_name,field_value,reason,logged_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        reject_rows,
    )
    conn.executemany(
        "INSERT INTO dim_bond (isin,issuer_name,instrument_type,currency,"
        "coupon_rate,coupon_frequency,issue_date,maturity_date,face_value,"
        "country,credit_rating,day_count,term_years,loaded_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        clean_rows,
    )

    # Per-field completeness, measured on what actually arrived.
    completeness = []
    for field in ref.ALL_FIELDS:
        populated = sum(
            1 for r in records if str(r.get(field) or "").strip() != ""
        )
        completeness.append((
            run_id, field, rows_read, populated,
            round(100.0 * populated / rows_read, 2) if rows_read else 0.0,
        ))
    conn.executemany(
        "INSERT INTO dq_field_completeness "
        "(run_id,field_name,rows_total,rows_populated,pct_complete) "
        "VALUES (?,?,?,?,?)",
        completeness,
    )

    rejected = sum(
        1 for rec in records
        if v.is_rejected(violations_by_row.get(rec["row_num"], []))
    )
    conn.execute(
        "UPDATE dq_run_log SET finished_at=?, rows_read=?, rows_loaded=?, "
        "rows_rejected=?, status=? WHERE run_id=?",
        (_now(), rows_read, len(clean_rows), rejected, "SUCCESS", run_id),
    )
    conn.commit()

    if not quiet:
        _print_summary(conn, run_id, rows_read, len(clean_rows), rejected,
                       len(reject_rows))
    return conn, run_id


def _print_summary(conn, run_id, rows_read, loaded, rejected, violations):
    print()
    print("=" * 62)
    print(f"  BOND REFERENCE DATA QUALITY REPORT — run {run_id}")
    print("=" * 62)
    print(f"  rows read      {rows_read:>8,}")
    print(f"  rows loaded    {loaded:>8,}   ({loaded / rows_read:.2%})")
    print(f"  rows rejected  {rejected:>8,}   ({rejected / rows_read:.2%})")
    print(f"  violations     {violations:>8,}   (a row can fail several rules)")

    print("\n  REJECTIONS BY RULE")
    print("  " + "-" * 58)
    rows = conn.execute(
        "SELECT rule_code, rule_name, severity, COUNT(*) c "
        "FROM dq_reject_log WHERE run_id=? "
        "GROUP BY rule_code, rule_name, severity ORDER BY c DESC", (run_id,)
    ).fetchall()
    for code, name, severity, count in rows:
        print(f"  {code:<5} {name:<28} {severity:<7} {count:>6,}")

    print("\n  FIELD COMPLETENESS (lowest first)")
    print("  " + "-" * 58)
    rows = conn.execute(
        "SELECT field_name, rows_populated, rows_total, pct_complete "
        "FROM dq_field_completeness WHERE run_id=? "
        "ORDER BY pct_complete ASC LIMIT 6", (run_id,)
    ).fetchall()
    for field, populated, total, pct in rows:
        print(f"  {field:<20} {populated:>7,}/{total:<7,} {pct:>7.2f}%")

    print("\n  MATURITY PROFILE (clean records)")
    print("  " + "-" * 58)
    for bucket, count, coupon, face in conn.execute(
        "SELECT maturity_bucket, instruments, avg_coupon, total_face_value "
        "FROM v_maturity_profile ORDER BY maturity_bucket"
    ):
        print(f"  {bucket:<24} {count:>6,}  avg coupon {coupon:>6.3f}%")
    print()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", default="data/bond_master.csv")
    parser.add_argument("--db", default="bond_reference.db")
    args = parser.parse_args()
    conn, _ = run(args.csv, args.db)
    conn.close()


if __name__ == "__main__":
    main()

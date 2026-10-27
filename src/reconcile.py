"""Reconcile detected rejections against the seeded defect list.

The generator records exactly which rows it corrupted. This script proves the
validation engine found those rows and only those rows:

    false negatives — a seeded defect the rules did not catch
    false positives — a clean row the rules rejected anyway

A checker that reports the right *count* but the wrong *rows* is worthless,
so this is the test that actually matters.

Run:  python src/reconcile.py
"""

import argparse
import csv
import sqlite3
from collections import Counter
from pathlib import Path


def load_seeded(path):
    seeded = {}
    with Path(path).open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            seeded[int(row["row_num"])] = row["defect"]
    return seeded


def load_detected(conn, run_id=1):
    """Rows rejected by at least one REJECT-severity rule."""
    rows = conn.execute(
        "SELECT DISTINCT row_num FROM dq_reject_log "
        "WHERE run_id = ? AND severity = 'REJECT'", (run_id,)
    ).fetchall()
    return {r[0] for r in rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="bond_reference.db")
    parser.add_argument("--seeded", default="data/seeded_defects.csv")
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)
    seeded = load_seeded(args.seeded)
    detected = load_detected(conn)
    seeded_rows = set(seeded)

    false_negatives = seeded_rows - detected
    false_positives = detected - seeded_rows
    caught = seeded_rows & detected

    total = conn.execute("SELECT rows_read FROM dq_run_log").fetchone()[0]

    print()
    print("=" * 62)
    print("  RECONCILIATION — detected vs seeded")
    print("=" * 62)
    print(f"  rows in file         {total:>7,}")
    print(f"  defects seeded       {len(seeded_rows):>7,}")
    print(f"  rows rejected        {len(detected):>7,}")
    print(f"  correctly caught     {len(caught):>7,}")
    print(f"  false negatives      {len(false_negatives):>7,}")
    print(f"  false positives      {len(false_positives):>7,}")

    recall = len(caught) / len(seeded_rows) if seeded_rows else 1.0
    precision = len(caught) / len(detected) if detected else 1.0
    print(f"\n  recall               {recall:>7.2%}")
    print(f"  precision            {precision:>7.2%}")

    print("\n  DETECTION BY SEEDED DEFECT TYPE")
    print("  " + "-" * 58)
    by_type = Counter(seeded.values())
    caught_by_type = Counter(seeded[r] for r in caught)
    for defect, count in by_type.most_common():
        found = caught_by_type.get(defect, 0)
        flag = "" if found == count else "   <-- MISSED"
        print(f"  {defect:<26} {found:>5,}/{count:<5,} "
              f"{found / count:>7.1%}{flag}")

    if false_negatives:
        print(f"\n  MISSED ROWS (first 10): "
              f"{sorted(false_negatives)[:10]}")
    if false_positives:
        print(f"\n  FALSE POSITIVE ROWS (first 10): "
              f"{sorted(false_positives)[:10]}")
        for row_num in sorted(false_positives)[:5]:
            rules = conn.execute(
                "SELECT rule_code, reason FROM dq_reject_log "
                "WHERE row_num = ? AND severity='REJECT'", (row_num,)
            ).fetchall()
            print(f"    row {row_num}: {rules}")
    print()
    conn.close()

    if false_negatives or false_positives:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

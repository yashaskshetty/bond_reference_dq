"""Export the daily DQ report and analysis views to CSV for Excel/Power BI.

The reference-data team's deliverable is a daily report, not a database, so
the pipeline ends by writing the files someone actually opens.

Run:  python src/export_reports.py
"""

import argparse
import csv
import sqlite3
from pathlib import Path

EXPORTS = {
    "dq_run_summary": """
        SELECT run_id, source_file, rows_read, rows_loaded, rows_rejected,
               ROUND(100.0 * rows_loaded / rows_read, 2) AS pct_clean, status
        FROM   dq_run_log ORDER BY run_id DESC
    """,
    "dq_rejections_by_rule": """
        SELECT rule_code, rule_name, severity, COUNT(*) AS rejections,
               ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 2) AS pct_of_total
        FROM   dq_reject_log
        GROUP  BY rule_code, rule_name, severity ORDER BY rejections DESC
    """,
    "dq_field_completeness": """
        SELECT field_name, rows_populated, rows_total, pct_complete,
               rows_total - rows_populated AS missing
        FROM   dq_field_completeness ORDER BY pct_complete ASC
    """,
    "dq_reject_detail": """
        SELECT row_num, isin, rule_code, rule_name, severity,
               field_name, field_value, reason
        FROM   dq_reject_log ORDER BY row_num, rule_code
    """,
    "maturity_profile": "SELECT * FROM v_maturity_profile",
    "issuer_exposure": """
        SELECT issuer_name, instruments, total_face_value, avg_coupon,
               ROUND(100.0 * total_face_value
                     / SUM(total_face_value) OVER (), 2) AS pct_of_book
        FROM   v_issuer_exposure ORDER BY total_face_value DESC
    """,
    "coupon_by_rating": """
        SELECT credit_rating, COUNT(*) AS instruments,
               ROUND(AVG(coupon_rate), 3) AS avg_coupon,
               ROUND(MIN(coupon_rate), 3) AS min_coupon,
               ROUND(MAX(coupon_rate), 3) AS max_coupon
        FROM   dim_bond WHERE coupon_rate > 0
        GROUP  BY credit_rating ORDER BY avg_coupon
    """,
    "maturity_ladder": """
        SELECT CAST(strftime('%Y', maturity_date) AS INTEGER) AS maturity_year,
               COUNT(*) AS instruments,
               ROUND(SUM(face_value), 2)  AS face_value_maturing,
               ROUND(AVG(coupon_rate), 3) AS avg_coupon
        FROM   dim_bond GROUP BY maturity_year ORDER BY maturity_year
    """,
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="bond_reference.db")
    parser.add_argument("--out", default="exports")
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    for name, query in EXPORTS.items():
        cur = conn.execute(query)
        header = [d[0] for d in cur.description]
        rows = cur.fetchall()
        path = out_dir / f"{name}.csv"
        with path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(header)
            writer.writerows(rows)
        print(f"  {path}  ({len(rows):,} rows)")

    conn.close()


if __name__ == "__main__":
    main()

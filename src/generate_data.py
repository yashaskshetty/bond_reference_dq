"""Generate a synthetic bond master file with deliberate data defects.

Real vendor reference data is not clean — identifiers get transcribed wrong,
mandatory fields arrive blank, dates get transposed. This generator produces
a file with a known, seeded defect population so the validation engine can be
measured against ground truth: we know exactly how many bad rows went in, so
we can prove the checker found them all.

Run:  python src/generate_data.py --rows 5000 --defect-rate 0.08
"""

import argparse
import csv
import random
from datetime import date, timedelta
from pathlib import Path

import isin as isin_mod
import reference as ref

ISSUERS = [
    ("US Treasury", "US", "USD", "AAA"),
    ("Apple Inc", "US", "USD", "AA+"),
    ("Microsoft Corp", "US", "USD", "AAA"),
    ("JPMorgan Chase", "US", "USD", "A-"),
    ("Ford Motor Credit", "US", "USD", "BB+"),
    ("UK Gilt", "GB", "GBP", "AA"),
    ("Barclays plc", "GB", "GBP", "BBB"),
    ("Vodafone Group", "GB", "GBP", "BBB"),
    ("Bundesrepublik Deutschland", "DE", "EUR", "AAA"),
    ("Deutsche Bank AG", "DE", "EUR", "BBB-"),
    ("Siemens AG", "DE", "EUR", "A+"),
    ("Republique Francaise", "FR", "EUR", "AA"),
    ("TotalEnergies SE", "FR", "EUR", "A"),
    ("ING Groep NV", "NL", "EUR", "A-"),
    ("Nestle SA", "CH", "CHF", "AA-"),
    ("Toyota Motor Corp", "JP", "JPY", "A+"),
    ("Commonwealth of Australia", "AU", "AUD", "AAA"),
    ("Royal Bank of Canada", "CA", "CAD", "A+"),
    ("DBS Group Holdings", "SG", "SGD", "AA-"),
    ("Reliance Industries", "IN", "INR", "BBB"),
]

TYPE_WEIGHTS = [
    ("Bond", 0.45),
    ("Note", 0.25),
    ("Medium Term Note", 0.15),
    ("Debenture", 0.08),
    ("Certificate of Deposit", 0.07),
]

DAY_COUNTS = sorted(ref.VALID_DAY_COUNTS)

# The defects we deliberately inject, and their relative weights.
DEFECTS = [
    ("bad_check_digit", 0.22),
    ("missing_mandatory", 0.18),
    ("maturity_before_issue", 0.13),
    ("coupon_out_of_range", 0.11),
    ("bad_currency", 0.09),
    ("bad_rating", 0.08),
    ("duplicate_isin", 0.07),
    ("negative_face_value", 0.05),
    ("bad_instrument_type", 0.04),
    ("malformed_isin", 0.03),
]


def _weighted_choice(rng, pairs):
    total = sum(w for _, w in pairs)
    roll = rng.random() * total
    upto = 0.0
    for item, weight in pairs:
        upto += weight
        if roll <= upto:
            return item
    return pairs[-1][0]


def _random_isin(rng, country):
    """Build a structurally valid ISIN with a correct check digit."""
    alphabet = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    nsin = "".join(rng.choice(alphabet) for _ in range(9))
    return isin_mod.build(f"{country}{nsin}")


def _make_clean_record(rng, row_num):
    issuer, country, currency, rating = rng.choice(ISSUERS)
    instrument = _weighted_choice(rng, TYPE_WEIGHTS)

    issue = date(2015, 1, 1) + timedelta(days=rng.randint(0, 3650))
    if instrument == "Certificate of Deposit":
        term_days = rng.randint(30, 365)
        frequency = 0
    else:
        term_days = rng.choice([365, 730, 1826, 3652, 7305, 10957])
        frequency = rng.choice([1, 2, 2, 4])
    maturity = issue + timedelta(days=term_days)

    if frequency == 0:
        coupon = 0.0
    else:
        base = {"AAA": 2.0, "AA+": 2.3, "AA": 2.6, "AA-": 2.9,
                "A+": 3.2, "A": 3.5, "A-": 3.8,
                "BBB+": 4.3, "BBB": 4.8, "BBB-": 5.3,
                "BB+": 6.5}.get(rating, 7.0)
        coupon = round(base + rng.uniform(-0.75, 1.5), 3)
        coupon = max(0.0, coupon)

    return {
        "row_num": row_num,
        "isin": _random_isin(rng, country),
        "issuer_name": issuer,
        "instrument_type": instrument,
        "currency": currency,
        "coupon_rate": f"{coupon:.3f}",
        "coupon_frequency": str(frequency),
        "issue_date": issue.isoformat(),
        "maturity_date": maturity.isoformat(),
        "face_value": str(rng.choice([1000, 1000, 1000, 5000, 10000, 100000])),
        "country": country,
        "credit_rating": rating,
        "day_count": rng.choice(DAY_COUNTS),
    }


def _corrupt(rng, rec, defect, pool):
    """Apply one defect to a clean record. Returns the defect actually applied."""
    if defect == "bad_check_digit":
        good = rec["isin"]
        wrong = str((int(good[11]) + rng.randint(1, 9)) % 10)
        rec["isin"] = good[:11] + wrong

    elif defect == "malformed_isin":
        rec["isin"] = rng.choice([
            rec["isin"][:8],
            rec["isin"] + "ZZ",
            rec["isin"][:11] + "X",
            rec["isin"].lower(),
        ])

    elif defect == "missing_mandatory":
        field = rng.choice([f for f in ref.MANDATORY_FIELDS if f != "isin"])
        rec[field] = ""

    elif defect == "maturity_before_issue":
        rec["issue_date"], rec["maturity_date"] = (
            rec["maturity_date"], rec["issue_date"],
        )

    elif defect == "coupon_out_of_range":
        # A misplaced decimal point: 4.5% becomes 450%.
        rec["coupon_rate"] = rng.choice(["450.000", "-2.500", "99.900", "N/A"])

    elif defect == "bad_currency":
        rec["currency"] = rng.choice(["US", "EURO", "XXX", "GBPP", "usd"])

    elif defect == "bad_rating":
        rec["credit_rating"] = rng.choice(["AAA+", "Aa2", "NR", "A1", "BBB++"])

    elif defect == "negative_face_value":
        rec["face_value"] = rng.choice(["-1000", "0", "abc"])

    elif defect == "bad_instrument_type":
        rec["instrument_type"] = rng.choice(
            ["Equity", "Bnd", "Warrant", "bond", "Preferred Share"]
        )

    elif defect == "duplicate_isin":
        if pool:
            rec["isin"] = rng.choice(pool)
        else:
            return None

    return defect


def generate(rows: int, defect_rate: float, seed: int):
    rng = random.Random(seed)
    records = []
    clean_isins = []
    defect_log = []

    for row_num in range(1, rows + 1):
        rec = _make_clean_record(rng, row_num)

        if rng.random() < defect_rate:
            defect = _weighted_choice(rng, DEFECTS)
            applied = _corrupt(rng, rec, defect, clean_isins)
            if applied:
                defect_log.append((row_num, applied))
            else:
                clean_isins.append(rec["isin"])
        else:
            clean_isins.append(rec["isin"])

        records.append(rec)

    return records, defect_log


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=int, default=5000)
    parser.add_argument("--defect-rate", type=float, default=0.08)
    parser.add_argument("--seed", type=int, default=20261027)
    parser.add_argument("--out", default="data/bond_master.csv")
    args = parser.parse_args()

    records, defect_log = generate(args.rows, args.defect_rate, args.seed)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["row_num"] + ref.ALL_FIELDS

    with out_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for rec in records:
            writer.writerow({k: rec.get(k, "") for k in fields})

    truth_path = out_path.with_name("seeded_defects.csv")
    with truth_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["row_num", "defect"])
        writer.writerows(defect_log)

    print(f"wrote {len(records):,} records to {out_path}")
    print(f"seeded {len(defect_log):,} defective rows "
          f"({len(defect_log) / len(records):.1%}) -> {truth_path}")


if __name__ == "__main__":
    main()

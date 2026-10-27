# Bond Reference Data Quality Checker

A validation and reporting pipeline for fixed income reference data — the
instrument master records (ISIN, issuer, coupon, maturity, rating) that sit
behind every bond pricing screen and risk report.

The premise: vendor reference data arrives dirty. Identifiers get mistyped,
mandatory fields arrive blank, dates get transposed. A single wrong coupon
rate propagates into every downstream yield calculation. This project catches
those errors at the door, logs each one with a reason, and reports what the
source feed is getting wrong.

**Headline result: 378 of 378 seeded defects detected across 5,000 records —
100% recall, 100% precision, zero false positives.**

---

## Architecture

```
bond_master.csv
      |
      v
stg_bond_master      all-TEXT staging — nothing fails at the door
      |
      v
13 validation rules  per-record + cross-record checks
      |
      +--> dq_reject_log    every failure, with rule code and reason
      |
      v
dim_bond             typed, constrained, clean records only
      |
      +--> dq_field_completeness   per-field fill rates
      +--> dq_run_log              run audit: counts, timings, status
      |
      v
exports/*.csv        daily report for Excel / Power BI
```

Staging is deliberately all-TEXT. A coupon of `"N/A"` or a date of
`"15/03/2030"` must land in the database so it can be inspected and reported
— if the loader rejects it at parse time, nobody ever finds out what the
source actually sent.

---

## The validation rules

| Code | Rule | Severity | Catches |
|------|------|----------|---------|
| R01 | Mandatory field present | REJECT | Blank issuer, currency, dates, rating |
| R02 | ISIN format | REJECT | Wrong length, lowercase, bad character class |
| R03 | **ISIN check digit** | REJECT | A single mistyped character in the identifier |
| R04 | Date order | REJECT | Maturity on or before issue; unparseable dates |
| R05 | Coupon range | REJECT | Misplaced decimal (4.5% keyed as 450%) |
| R06 | Currency code | REJECT | Not a valid ISO 4217 code |
| R07 | Credit rating scale | REJECT | `Aa2`, `NR`, `AAA+` — off the AAA–D scale |
| R08 | Instrument type | REJECT | Equities or typos in a fixed income file |
| R09 | Face value | REJECT | Zero, negative or non-numeric |
| R10 | Country prefix | WARN/REJECT | ISIN prefix disagreeing with the country field |
| R11 | Coupon frequency | REJECT/WARN | Non-standard schedule; zero-coupon carrying a coupon |
| R12 | Day count convention | WARN | Unrecognised convention |
| R13 | Duplicate ISIN | REJECT | One instrument, two records |

Rules are independent, so a record reports **every** reason it failed rather
than only the first. That matters to whoever has to fix the record — one pass
tells them everything wrong with it.

### Why the ISIN check digit is the interesting one

An ISIN is 2-letter country code + 9-character identifier + 1 check digit,
and that check digit is a Luhn checksum over the first 11 characters with
letters expanded to numbers (`A`=10 … `Z`=35).

This is the only rule that catches an identifier which looks *completely
plausible* — right length, right shape, right country — but is wrong. Every
other error is visible to the naked eye. This one isn't.

The implementation is verified against ten real published ISINs (Apple, a US
Treasury note, BAE, Bayer, TotalEnergies, Airbus, Roche, Toyota and others),
and tested to confirm that corrupting any check digit always fails.

---

## Proving it works

Counting rejections proves nothing — a broken checker can reject the right
*number* of rows and still be flagging the wrong ones. So the generator
records exactly which rows it corrupted, and `reconcile.py` compares detected
against seeded:

```
  rows in file           5,000
  defects seeded           378
  rows rejected            378
  correctly caught         378
  false negatives            0
  false positives            0

  recall               100.00%
  precision            100.00%
```

Every defect class is caught at 100%:

| Seeded defect | Caught |
|---|---|
| bad_check_digit | 91/91 |
| missing_mandatory | 69/69 |
| coupon_out_of_range | 47/47 |
| maturity_before_issue | 41/41 |
| bad_rating | 30/30 |
| duplicate_isin | 28/28 |
| bad_currency | 26/26 |
| bad_instrument_type | 22/22 |
| negative_face_value | 14/14 |
| malformed_isin | 10/10 |

`reconcile.py` exits non-zero on any mismatch, so it works as a CI gate.

---

## What the clean data shows

With the bad records stripped out, the book behaves the way fixed income
should — **credit risk is monotonically priced**:

| Rating | Instruments | Avg coupon |
|---|---|---|
| AAA | 905 | 2.367% |
| AA+ | 219 | 2.636% |
| AA | 373 | 2.994% |
| AA− | 454 | 3.282% |
| A+ | 635 | 3.591% |
| A | 207 | 3.872% |
| A− | 448 | 4.179% |
| BBB | 623 | 5.226% |
| BBB− | 236 | 5.675% |
| BB+ | 205 | 6.931% |

Investment grade averages 3.378% against high yield at 6.518% — a 314bp
spread. The monotonic curve is itself a data-quality signal: a rating bucket
breaking the pattern would point at either mis-tagged ratings or mis-keyed
coupons.

---

## Running it

```bash
pip install -r requirements.txt

python src/generate_data.py --rows 5000 --defect-rate 0.08
python src/run_pipeline.py
python src/reconcile.py
python src/export_reports.py

python -m pytest -q        # 103 tests
```

Outputs land in `exports/` as CSV, ready for Excel or Power BI.

---

## Layout

```
sql/01_schema.sql      staging, dimension, DQ log tables, reporting views
sql/02_queries.sql     10 analysis queries
src/isin.py            ISO 6166 check digit implementation
src/reference.py       controlled vocabularies (ISO 4217, rating scale)
src/validate.py        the 13 rules and the batch engine
src/generate_data.py   synthetic master file with seeded defects
src/run_pipeline.py    CSV -> staging -> validate -> dim + logs
src/reconcile.py       detected vs seeded; exits non-zero on mismatch
src/export_reports.py  daily report CSVs
tests/                 103 tests
```

---

## Known limitations

Worth stating plainly rather than leaving to be discovered:

- **Full refresh only.** Each run rebuilds the database; there is no
  incremental load or restart-from-failure.
- **No history.** A changed rating overwrites the old value — no
  slowly-changing-dimension tracking, so you cannot ask what a bond was rated
  last year.
- **Synthetic data.** The defect population is seeded by the generator, which
  makes 100% recall a measure of rule coverage, not a claim about real vendor
  feeds. Real data would contain defect classes these 13 rules do not model.
- **Rating scale is S&P-style only.** Moody's notation (`Aa2`, `Baa1`) is
  rejected rather than mapped across.
- **No corporate actions.** Calls, puts, sinking funds and amortising
  schedules are not modelled.

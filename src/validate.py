"""The validation rule engine.

Each rule is a small function taking one staged record and returning a list
of Violation objects — empty when the record passes. Rules are independent,
so a single bad record reports every reason it failed rather than only the
first, which is what makes the reject log useful to whoever has to fix it.

Severity:
    REJECT  the record must not enter dim_bond
    WARN    the record is loadable but someone should look at it
"""

from dataclasses import dataclass
from datetime import datetime

import isin as isin_mod
import reference as ref


@dataclass(frozen=True)
class Violation:
    rule_code: str
    rule_name: str
    severity: str
    field_name: str
    field_value: str
    reason: str


def _blank(value) -> bool:
    return value is None or str(value).strip() == ""


def _parse_date(value):
    """Return a date, or None if the value is not an ISO date."""
    if _blank(value):
        return None
    try:
        return datetime.strptime(str(value).strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


def _parse_float(value):
    if _blank(value):
        return None
    try:
        return float(str(value).strip())
    except ValueError:
        return None


# --------------------------------------------------------------- the rules --

def rule_01_mandatory_fields(rec):
    """R01 — every mandatory field is populated."""
    out = []
    for field in ref.MANDATORY_FIELDS:
        if _blank(rec.get(field)):
            out.append(Violation(
                "R01", "Mandatory field present", "REJECT",
                field, "", f"mandatory field '{field}' is empty",
            ))
    return out


def rule_02_isin_format(rec):
    """R02 — ISIN matches the ISO 6166 shape."""
    value = str(rec.get("isin") or "").strip()
    if _blank(value):
        return []                      # already reported by R01
    if not isin_mod.is_well_formed(value):
        return [Violation(
            "R02", "ISIN format", "REJECT", "isin", value,
            "ISIN must be 2 letters + 9 alphanumerics + 1 check digit",
        )]
    return []


def rule_03_isin_check_digit(rec):
    """R03 — the ISIN Luhn check digit is correct.

    This is the rule that catches a transcription error in an identifier
    that otherwise looks perfectly plausible.
    """
    value = str(rec.get("isin") or "").strip()
    if not isin_mod.is_well_formed(value):
        return []                      # shape already reported by R02
    expected = isin_mod.check_digit(value[:11])
    if expected != int(value[11]):
        return [Violation(
            "R03", "ISIN check digit", "REJECT", "isin", value,
            f"check digit is {value[11]}, expected {expected}",
        )]
    return []


def rule_04_date_order(rec):
    """R04 — maturity falls after issue."""
    issue = _parse_date(rec.get("issue_date"))
    maturity = _parse_date(rec.get("maturity_date"))
    out = []
    for field, parsed in (("issue_date", issue), ("maturity_date", maturity)):
        raw = rec.get(field)
        if not _blank(raw) and parsed is None:
            out.append(Violation(
                "R04", "Date order", "REJECT", field, str(raw),
                "date is not in YYYY-MM-DD format",
            ))
    if issue and maturity and maturity <= issue:
        out.append(Violation(
            "R04", "Date order", "REJECT", "maturity_date", str(maturity),
            f"maturity {maturity} is not after issue {issue}",
        ))
    return out


def rule_05_coupon_range(rec):
    """R05 — coupon rate is a number inside a plausible band."""
    raw = rec.get("coupon_rate")
    if _blank(raw):
        return []
    coupon = _parse_float(raw)
    if coupon is None:
        return [Violation(
            "R05", "Coupon range", "REJECT", "coupon_rate", str(raw),
            "coupon rate is not numeric",
        )]
    if not (ref.MIN_COUPON_RATE <= coupon <= ref.MAX_COUPON_RATE):
        return [Violation(
            "R05", "Coupon range", "REJECT", "coupon_rate", str(raw),
            f"coupon {coupon} outside {ref.MIN_COUPON_RATE}-{ref.MAX_COUPON_RATE}%",
        )]
    return []


def rule_06_currency_code(rec):
    """R06 — currency is a known ISO 4217 code."""
    value = str(rec.get("currency") or "").strip()
    if _blank(value):
        return []
    if value not in ref.VALID_CURRENCIES:
        return [Violation(
            "R06", "Currency code", "REJECT", "currency", value,
            f"'{value}' is not a recognised ISO 4217 code",
        )]
    return []


def rule_07_credit_rating(rec):
    """R07 — credit rating sits on the standard scale."""
    value = str(rec.get("credit_rating") or "").strip()
    if _blank(value):
        return []
    if value not in ref.VALID_RATINGS:
        return [Violation(
            "R07", "Credit rating scale", "REJECT", "credit_rating", value,
            f"'{value}' is not on the AAA-D rating scale",
        )]
    return []


def rule_08_instrument_type(rec):
    """R08 — instrument type is one of the supported asset classes."""
    value = str(rec.get("instrument_type") or "").strip()
    if _blank(value):
        return []
    if value not in ref.VALID_INSTRUMENT_TYPES:
        return [Violation(
            "R08", "Instrument type", "REJECT", "instrument_type", value,
            f"'{value}' is not a supported instrument type",
        )]
    return []


def rule_09_face_value(rec):
    """R09 — face value is numeric and positive."""
    raw = rec.get("face_value")
    if _blank(raw):
        return []
    value = _parse_float(raw)
    if value is None:
        return [Violation(
            "R09", "Face value", "REJECT", "face_value", str(raw),
            "face value is not numeric",
        )]
    if value <= 0:
        return [Violation(
            "R09", "Face value", "REJECT", "face_value", str(raw),
            f"face value {value} must be positive",
        )]
    return []


def rule_10_country_prefix(rec):
    """R10 — the ISIN country prefix agrees with the country field.

    A mismatch usually means one of the two was keyed from the wrong source.
    """
    isin_value = str(rec.get("isin") or "").strip()
    country = str(rec.get("country") or "").strip()
    if len(isin_value) < 2 or _blank(country):
        return []
    prefix = isin_value[:2]
    if country not in ref.VALID_COUNTRIES:
        return [Violation(
            "R10", "Country prefix", "REJECT", "country", country,
            f"'{country}' is not a recognised country code",
        )]
    if prefix != country:
        return [Violation(
            "R10", "Country prefix", "WARN", "country", country,
            f"ISIN prefix '{prefix}' does not match country '{country}'",
        )]
    return []


def rule_11_coupon_frequency(rec):
    """R11 — coupon frequency is a standard payment schedule."""
    raw = rec.get("coupon_frequency")
    if _blank(raw):
        return []
    try:
        freq = int(float(str(raw).strip()))
    except ValueError:
        return [Violation(
            "R11", "Coupon frequency", "REJECT", "coupon_frequency", str(raw),
            "coupon frequency is not numeric",
        )]
    if freq not in ref.VALID_COUPON_FREQUENCIES:
        return [Violation(
            "R11", "Coupon frequency", "REJECT", "coupon_frequency", str(raw),
            f"{freq} is not a standard frequency "
            f"{sorted(ref.VALID_COUPON_FREQUENCIES)}",
        )]
    coupon = _parse_float(rec.get("coupon_rate"))
    if freq == 0 and coupon is not None and coupon > 0:
        return [Violation(
            "R11", "Coupon frequency", "WARN", "coupon_frequency", str(raw),
            f"zero-coupon instrument carries a {coupon}% coupon",
        )]
    return []


def rule_12_day_count(rec):
    """R12 — day count convention is recognised."""
    value = str(rec.get("day_count") or "").strip()
    if _blank(value):
        return []
    if value not in ref.VALID_DAY_COUNTS:
        return [Violation(
            "R12", "Day count convention", "WARN", "day_count", value,
            f"'{value}' is not a recognised day count convention",
        )]
    return []


RULES = [
    rule_01_mandatory_fields,
    rule_02_isin_format,
    rule_03_isin_check_digit,
    rule_04_date_order,
    rule_05_coupon_range,
    rule_06_currency_code,
    rule_07_credit_rating,
    rule_08_instrument_type,
    rule_09_face_value,
    rule_10_country_prefix,
    rule_11_coupon_frequency,
    rule_12_day_count,
]


def validate_record(rec):
    """Run every rule against one record and return all violations."""
    out = []
    for rule in RULES:
        out.extend(rule(rec))
    return out


def validate_batch(records):
    """Validate a batch, adding the cross-record duplicate-ISIN check.

    Returns {row_num: [Violation, ...]} for every row with at least one
    violation. Duplicate detection cannot live in a per-record rule because
    it needs to see the whole batch.
    """
    results = {}
    for rec in records:
        violations = validate_record(rec)
        if violations:
            results[rec["row_num"]] = violations

    seen = {}
    for rec in records:
        key = str(rec.get("isin") or "").strip()
        if not key:
            continue
        if key in seen:
            violation = Violation(
                "R13", "Duplicate ISIN", "REJECT", "isin", key,
                f"ISIN already present on row {seen[key]}",
            )
            results.setdefault(rec["row_num"], []).append(violation)
        else:
            seen[key] = rec["row_num"]
    return results


def is_rejected(violations) -> bool:
    """A record is rejected if any violation has REJECT severity."""
    return any(v.severity == "REJECT" for v in violations)


def term_years(issue_date: str, maturity_date: str):
    """Years between issue and maturity, to 2dp."""
    issue = _parse_date(issue_date)
    maturity = _parse_date(maturity_date)
    if not issue or not maturity:
        return None
    return round((maturity - issue).days / 365.25, 2)

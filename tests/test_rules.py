"""Validation rule tests.

Each rule gets a clean record that must pass and at least one corrupted
record that must fail with the expected rule code.
"""

import pytest

import validate as v


def clean_record(**overrides):
    rec = {
        "row_num": 1,
        "isin": "US0378331005",
        "issuer_name": "Apple Inc",
        "instrument_type": "Bond",
        "currency": "USD",
        "coupon_rate": "3.250",
        "coupon_frequency": "2",
        "issue_date": "2020-03-15",
        "maturity_date": "2030-03-15",
        "face_value": "1000",
        "country": "US",
        "credit_rating": "AA+",
        "day_count": "30/360",
    }
    rec.update(overrides)
    return rec


def codes(violations):
    return {x.rule_code for x in violations}


def test_clean_record_passes_everything():
    assert v.validate_record(clean_record()) == []


# ------------------------------------------------------------------ R01-R03 --

@pytest.mark.parametrize("field", [
    "issuer_name", "instrument_type", "currency", "coupon_rate",
    "issue_date", "maturity_date", "face_value", "country", "credit_rating",
])
def test_r01_missing_mandatory_field(field):
    violations = v.validate_record(clean_record(**{field: ""}))
    assert "R01" in codes(violations)


def test_r02_malformed_isin():
    violations = v.validate_record(clean_record(isin="US03783"))
    assert "R02" in codes(violations)


def test_r03_bad_check_digit():
    violations = v.validate_record(clean_record(isin="US0378331004"))
    assert "R03" in codes(violations)


def test_r03_not_reported_when_shape_is_wrong():
    """A malformed ISIN is an R02 problem; R03 should stay quiet."""
    violations = v.validate_record(clean_record(isin="US03783"))
    assert "R03" not in codes(violations)


# ------------------------------------------------------------------ R04-R06 --

def test_r04_maturity_before_issue():
    violations = v.validate_record(
        clean_record(issue_date="2030-03-15", maturity_date="2020-03-15")
    )
    assert "R04" in codes(violations)


def test_r04_same_day_is_invalid():
    violations = v.validate_record(
        clean_record(issue_date="2020-03-15", maturity_date="2020-03-15")
    )
    assert "R04" in codes(violations)


def test_r04_unparseable_date():
    violations = v.validate_record(clean_record(maturity_date="15/03/2030"))
    assert "R04" in codes(violations)


@pytest.mark.parametrize("coupon", ["450.000", "-2.500", "N/A", "25.001"])
def test_r05_coupon_out_of_range(coupon):
    violations = v.validate_record(clean_record(coupon_rate=coupon))
    assert "R05" in codes(violations)


@pytest.mark.parametrize("coupon", ["0.000", "25.000", "3.125"])
def test_r05_coupon_boundaries_accepted(coupon):
    violations = v.validate_record(clean_record(coupon_rate=coupon))
    assert "R05" not in codes(violations)


@pytest.mark.parametrize("currency", ["US", "EURO", "XXX", "usd"])
def test_r06_bad_currency(currency):
    violations = v.validate_record(clean_record(currency=currency))
    assert "R06" in codes(violations)


# ------------------------------------------------------------------ R07-R09 --

@pytest.mark.parametrize("rating", ["AAA+", "Aa2", "NR", "BBB++"])
def test_r07_bad_rating(rating):
    violations = v.validate_record(clean_record(credit_rating=rating))
    assert "R07" in codes(violations)


@pytest.mark.parametrize("rating", ["AAA", "BBB-", "D", "CCC+"])
def test_r07_valid_ratings_accepted(rating):
    violations = v.validate_record(clean_record(credit_rating=rating))
    assert "R07" not in codes(violations)


@pytest.mark.parametrize("instrument", ["Equity", "bond", "Warrant"])
def test_r08_bad_instrument_type(instrument):
    violations = v.validate_record(clean_record(instrument_type=instrument))
    assert "R08" in codes(violations)


@pytest.mark.parametrize("face", ["-1000", "0", "abc"])
def test_r09_bad_face_value(face):
    violations = v.validate_record(clean_record(face_value=face))
    assert "R09" in codes(violations)


# ------------------------------------------------------------------ R10-R12 --

def test_r10_country_prefix_mismatch_warns():
    violations = v.validate_record(clean_record(country="GB"))
    r10 = [x for x in violations if x.rule_code == "R10"]
    assert r10 and r10[0].severity == "WARN"


def test_r10_unknown_country_rejects():
    violations = v.validate_record(clean_record(country="ZZ"))
    r10 = [x for x in violations if x.rule_code == "R10"]
    assert r10 and r10[0].severity == "REJECT"


@pytest.mark.parametrize("freq", ["3", "7", "abc"])
def test_r11_bad_coupon_frequency(freq):
    violations = v.validate_record(clean_record(coupon_frequency=freq))
    assert "R11" in codes(violations)


def test_r11_zero_coupon_with_coupon_rate_warns():
    violations = v.validate_record(
        clean_record(coupon_frequency="0", coupon_rate="3.250")
    )
    r11 = [x for x in violations if x.rule_code == "R11"]
    assert r11 and r11[0].severity == "WARN"


def test_r12_unknown_day_count_warns():
    violations = v.validate_record(clean_record(day_count="30/365"))
    r12 = [x for x in violations if x.rule_code == "R12"]
    assert r12 and r12[0].severity == "WARN"


# ------------------------------------------------------------------- batch --

def test_r13_duplicate_isin_flags_the_second_occurrence():
    records = [
        clean_record(row_num=1),
        clean_record(row_num=2),
    ]
    results = v.validate_batch(records)
    assert 1 not in results            # first occurrence is fine
    assert "R13" in codes(results[2])


def test_batch_reports_every_failure_on_one_row():
    """A row failing several rules reports all of them, not just the first."""
    bad = clean_record(
        row_num=1, isin="US0378331004", currency="XXX", credit_rating="Aa2",
    )
    results = v.validate_batch([bad])
    assert {"R03", "R06", "R07"} <= codes(results[1])


def test_warn_only_record_is_not_rejected():
    rec = clean_record(day_count="30/365")
    violations = v.validate_record(rec)
    assert violations
    assert not v.is_rejected(violations)


def test_reject_severity_blocks_load():
    rec = clean_record(isin="US0378331004")
    assert v.is_rejected(v.validate_record(rec))


def test_term_years():
    assert v.term_years("2020-03-15", "2030-03-15") == pytest.approx(10.0, abs=0.02)
    assert v.term_years("2020-03-15", "bad") is None

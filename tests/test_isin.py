"""ISIN check-digit tests, anchored on real published identifiers."""

import pytest

import isin

# Real, publicly listed ISINs. If the Luhn implementation is wrong, these fail.
REAL_ISINS = [
    "US0378331005",   # Apple Inc
    "US5949181045",   # Microsoft Corp
    "US912828U816",   # US Treasury Note
    "GB0002634946",   # BAE Systems
    "DE000BAY0017",   # Bayer AG
    "FR0000120271",   # TotalEnergies
    "NL0000235190",   # Airbus
    "CH0012032048",   # Roche
    "JP3633400001",   # Toyota
    "AU0000XVGZA3",   # Australian listing
]


@pytest.mark.parametrize("value", REAL_ISINS)
def test_real_isins_validate(value):
    assert isin.is_valid(value)


@pytest.mark.parametrize("value", REAL_ISINS)
def test_check_digit_is_reproducible(value):
    assert isin.build(value[:11]) == value


@pytest.mark.parametrize("value", REAL_ISINS)
def test_single_digit_corruption_is_caught(value):
    """Changing the check digit must always break validation."""
    for replacement in "0123456789":
        if replacement == value[11]:
            continue
        assert not isin.is_valid(value[:11] + replacement)


def test_letter_expansion():
    assert isin.expand("0") == "0"
    assert isin.expand("A") == "10"
    assert isin.expand("Z") == "35"
    assert isin.expand("US03") == "302803"


def test_expand_rejects_bad_characters():
    with pytest.raises(ValueError):
        isin.expand("us-3")


@pytest.mark.parametrize("value", [
    "",                  # empty
    "US037833100",       # 11 chars, too short
    "US03783310055",     # 13 chars, too long
    "us0378331005",      # lowercase
    "U50378331005",      # digit in the country prefix
    "US037833100A",      # letter in the check-digit position
])
def test_malformed_isins_rejected(value):
    assert not isin.is_valid(value)
    assert not isin.is_well_formed(value)


def test_well_formed_but_wrong_checksum():
    """Shape can be right while the checksum is still wrong."""
    value = "US0378331004"
    assert isin.is_well_formed(value)
    assert not isin.is_valid(value)

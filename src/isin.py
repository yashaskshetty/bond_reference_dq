"""ISIN validation.

An ISIN (ISO 6166) is the primary key of fixed income reference data:
12 characters = 2-letter country prefix + 9-character NSIN + 1 check digit.

The check digit is a Luhn checksum computed over the first 11 characters
after letters are expanded to their numeric values (A=10 ... Z=35). A single
mistyped character almost always breaks the checksum, which makes this the
cheapest possible guard against bad identifiers entering the database.
"""

import re

ISIN_PATTERN = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")


def expand(body: str) -> str:
    """Expand an alphanumeric ISIN body to a pure digit string.

    Letters become their 0-indexed alphabet position plus 10, so A -> 10,
    B -> 11 ... Z -> 35. Digits are left alone.
    """
    out = []
    for ch in body:
        if ch.isdigit():
            out.append(ch)
        elif "A" <= ch <= "Z":
            out.append(str(ord(ch) - ord("A") + 10))
        else:
            raise ValueError(f"invalid ISIN character: {ch!r}")
    return "".join(out)


def check_digit(first_eleven: str) -> int:
    """Return the Luhn check digit for the first 11 characters of an ISIN.

    Doubling starts at the rightmost digit of the expanded string, per ISO 6166.
    """
    digits = expand(first_eleven)
    total = 0
    for position, ch in enumerate(reversed(digits), start=1):
        value = int(ch)
        if position % 2 == 1:          # rightmost digit is doubled
            value *= 2
            if value > 9:
                value -= 9             # same as summing the two digits
        total += value
    return (10 - total % 10) % 10


def is_well_formed(isin: str) -> bool:
    """True if the ISIN matches the ISO 6166 shape (ignores the checksum)."""
    return bool(isin) and bool(ISIN_PATTERN.match(isin))


def is_valid(isin: str) -> bool:
    """True if the ISIN is well formed AND its check digit is correct."""
    if not is_well_formed(isin):
        return False
    return check_digit(isin[:11]) == int(isin[11])


def build(first_eleven: str) -> str:
    """Append the correct check digit to an 11-character ISIN body."""
    return f"{first_eleven}{check_digit(first_eleven)}"

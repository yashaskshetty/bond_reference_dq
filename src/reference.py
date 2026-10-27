"""Controlled vocabularies for fixed income reference data.

These are the lists a validation rule checks a field against. In a real
reference-data shop they would be tables maintained by a data governance
team; here they are small enough to keep in code.
"""

# ISO 4217 — the currencies a bond is realistically denominated in.
VALID_CURRENCIES = {
    "USD", "EUR", "GBP", "JPY", "CHF", "AUD", "CAD", "NZD",
    "SEK", "NOK", "DKK", "SGD", "HKD", "INR", "CNY", "ZAR",
}

# ISO 3166-1 alpha-2 prefixes seen on ISINs in this dataset.
VALID_COUNTRIES = {
    "US", "GB", "DE", "FR", "NL", "IT", "ES", "CH",
    "JP", "AU", "CA", "SG", "HK", "IN", "SE", "NO", "XS",
}

# Standard long-term rating scale, best to worst. Order matters: the index
# is used to rank credit quality.
RATING_SCALE = [
    "AAA",
    "AA+", "AA", "AA-",
    "A+", "A", "A-",
    "BBB+", "BBB", "BBB-",
    "BB+", "BB", "BB-",
    "B+", "B", "B-",
    "CCC+", "CCC", "CCC-",
    "CC", "C", "D",
]
VALID_RATINGS = set(RATING_SCALE)

# Investment grade is BBB- and above — the cutoff most mandates care about.
INVESTMENT_GRADE = set(RATING_SCALE[: RATING_SCALE.index("BBB-") + 1])

VALID_INSTRUMENT_TYPES = {
    "Bond",
    "Note",
    "Debenture",
    "Certificate of Deposit",
    "Medium Term Note",
}

# Coupons per year. 0 means a zero-coupon instrument.
VALID_COUPON_FREQUENCIES = {0, 1, 2, 4, 12}

VALID_DAY_COUNTS = {
    "30/360",
    "ACT/360",
    "ACT/365",
    "ACT/ACT",
}

# A coupon outside this band is a data error, not an exotic instrument.
MIN_COUPON_RATE = 0.0
MAX_COUPON_RATE = 25.0

# Fields that must be present on every record.
MANDATORY_FIELDS = [
    "isin",
    "issuer_name",
    "instrument_type",
    "currency",
    "coupon_rate",
    "issue_date",
    "maturity_date",
    "face_value",
    "country",
    "credit_rating",
]

ALL_FIELDS = MANDATORY_FIELDS + ["coupon_frequency", "day_count"]

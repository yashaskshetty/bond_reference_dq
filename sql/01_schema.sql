-- Bond reference data quality checker — schema
--
-- Three layers, mirroring how a reference-data feed is actually processed:
--   stg_bond_master  all-TEXT staging, so nothing is rejected at the door
--   dim_bond         typed, constrained, clean records only
--   dq_*             reject log, run audit and completeness metrics
--
-- Nothing reaches dim_bond without passing every rule in src/validate.py.

DROP VIEW  IF EXISTS v_reject_summary;
DROP VIEW  IF EXISTS v_field_completeness;
DROP VIEW  IF EXISTS v_maturity_profile;
DROP VIEW  IF EXISTS v_issuer_exposure;
DROP TABLE IF EXISTS dq_field_completeness;
DROP TABLE IF EXISTS dq_reject_log;
DROP TABLE IF EXISTS dq_run_log;
DROP TABLE IF EXISTS dim_bond;
DROP TABLE IF EXISTS stg_bond_master;

-- ---------------------------------------------------------------- staging --
-- Every column is TEXT on purpose. A malformed date or a coupon of "N/A"
-- must land in the database so it can be inspected and reported, not blow up
-- the load.
CREATE TABLE stg_bond_master (
    row_num           INTEGER PRIMARY KEY,
    isin              TEXT,
    issuer_name       TEXT,
    instrument_type   TEXT,
    currency          TEXT,
    coupon_rate       TEXT,
    coupon_frequency  TEXT,
    issue_date        TEXT,
    maturity_date     TEXT,
    face_value        TEXT,
    country           TEXT,
    credit_rating     TEXT,
    day_count         TEXT
);

-- ------------------------------------------------------------- clean dim --
CREATE TABLE dim_bond (
    isin              TEXT    PRIMARY KEY,
    issuer_name       TEXT    NOT NULL,
    instrument_type   TEXT    NOT NULL
        CHECK (instrument_type IN ('Bond','Note','Debenture',
                                   'Certificate of Deposit','Medium Term Note')),
    currency          TEXT    NOT NULL CHECK (length(currency) = 3),
    coupon_rate       REAL    NOT NULL CHECK (coupon_rate >= 0 AND coupon_rate <= 25),
    coupon_frequency  INTEGER NOT NULL CHECK (coupon_frequency IN (0,1,2,4,12)),
    issue_date        TEXT    NOT NULL,
    maturity_date     TEXT    NOT NULL,
    face_value        REAL    NOT NULL CHECK (face_value > 0),
    country           TEXT    NOT NULL CHECK (length(country) = 2),
    credit_rating     TEXT    NOT NULL,
    day_count         TEXT    NOT NULL,
    term_years        REAL,
    loaded_at         TEXT    NOT NULL,
    CHECK (maturity_date > issue_date)
);

CREATE INDEX idx_bond_issuer   ON dim_bond(issuer_name);
CREATE INDEX idx_bond_maturity ON dim_bond(maturity_date);
CREATE INDEX idx_bond_rating   ON dim_bond(credit_rating);
CREATE INDEX idx_bond_ccy      ON dim_bond(currency);

-- ------------------------------------------------------------ dq logging --
CREATE TABLE dq_run_log (
    run_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at     TEXT    NOT NULL,
    finished_at    TEXT,
    source_file    TEXT    NOT NULL,
    rows_read      INTEGER DEFAULT 0,
    rows_loaded    INTEGER DEFAULT 0,
    rows_rejected  INTEGER DEFAULT 0,
    status         TEXT    DEFAULT 'RUNNING'
);

CREATE TABLE dq_reject_log (
    reject_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id      INTEGER NOT NULL REFERENCES dq_run_log(run_id),
    row_num     INTEGER NOT NULL,
    isin        TEXT,
    rule_code   TEXT    NOT NULL,
    rule_name   TEXT    NOT NULL,
    severity    TEXT    NOT NULL CHECK (severity IN ('REJECT','WARN')),
    field_name  TEXT,
    field_value TEXT,
    reason      TEXT    NOT NULL,
    logged_at   TEXT    NOT NULL
);

CREATE INDEX idx_reject_run  ON dq_reject_log(run_id);
CREATE INDEX idx_reject_rule ON dq_reject_log(rule_code);

CREATE TABLE dq_field_completeness (
    run_id        INTEGER NOT NULL REFERENCES dq_run_log(run_id),
    field_name    TEXT    NOT NULL,
    rows_total    INTEGER NOT NULL,
    rows_populated INTEGER NOT NULL,
    pct_complete  REAL    NOT NULL,
    PRIMARY KEY (run_id, field_name)
);

-- --------------------------------------------------------------- reports --
CREATE VIEW v_reject_summary AS
SELECT run_id,
       rule_code,
       rule_name,
       severity,
       COUNT(*) AS rejections
FROM   dq_reject_log
GROUP  BY run_id, rule_code, rule_name, severity;

CREATE VIEW v_field_completeness AS
SELECT run_id, field_name, rows_populated, rows_total, pct_complete
FROM   dq_field_completeness;

CREATE VIEW v_maturity_profile AS
SELECT CASE
           WHEN term_years <  1  THEN '0-1y  (money market)'
           WHEN term_years <  5  THEN '1-5y  (short)'
           WHEN term_years < 10  THEN '5-10y (medium)'
           WHEN term_years < 30  THEN '10-30y (long)'
           ELSE '30y+  (ultra long)'
       END AS maturity_bucket,
       COUNT(*)            AS instruments,
       ROUND(AVG(coupon_rate), 3) AS avg_coupon,
       ROUND(SUM(face_value), 2)  AS total_face_value
FROM   dim_bond
GROUP  BY maturity_bucket;

CREATE VIEW v_issuer_exposure AS
SELECT issuer_name,
       COUNT(*)                   AS instruments,
       ROUND(SUM(face_value), 2)  AS total_face_value,
       ROUND(AVG(coupon_rate), 3) AS avg_coupon,
       MIN(credit_rating)         AS best_rating
FROM   dim_bond
GROUP  BY issuer_name;

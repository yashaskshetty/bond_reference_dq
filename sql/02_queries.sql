-- Reporting queries over the clean dimension and the DQ logs.
-- Each one answers a question a reference-data team is actually asked.

-- 1. Daily data quality scorecard -------------------------------------------
SELECT run_id,
       source_file,
       rows_read,
       rows_loaded,
       rows_rejected,
       ROUND(100.0 * rows_loaded / rows_read, 2) AS pct_clean,
       status
FROM   dq_run_log
ORDER  BY run_id DESC;

-- 2. Which rule fires most? Tells you where to fix the source ---------------
SELECT rule_code,
       rule_name,
       severity,
       COUNT(*)                                        AS rejections,
       ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 2) AS pct_of_total
FROM   dq_reject_log
GROUP  BY rule_code, rule_name, severity
ORDER  BY rejections DESC;

-- 3. Fields most often missing at source ------------------------------------
SELECT field_name,
       rows_populated,
       rows_total,
       pct_complete,
       rows_total - rows_populated AS missing
FROM   dq_field_completeness
ORDER  BY pct_complete ASC;

-- 4. Maturity ladder — what is rolling off and when -------------------------
SELECT CAST(strftime('%Y', maturity_date) AS INTEGER) AS maturity_year,
       COUNT(*)                   AS instruments,
       ROUND(SUM(face_value), 2)  AS face_value_maturing,
       ROUND(AVG(coupon_rate), 3) AS avg_coupon
FROM   dim_bond
WHERE  maturity_date >= date('now')
GROUP  BY maturity_year
ORDER  BY maturity_year
LIMIT  20;

-- 5. Investment grade vs high yield split -----------------------------------
SELECT CASE
           WHEN credit_rating IN ('AAA','AA+','AA','AA-','A+','A','A-',
                                  'BBB+','BBB','BBB-')
           THEN 'Investment Grade' ELSE 'High Yield'
       END                        AS grade,
       COUNT(*)                   AS instruments,
       ROUND(AVG(coupon_rate), 3) AS avg_coupon,
       ROUND(SUM(face_value), 2)  AS total_face_value
FROM   dim_bond
GROUP  BY grade;

-- 6. Average coupon by rating — does the curve behave? ----------------------
-- Credit risk should be priced: weaker ratings ought to carry higher coupons.
SELECT credit_rating,
       COUNT(*)                   AS instruments,
       ROUND(AVG(coupon_rate), 3) AS avg_coupon,
       ROUND(MIN(coupon_rate), 3) AS min_coupon,
       ROUND(MAX(coupon_rate), 3) AS max_coupon
FROM   dim_bond
WHERE  coupon_rate > 0
GROUP  BY credit_rating
ORDER  BY avg_coupon;

-- 7. Issuer concentration ---------------------------------------------------
SELECT issuer_name,
       instruments,
       total_face_value,
       ROUND(100.0 * total_face_value
             / SUM(total_face_value) OVER (), 2) AS pct_of_book
FROM   v_issuer_exposure
ORDER  BY total_face_value DESC
LIMIT  10;

-- 8. Zero-coupon instruments — should all be short-dated CDs ----------------
SELECT instrument_type,
       COUNT(*)                   AS instruments,
       ROUND(AVG(term_years), 2)  AS avg_term_years
FROM   dim_bond
WHERE  coupon_frequency = 0
GROUP  BY instrument_type;

-- 9. Worst offending rows — most rules failed at once -----------------------
SELECT row_num,
       isin,
       COUNT(*)                        AS rules_failed,
       GROUP_CONCAT(rule_code, ', ')   AS codes
FROM   dq_reject_log
GROUP  BY row_num, isin
HAVING COUNT(*) > 1
ORDER  BY rules_failed DESC
LIMIT  15;

-- 10. Currency coverage -----------------------------------------------------
SELECT currency,
       COUNT(*)                   AS instruments,
       ROUND(AVG(coupon_rate), 3) AS avg_coupon
FROM   dim_bond
GROUP  BY currency
ORDER  BY instruments DESC;

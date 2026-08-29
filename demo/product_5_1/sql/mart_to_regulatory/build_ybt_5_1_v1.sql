-- Product 5.1 Demo ETL v1: Regulatory Mart -> YBT target
DROP TABLE IF EXISTS ybt_5_1_product_business_basic;
CREATE TABLE ybt_5_1_product_business_basic AS
SELECT
    master.product_id,
    master.institution_id,
    master.product_name,
    master.product_number,
    master.accounting_subject_type,
    classification.product_category,
    master.proprietary_flag,
    master.currency,
    CAST(master.product_term AS TEXT) AS product_term,
    master.establishment_date,
    master.maturity_date,
    master.product_issue,
    master.interest_rate_type,
    master.product_status_code,
    CASE WHEN master.proprietary_flag = '02' THEN master.agency_institution_name ELSE NULL END AS agency_institution_name,
    master.remark,
    master.collection_date
FROM mart_product_master master
JOIN mart_product_regulatory_classification classification ON classification.product_id = master.product_id;
CREATE UNIQUE INDEX ux_ybt_5_1_product_id ON ybt_5_1_product_business_basic(product_id);


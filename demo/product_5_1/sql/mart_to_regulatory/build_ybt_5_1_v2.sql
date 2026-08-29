-- Product 5.1 Demo ETL v2 for change-impact analysis.
-- Change: if a specialized source has already stopped a product, the regulatory status becomes 02
-- even when the product-center status has not yet caught up. This affects E010015 and downstream reviews.
DROP TABLE IF EXISTS ybt_5_1_product_business_basic;
CREATE TABLE ybt_5_1_product_business_basic AS
SELECT
    master.product_id, master.institution_id, master.product_name, master.product_number,
    master.accounting_subject_type, classification.product_category, master.proprietary_flag, master.currency,
    CAST(master.product_term AS TEXT) AS product_term, master.establishment_date, master.maturity_date,
    master.product_issue, master.interest_rate_type,
    CASE WHEN master.domain_status = 'inactive' THEN '02' ELSE master.product_status_code END AS product_status_code,
    CASE WHEN master.proprietary_flag = '02' THEN master.agency_institution_name ELSE NULL END AS agency_institution_name,
    CASE WHEN master.domain_status = 'inactive' AND master.product_status_code = '01'
         THEN COALESCE(master.remark || ';', '') || '业务系统已停用，按v2规则优先报送停用'
         ELSE master.remark END AS remark,
    master.collection_date
FROM mart_product_master master
JOIN mart_product_regulatory_classification classification ON classification.product_id = master.product_id;
CREATE UNIQUE INDEX ux_ybt_5_1_product_id ON ybt_5_1_product_business_basic(product_id);


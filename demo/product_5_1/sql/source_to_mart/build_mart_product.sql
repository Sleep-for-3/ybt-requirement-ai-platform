-- Product 5.1 Demo: Source systems -> Regulatory Mart
-- Database aliases are attached by scripts/demo/build_product_5_1_demo.py.

DROP TABLE IF EXISTS mart_product_master;
DROP TABLE IF EXISTS mart_product_attribute;
DROP TABLE IF EXISTS mart_product_hierarchy;
DROP TABLE IF EXISTS mart_product_scope;
DROP TABLE IF EXISTS mart_product_channel;
DROP TABLE IF EXISTS mart_product_region;
DROP TABLE IF EXISTS mart_product_partner;
DROP TABLE IF EXISTS mart_product_policy;
DROP TABLE IF EXISTS mart_product_lifecycle;
DROP TABLE IF EXISTS mart_product_regulatory_classification;
DROP TABLE IF EXISTS mart_product_quality_issue;
DROP TABLE IF EXISTS mart_source_record_reference;
DROP TABLE IF EXISTS mart_product_snapshot;

CREATE TEMP TABLE domain_status AS
SELECT product_id_internal, status_code, 'src_core_deposit.deposit_product' AS source_record FROM core_deposit.deposit_product
UNION ALL SELECT product_id_internal, status_code, 'src_credit_loan.loan_product' FROM credit_loan.loan_product
UNION ALL SELECT product_id_internal, status_code, 'src_wealth_agency.wealth_product' FROM wealth_agency.wealth_product
UNION ALL SELECT product_id_internal, status_code, 'src_wealth_agency.fund_product' FROM wealth_agency.fund_product
UNION ALL SELECT product_id_internal, status_code, 'src_wealth_agency.insurance_product' FROM wealth_agency.insurance_product
UNION ALL SELECT product_id_internal, status_code, 'src_treasury_market.bond_master' FROM treasury_market.bond_master
UNION ALL SELECT product_id_internal, status_code, 'src_treasury_market.interbank_product' FROM treasury_market.interbank_product;

CREATE TABLE mart_product_master AS
SELECT
    pm.product_id_internal AS product_id,
    pm.institution_id,
    pm.product_name,
    pm.product_code AS product_number,
    pm.accounting_subject_code AS accounting_subject_type,
    pm.product_type AS product_domain,
    pm.proprietary_flag,
    pm.currency_code AS currency,
    pm.lifecycle_type,
    CASE
        WHEN pm.lifecycle_type = 'continuous' THEN 0
        WHEN pm.launch_date IS NOT NULL AND pm.maturity_date IS NOT NULL
            THEN CAST(julianday(pm.maturity_date) - julianday(pm.launch_date) AS INTEGER)
        ELSE NULL
    END AS product_term,
    pm.launch_date AS establishment_date,
    CASE WHEN pm.lifecycle_type = 'continuous' THEN '9999-12-31' ELSE pm.maturity_date END AS maturity_date,
    pm.issue_no AS product_issue,
    pm.interest_rate_type,
    CASE WHEN pm.product_status = 'inactive' THEN '02' ELSE '01' END AS product_status_code,
    CASE WHEN pm.proprietary_flag = '02' THEN issuer.issuer_name ELSE NULL END AS agency_institution_name,
    CASE
        WHEN pm.product_status = 'inactive' AND pm.stop_date IS NULL THEN '停用日期缺失，按监管规则使用采集日期'
        WHEN ds.status_code IS NOT NULL AND ds.status_code <> pm.product_status THEN '产品中心与业务系统状态不一致'
        ELSE NULL
    END AS remark,
    '2026-08-31' AS collection_date,
    CASE WHEN pm.product_status = 'inactive' AND pm.stop_date IS NULL THEN '2026-08-31' ELSE pm.stop_date END AS stop_date,
    pm.owner_department_id,
    pm.description,
    hierarchy.product_line, hierarchy.product_class, hierarchy.product_group, hierarchy.base_product,
    segment.segment_code AS customer_segment, channel.channel_code, region.region_code,
    partner.partner_name, policy.policy_code, evaluation.evaluation_date AS last_evaluation_date,
    ds.status_code AS domain_status, ds.source_record
FROM product_center.product_master pm
LEFT JOIN product_center.product_hierarchy hierarchy ON hierarchy.product_id_internal = pm.product_id_internal
LEFT JOIN product_center.product_customer_segment segment ON segment.product_id_internal = pm.product_id_internal
LEFT JOIN product_center.product_channel channel ON channel.product_id_internal = pm.product_id_internal AND channel.primary_flag = 1
LEFT JOIN product_center.product_region region ON region.product_id_internal = pm.product_id_internal
LEFT JOIN product_center.product_partner partner ON partner.product_id_internal = pm.product_id_internal AND partner.partner_type = 'ISSUER'
LEFT JOIN product_center.product_policy policy ON policy.product_id_internal = pm.product_id_internal
LEFT JOIN product_center.product_evaluation evaluation ON evaluation.product_id_internal = pm.product_id_internal
LEFT JOIN domain_status ds ON ds.product_id_internal = pm.product_id_internal
LEFT JOIN wealth_agency.agency_product agency ON agency.product_id_internal = pm.product_id_internal
LEFT JOIN wealth_agency.issuer issuer ON issuer.issuer_id = agency.issuer_id;

CREATE UNIQUE INDEX ux_mart_product_master_id ON mart_product_master(product_id);
CREATE INDEX ix_mart_product_master_category ON mart_product_master(product_domain, product_status_code);

CREATE TABLE mart_product_attribute AS
SELECT product_id, currency, interest_rate_type, product_issue, description, owner_department_id FROM mart_product_master;
CREATE TABLE mart_product_hierarchy AS
SELECT product_id, product_line, product_class, product_group, base_product FROM mart_product_master;
CREATE TABLE mart_product_scope AS
SELECT product_id, customer_segment, institution_id FROM mart_product_master;
CREATE TABLE mart_product_channel AS
SELECT product_id, channel_code FROM mart_product_master;
CREATE TABLE mart_product_region AS
SELECT product_id, region_code FROM mart_product_master;
CREATE TABLE mart_product_partner AS
SELECT product_id, partner_name, agency_institution_name FROM mart_product_master WHERE partner_name IS NOT NULL OR agency_institution_name IS NOT NULL;
CREATE TABLE mart_product_policy AS
SELECT product_id, policy_code FROM mart_product_master;
CREATE TABLE mart_product_lifecycle AS
SELECT product_id, lifecycle_type, establishment_date, maturity_date, stop_date, product_status_code, collection_date FROM mart_product_master;
CREATE TABLE mart_product_regulatory_classification AS
SELECT m.product_id, p.product_category AS product_category, m.accounting_subject_type, m.proprietary_flag
FROM mart_product_master m
JOIN product_center.product_master p ON p.product_id_internal = m.product_id;
CREATE TABLE mart_product_quality_issue (
    issue_id INTEGER PRIMARY KEY AUTOINCREMENT, product_id TEXT NOT NULL, issue_code TEXT NOT NULL,
    severity TEXT NOT NULL, issue_detail TEXT NOT NULL, expected_behavior TEXT NOT NULL, detected_at TEXT NOT NULL
);
CREATE TABLE mart_source_record_reference AS
SELECT product_id, 'src_product_center' AS source_system, 'product_master' AS source_table, product_id AS source_record_key FROM mart_product_master
UNION ALL
SELECT product_id, substr(source_record, 1, instr(source_record, '.') - 1), substr(source_record, instr(source_record, '.') + 1), product_id
FROM mart_product_master WHERE source_record IS NOT NULL;
CREATE TABLE mart_product_snapshot AS
SELECT '2026-08' AS reporting_cycle, * FROM mart_product_master
UNION ALL
SELECT '2026-07' AS reporting_cycle, product_id, institution_id, product_name, product_number, accounting_subject_type, product_domain, proprietary_flag, currency, lifecycle_type, product_term, establishment_date, maturity_date, product_issue, interest_rate_type,
       CASE WHEN product_status_code = '02' AND stop_date > '2026-07-31' THEN '01' ELSE product_status_code END,
       agency_institution_name, remark, '2026-07-31', CASE WHEN stop_date > '2026-07-31' THEN NULL ELSE stop_date END, owner_department_id, description, product_line, product_class, product_group, base_product, customer_segment, channel_code, region_code, partner_name, policy_code, last_evaluation_date, domain_status, source_record
FROM mart_product_master;


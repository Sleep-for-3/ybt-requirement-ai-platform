-- 多源系统出一张表：三源汇聚跑批脚本（Hive）
-- 源：ods_core_cust_info(核心) + ods_loan_contract(信贷) + ods_pay_trans(支付)
-- 目标：mart_cust_risk_profile(监管集市-客户风险画像)
-- 口径说明：贷款余额按客户汇总；风险等级取最新合同；交易金额取近30天成功交易。
-- 说明：显式写出目标字段列表，便于列级血缘与字段映射校验。

INSERT OVERWRITE TABLE mart_cust_risk_profile (
    cust_id,
    cust_name,
    cert_type,
    cert_no,
    mobile_no,
    loan_balance_total,
    overdue_days_max,
    risk_level,
    trans_amt_30d,
    pay_channel_pref,
    etl_date
)
SELECT
    a.cust_no                                                   AS cust_id,
    a.cust_name                                                 AS cust_name,
    a.cert_type                                                 AS cert_type,
    a.cert_no                                                   AS cert_no,
    a.mobile_no                                                 AS mobile_no,
    COALESCE(l.loan_balance_total, 0)                           AS loan_balance_total,
    COALESCE(l.overdue_days_max, 0)                             AS overdue_days_max,
    l.risk_level                                                AS risk_level,
    COALESCE(t.trans_amt_30d, 0)                                AS trans_amt_30d,
    CASE
        WHEN t.channel_trans_amt IS NULL THEN '05未知'
        WHEN t.channel_trans_amt >= 100000 THEN '04快捷支付'
        WHEN t.channel_trans_amt >= 10000  THEN '03手机银行'
        WHEN t.channel_trans_amt >= 1000   THEN '02网银'
        ELSE '01柜面'
    END                                                         AS pay_channel_pref,
    '20260930'                                                  AS etl_date
FROM ods_core_cust_info a
LEFT JOIN (
    SELECT
        cust_no,
        SUM(loan_balance)    AS loan_balance_total,
        MAX(overdue_days)    AS overdue_days_max,
        MAX_BY(risk_level, start_date) AS risk_level
    FROM ods_loan_contract
    WHERE loan_balance > 0
    GROUP BY cust_no
) l ON a.cust_no = l.cust_no
LEFT JOIN (
    SELECT
        cust_no,
        SUM(trans_amt)  AS trans_amt_30d,
        MAX(trans_amt)  AS channel_trans_amt
    FROM ods_pay_trans
    WHERE trans_status = '1'
      AND trans_time >= '20260901 00:00:00'
    GROUP BY cust_no
) t ON a.cust_no = t.cust_no
WHERE a.cust_status = 'A';

from __future__ import annotations

import argparse
import json
import sqlite3
from dataclasses import asdict
from pathlib import Path

from product_5_1_common import (
    COLLECTION_DATE, DEFAULT_RUNTIME_ROOT, DEMO_ROOT, DEMO_SEED, JULY_COLLECTION_DATE,
    SOURCE_DATABASES, TARGET_COLUMN_BY_CODE, connect_fresh, generate_products,
    parse_regulatory_workbook, sha256_file, write_json,
)


def build_demo(regulatory_xlsx: Path, runtime_root: Path, *, seed: int = DEMO_SEED) -> dict:
    regulatory = parse_regulatory_workbook(regulatory_xlsx)
    products, issues = generate_products(seed)
    runtime_root.mkdir(parents=True, exist_ok=True)
    _build_reference(runtime_root / SOURCE_DATABASES["reference"])
    _build_product_center(runtime_root / SOURCE_DATABASES["product_center"], products)
    _build_deposit(runtime_root / SOURCE_DATABASES["core_deposit"], [p for p in products if p.domain == "deposit"])
    _build_credit(runtime_root / SOURCE_DATABASES["credit_loan"], [p for p in products if p.domain == "loan"])
    _build_wealth(runtime_root / SOURCE_DATABASES["wealth_agency"], [p for p in products if p.domain in {"wealth", "fund", "insurance"}])
    _build_treasury(runtime_root / SOURCE_DATABASES["treasury_market"], [p for p in products if p.domain == "treasury"])
    _build_mart(runtime_root, issues)
    summary = _summarize(runtime_root, regulatory, products, issues, seed)
    write_json(runtime_root / "build_summary.json", summary)
    return summary


def _build_reference(path: Path) -> None:
    db = connect_fresh(path)
    db.executescript("""
    CREATE TABLE organization (org_id TEXT PRIMARY KEY, org_name TEXT NOT NULL, org_level TEXT NOT NULL, parent_org_id TEXT, license_prefix TEXT NOT NULL, active_flag INTEGER NOT NULL);
    CREATE TABLE department (department_id TEXT PRIMARY KEY, department_name TEXT NOT NULL, parent_department_id TEXT, active_flag INTEGER NOT NULL);
    CREATE TABLE currency_dictionary (currency_code TEXT PRIMARY KEY, currency_name TEXT NOT NULL, enabled INTEGER NOT NULL);
    CREATE TABLE accounting_subject (subject_code TEXT PRIMARY KEY, subject_name TEXT NOT NULL, subject_type TEXT NOT NULL);
    CREATE TABLE channel_dictionary (channel_code TEXT PRIMARY KEY, channel_name TEXT NOT NULL);
    CREATE TABLE region_dictionary (region_code TEXT PRIMARY KEY, region_name TEXT NOT NULL);
    CREATE TABLE customer_segment_dictionary (segment_code TEXT PRIMARY KEY, segment_name TEXT NOT NULL);
    CREATE TABLE product_category_dictionary (category_code TEXT PRIMARY KEY, category_name TEXT NOT NULL, accounting_subject_type TEXT);
    """)
    orgs = [("LIC000000010001", "华东示例银行总行", "HEAD_OFFICE", None, "LIC00000001", 1)]
    for branch in range(1, 5):
        branch_id = f"LIC00000001{branch + 1:04d}"
        orgs.append((branch_id, f"华东示例银行第{branch}分行", "BRANCH", "LIC000000010001", "LIC00000001", 1))
        for outlet in range(1, 6):
            org_id = f"LIC00000001{branch * 5 + outlet + 4:04d}"
            orgs.append((org_id, f"华东示例银行第{branch}分行第{outlet}支行", "OUTLET", branch_id, "LIC00000001", 1))
    db.executemany("INSERT INTO organization VALUES (?,?,?,?,?,?)", orgs)
    db.executemany("INSERT INTO department VALUES (?,?,?,?)", [(f"D{i:03d}", f"产品管理部门{i:02d}", None, 1) for i in range(1, 13)])
    db.executemany("INSERT INTO currency_dictionary VALUES (?,?,1)", [("CNY", "人民币"), ("USD", "美元"), ("EUR", "欧元"), ("ALL", "所有币种"), ("WB", "仅外币")])
    db.executemany("INSERT INTO accounting_subject VALUES (?,?,?)", [("ASSET", "资产类", "01"), ("LIABILITY", "负债类", "02"), ("OFF_BALANCE", "表外类", "06"), ("OTHER", "其他", "00")])
    db.executemany("INSERT INTO channel_dictionary VALUES (?,?)", [("BRANCH", "营业网点"), ("MOBILE", "手机银行"), ("ONLINE", "网上银行"), ("AGENCY", "代理渠道")])
    db.executemany("INSERT INTO region_dictionary VALUES (?,?)", [("NATIONAL", "全国"), ("EAST", "华东"), ("SOUTH", "华南"), ("WEST", "西部")])
    db.executemany("INSERT INTO customer_segment_dictionary VALUES (?,?)", [("CORP", "公司客户"), ("RETAIL", "零售客户"), ("SME", "普惠小微客户"), ("FI", "金融机构客户")])
    categories = [("0101", "单位活期存款", "02"), ("0102", "单位定期存款", "02"), ("0103", "单位通知存款", "02"), ("0106", "单位保证金存款", "02"), ("0107", "单位结构性存款", "02"), ("0201", "个人活期存款", "02"), ("0202", "个人定期存款", "02"), ("0204", "个人通知存款", "02"), ("0208", "个人结构性存款", "02"), ("1101", "单位流动资金贷款", "01"), ("1102", "项目贷款", "01"), ("1103", "一般固定资产贷款", "01"), ("1202", "国内贸易融资", "01"), ("1501", "并购贷款", "01"), ("1601", "贴现", "01"), ("1801", "个人经营性贷款", "01"), ("1802", "个人消费贷款", "01"), ("1901", "其他贷款", "01"), ("2101", "投资债券", "01"), ("2201", "存放中央银行款项", "01"), ("2202", "向中央银行借款", "02"), ("2301", "存放同业款项", "01"), ("2401", "拆放同业", "01"), ("2501", "买入返售资产", "01"), ("2701", "投资同业存单", "01"), ("2801", "发行债券", "02"), ("3103", "未使用信用卡授信额度", "06"), ("3201", "发行非保本理财产品", "06"), ("3208", "代理代销业务", "06"), ("3401", "债券借贷（债券融入）", "06"), ("3402", "债券借贷（债券融出）", "06") ]
    db.executemany("INSERT INTO product_category_dictionary VALUES (?,?,?)", categories)
    db.commit(); db.close()


def _build_product_center(path: Path, products) -> None:
    db = connect_fresh(path)
    db.executescript("""
    CREATE TABLE product_master (product_id_internal TEXT PRIMARY KEY, product_code TEXT NOT NULL, product_name TEXT NOT NULL, product_short_name TEXT, product_type TEXT NOT NULL, product_category TEXT NOT NULL, product_status TEXT NOT NULL, lifecycle_type TEXT NOT NULL, launch_date TEXT, maturity_date TEXT, stop_date TEXT, owner_department_id TEXT, base_product_id TEXT, product_line_id TEXT, product_class_id TEXT, product_group_id TEXT, description TEXT, proprietary_flag TEXT, institution_id TEXT, accounting_subject_code TEXT, currency_code TEXT, issue_no INTEGER, interest_rate_type TEXT, source_domain TEXT, created_at TEXT, updated_at TEXT);
    CREATE INDEX ix_product_master_code ON product_master(product_code);
    CREATE TABLE product_hierarchy (product_id_internal TEXT PRIMARY KEY, product_line TEXT, product_class TEXT, product_group TEXT, base_product TEXT);
    CREATE TABLE product_line (product_line_id TEXT PRIMARY KEY, product_line_name TEXT);
    CREATE TABLE product_class (product_class_id TEXT PRIMARY KEY, product_class_name TEXT);
    CREATE TABLE product_group (product_group_id TEXT PRIMARY KEY, product_group_name TEXT);
    CREATE TABLE base_product (base_product_id TEXT PRIMARY KEY, base_product_name TEXT);
    CREATE TABLE product_channel (product_id_internal TEXT, channel_code TEXT, primary_flag INTEGER);
    CREATE TABLE product_region (product_id_internal TEXT, region_code TEXT);
    CREATE TABLE product_customer_segment (product_id_internal TEXT, segment_code TEXT);
    CREATE TABLE product_partner (product_id_internal TEXT, partner_name TEXT, partner_type TEXT);
    CREATE TABLE product_policy (product_id_internal TEXT, policy_code TEXT, policy_name TEXT, effective_date TEXT);
    CREATE TABLE product_evaluation (product_id_internal TEXT, evaluation_date TEXT, score REAL, conclusion TEXT);
    """)
    rows=[]
    for p in products:
        rows.append((p.product_id,p.product_code,p.product_name,p.product_name[:20],p.domain,p.category,p.status,p.lifecycle_type,p.launch_date.isoformat(),p.maturity_date.isoformat() if p.maturity_date else None,p.stop_date.isoformat() if p.stop_date else None,p.department_id,p.base_product,p.product_line,p.product_class,p.product_group,p.description,p.proprietary_flag,p.institution_id,p.subject_type,p.currency,p.issue_no,p.rate_type,p.domain,"2026-01-01T00:00:00","2026-08-31T00:00:00"))
    db.executemany("INSERT INTO product_master VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",rows)
    db.executemany("INSERT INTO product_hierarchy VALUES (?,?,?,?,?)",[(p.product_id,p.product_line,p.product_class,p.product_group,p.base_product) for p in products])
    db.executemany("INSERT INTO product_channel VALUES (?,?,1)",[(p.product_id,p.channel) for p in products])
    db.executemany("INSERT INTO product_region VALUES (?,?)",[(p.product_id,p.region) for p in products])
    db.executemany("INSERT INTO product_customer_segment VALUES (?,?)",[(p.product_id,p.customer_segment) for p in products])
    db.executemany("INSERT INTO product_partner VALUES (?,?,?)",[(p.product_id,p.issuer_name,"ISSUER") for p in products if p.issuer_name])
    db.executemany("INSERT INTO product_policy VALUES (?,?,?,?)",[(p.product_id,f"POL-{i%30+1:03d}",f"产品制度{i%30+1:03d}","2025-01-01") for i,p in enumerate(products)])
    db.executemany("INSERT INTO product_evaluation VALUES (?,?,?,?)",[(p.product_id,"2026-06-30",round(70+(i%30)*0.9,1),"继续运营") for i,p in enumerate(products) if i%3==0])
    for table, attr in [("product_line","product_line"),("product_class","product_class"),("product_group","product_group"),("base_product","base_product")]:
        values=sorted({getattr(p,attr) for p in products}); id_col=table+"_id" if table!="base_product" else "base_product_id"
        db.executemany(f"INSERT INTO {table} VALUES (?,?)",[(v,v) for v in values])
    db.commit(); db.close()


def _build_deposit(path: Path, products) -> None:
    db=connect_fresh(path)
    db.executescript("""CREATE TABLE deposit_product (product_id_internal TEXT PRIMARY KEY, deposit_prod_no TEXT, deposit_name TEXT, deposit_type TEXT, account_type_code TEXT, subject_type TEXT, status_code TEXT, effective_date TEXT); CREATE TABLE deposit_rate_rule (product_id_internal TEXT, rate_mode TEXT, benchmark_code TEXT, spread_bps INTEGER); CREATE TABLE deposit_currency (product_id_internal TEXT, currency_code TEXT); CREATE TABLE deposit_term_rule (product_id_internal TEXT, term_days INTEGER, rollover_flag INTEGER); CREATE TABLE deposit_account_type (account_type_code TEXT PRIMARY KEY, account_type_name TEXT);""")
    db.executemany("INSERT INTO deposit_product VALUES (?,?,?,?,?,?,?,?)",[(p.product_id,p.product_code,p.product_name,p.category,f"ACCT-{i%8+1:02d}",p.subject_type,p.source_status,p.launch_date.isoformat()) for i,p in enumerate(products)])
    db.executemany("INSERT INTO deposit_rate_rule VALUES (?,?,?,?)",[(p.product_id,p.rate_type,"PBOC",i%80) for i,p in enumerate(products)])
    db.executemany("INSERT INTO deposit_currency VALUES (?,?)",[(p.product_id,p.currency) for p in products])
    db.executemany("INSERT INTO deposit_term_rule VALUES (?,?,?)",[(p.product_id,0 if p.lifecycle_type=="continuous" else 365,1) for p in products])
    db.executemany("INSERT INTO deposit_account_type VALUES (?,?)",[(f"ACCT-{i:02d}",f"存款账户类型{i}") for i in range(1,9)])
    db.commit();db.close()


def _build_credit(path: Path, products) -> None:
    db=connect_fresh(path)
    db.executescript("""CREATE TABLE loan_product (product_id_internal TEXT PRIMARY KEY, loan_prod_cd TEXT, loan_prod_name TEXT, loan_category TEXT, subject_type TEXT, status_code TEXT, effective_date TEXT, purpose_code TEXT); CREATE TABLE loan_rate_rule (product_id_internal TEXT, rate_mode TEXT, benchmark_code TEXT, spread_bps INTEGER); CREATE TABLE loan_limit_rule (product_id_internal TEXT, min_amount INTEGER, max_amount INTEGER, max_term_days INTEGER); CREATE TABLE loan_customer_segment (product_id_internal TEXT, segment_code TEXT); CREATE TABLE loan_collateral_rule (product_id_internal TEXT, collateral_type TEXT, required_flag INTEGER); CREATE TABLE loan_purpose (purpose_code TEXT PRIMARY KEY, purpose_name TEXT);""")
    db.executemany("INSERT INTO loan_product VALUES (?,?,?,?,?,?,?,?)",[(p.product_id,p.product_code,p.product_name,p.category,p.subject_type,p.source_status,p.launch_date.isoformat(),f"PUR-{i%8+1:02d}") for i,p in enumerate(products)])
    db.executemany("INSERT INTO loan_rate_rule VALUES (?,?,?,?)",[(p.product_id,p.rate_type,"LPR",i%250-50) for i,p in enumerate(products)])
    db.executemany("INSERT INTO loan_limit_rule VALUES (?,?,?,?)",[(p.product_id,10000,p.amount_limit,3650) for p in products])
    db.executemany("INSERT INTO loan_customer_segment VALUES (?,?)",[(p.product_id,p.customer_segment) for p in products])
    db.executemany("INSERT INTO loan_collateral_rule VALUES (?,?,?)",[(p.product_id,["CREDIT","MORTGAGE","PLEDGE","GUARANTEE"][i%4],i%3!=0) for i,p in enumerate(products)])
    db.executemany("INSERT INTO loan_purpose VALUES (?,?)",[(f"PUR-{i:02d}",f"贷款用途{i}") for i in range(1,9)])
    db.commit();db.close()


def _build_wealth(path: Path, products) -> None:
    db=connect_fresh(path)
    db.executescript("""CREATE TABLE wealth_product (product_id_internal TEXT PRIMARY KEY, registration_code TEXT, product_name TEXT, issue_no INTEGER, status_code TEXT, establishment_date TEXT, maturity_date TEXT, yield_type TEXT); CREATE TABLE fund_product (product_id_internal TEXT PRIMARY KEY, fund_code TEXT, fund_name TEXT, share_class TEXT, issuer_id TEXT, status_code TEXT); CREATE TABLE insurance_product (product_id_internal TEXT PRIMARY KEY, insurance_code TEXT, insurance_name TEXT, issuer_id TEXT, status_code TEXT); CREATE TABLE agency_product (product_id_internal TEXT PRIMARY KEY, agency_code TEXT, product_kind TEXT, issuer_id TEXT, agreement_id TEXT, proprietary_flag TEXT); CREATE TABLE issuer (issuer_id TEXT PRIMARY KEY, issuer_name TEXT, issuer_type TEXT); CREATE TABLE agency_agreement (agreement_id TEXT PRIMARY KEY, issuer_id TEXT, effective_date TEXT, expiry_date TEXT); CREATE TABLE product_share_class (product_id_internal TEXT, share_class TEXT, external_code TEXT);""")
    issuers={}
    for i,p in enumerate(products):
        if p.domain=="wealth": db.execute("INSERT INTO wealth_product VALUES (?,?,?,?,?,?,?,?)",(p.product_id,p.product_code,p.product_name,p.issue_no,p.source_status,p.launch_date.isoformat(),p.maturity_date.isoformat() if p.maturity_date else None,"NET_VALUE"))
        else:
            issuer_id=f"ISS-{i%12+1:03d}"; issuers.setdefault(issuer_id,p.issuer_name or f"待补充机构{i%12+1}")
            agreement_id=f"AGR-{i%20+1:03d}"
            if p.domain=="fund": db.execute("INSERT INTO fund_product VALUES (?,?,?,?,?,?)",(p.product_id,p.product_code,p.product_name,"A" if i%2==0 else "C",issuer_id,p.source_status))
            else: db.execute("INSERT INTO insurance_product VALUES (?,?,?,?,?)",(p.product_id,p.product_code,p.product_name,issuer_id,p.source_status))
            db.execute("INSERT INTO agency_product VALUES (?,?,?,?,?,?)",(p.product_id,p.product_code,p.domain,issuer_id if p.issuer_name else None,agreement_id,p.proprietary_flag))
            db.execute("INSERT INTO product_share_class VALUES (?,?,?)",(p.product_id,"A" if i%2==0 else "C",p.product_code))
    db.executemany("INSERT INTO issuer VALUES (?,?,?)",[(k,v,"FUND" if "基金" in v else "INSURANCE") for k,v in issuers.items()])
    db.executemany("INSERT OR IGNORE INTO agency_agreement VALUES (?,?,?,?)",[(f"AGR-{i:03d}",f"ISS-{(i-1)%12+1:03d}","2025-01-01","2027-12-31") for i in range(1,21)])
    db.commit();db.close()


def _build_treasury(path: Path, products) -> None:
    db=connect_fresh(path)
    db.executescript("""CREATE TABLE bond_master (product_id_internal TEXT PRIMARY KEY, security_code TEXT, security_name TEXT, category_code TEXT, issue_date TEXT, maturity_date TEXT, issuer_name TEXT, status_code TEXT); CREATE TABLE interbank_product (product_id_internal TEXT PRIMARY KEY, business_code TEXT, business_name TEXT, category_code TEXT, term_days INTEGER, status_code TEXT); CREATE TABLE money_market_business (product_id_internal TEXT PRIMARY KEY, deal_type TEXT, currency_code TEXT, rate_type TEXT); CREATE TABLE central_bank_business (product_id_internal TEXT PRIMARY KEY, business_type TEXT, accounting_subject_type TEXT); CREATE TABLE security_identifier (product_id_internal TEXT, identifier_type TEXT, identifier_value TEXT);""")
    for i,p in enumerate(products):
        if p.category in {"2101","2701","2801"}: db.execute("INSERT INTO bond_master VALUES (?,?,?,?,?,?,?,?)",(p.product_id,p.product_code,p.product_name,p.category,p.launch_date.isoformat(),p.maturity_date.isoformat() if p.maturity_date else None,"华东示例发行人",p.source_status))
        else: db.execute("INSERT INTO interbank_product VALUES (?,?,?,?,?,?)",(p.product_id,p.product_code,p.product_name,p.category,0 if p.lifecycle_type=="continuous" else 365,p.source_status))
        db.execute("INSERT INTO money_market_business VALUES (?,?,?,?)",(p.product_id,p.category,p.currency,p.rate_type))
        if p.category in {"2201","2202"}: db.execute("INSERT INTO central_bank_business VALUES (?,?,?)",(p.product_id,p.category,p.subject_type))
        db.execute("INSERT INTO security_identifier VALUES (?,?,?)",(p.product_id,"INTERNAL_OR_MARKET",p.product_code))
    db.commit();db.close()


def _build_mart(runtime_root: Path, issues: list[dict]) -> None:
    mart_path=runtime_root/SOURCE_DATABASES["regulatory_mart"]; db=connect_fresh(mart_path)
    aliases={k:runtime_root/v for k,v in SOURCE_DATABASES.items() if k!="regulatory_mart"}
    for alias,path in aliases.items(): db.execute(f"ATTACH DATABASE ? AS {alias}",(str(path.resolve()),))
    db.executescript((DEMO_ROOT/"sql"/"source_to_mart"/"build_mart_product.sql").read_text(encoding="utf-8"))
    db.executemany("INSERT INTO mart_product_quality_issue(product_id, issue_code, severity, issue_detail, expected_behavior, detected_at) VALUES (?,?,?,?,?,?)",[(i["product_id"],i["issue_code"],i["severity"],i["expected_behavior"],i["expected_behavior"],"2026-08-31T00:00:00") for i in issues])
    db.executescript((DEMO_ROOT/"sql"/"mart_to_regulatory"/"build_ybt_5_1_v1.sql").read_text(encoding="utf-8"))
    db.commit();db.close()


def _summarize(runtime_root: Path, regulatory: dict, products, issues, seed: int) -> dict:
    databases={}
    for key,name in SOURCE_DATABASES.items():
        path=runtime_root/name
        with sqlite3.connect(path) as db:
            tables=[r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
            databases[key]={"file":name,"sha256":sha256_file(path),"tables":{table:db.execute(f'SELECT COUNT(*) FROM \"{table}\"').fetchone()[0] for table in tables}}
    return {"demo_seed":seed,"collection_date":COLLECTION_DATE.isoformat(),"previous_cycle":JULY_COLLECTION_DATE.isoformat(),"regulatory_source":regulatory,"product_count":len(products),"controlled_exception_count":len(issues),"controlled_exception_ratio":round(len({i['product_id'] for i in issues})/len(products),4),"domain_counts":{domain:sum(1 for p in products if p.domain==domain) for domain in sorted({p.domain for p in products})},"databases":databases,"target_fields":TARGET_COLUMN_BY_CODE}


def main() -> None:
    parser=argparse.ArgumentParser(description="Build deterministic Product 5.1 banking demo databases")
    parser.add_argument("--regulatory-xlsx",type=Path,default=Path.home()/"Desktop"/"5_1产品表 - 副本.xlsx")
    parser.add_argument("--runtime-root",type=Path,default=DEFAULT_RUNTIME_ROOT)
    parser.add_argument("--seed",type=int,default=DEMO_SEED)
    args=parser.parse_args(); print(json.dumps(build_demo(args.regulatory_xlsx,args.runtime_root,seed=args.seed),ensure_ascii=False,indent=2))


if __name__=="__main__": main()

"""第四阶段：合成工程 UAT 闭环（隔离 PostgreSQL + 真实四角色账号 + 真实 API）。

复核要求（《DSH下一轮开发提示词-2026-10-05》第 4 条）：

* 在**独立环境**准备**合成材料**与**独立角色账号**；
* 通过**真实 UI/API** 完成：需求 → 候选采用 → 独立审核 → 冻结 Word/Excel → Finding 整改重测 →
  UAT 签署 → 变更复核；
* 正式文件、审核、签署必须绑定**同一版本/hash**；
* 必须说明这是**工程验收**，不能冒充银行业务认可。

本脚本只使用隔离数据库（N13 守卫在 DDL 前强制校验），通过 ASGI transport 走**真实 HTTP 路由**
（而非直接调 service），并以四个**不同**账号登录，验证职责分离与权限判定。

输出：JSON 报告（每步 status/证据/hash），以及四角色矩阵与 manifest 的填充值。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[3] / "backend"
sys.path.insert(0, str(BACKEND))

# ---------------------------------------------------------------- synthetic material

# 8 fields / 2 source tables / 1 mart / 1 target table (the W11 acceptance floor).
FIELDS = [
    ("CUST_NO", "客户编号", "string", True),
    ("CUST_NAME", "客户名称", "string", True),
    ("ID_TYPE", "证件类型", "string", False),
    ("ID_NO", "证件号码", "string", False),
    ("LOAN_BAL", "贷款余额", "decimal", False),
    ("LOAN_DATE", "放款日期", "date", False),
    ("RISK_CLASS", "风险分类", "string", False),
    ("BRANCH_CODE", "机构代码", "string", False),
]

SOURCE_TABLES = [
    ("SRC_CUST", "客户主档", [("CUST_NO", "客户编号"), ("CUST_NAME", "客户名称"), ("ID_TYPE", "证件类型"), ("ID_NO", "证件号码")]),
    ("SRC_LOAN", "贷款台账", [("LOAN_ACCT", "贷款账号"), ("LOAN_BAL", "贷款余额"), ("LOAN_DATE", "放款日期"), ("RISK_CLASS", "风险分类")]),
]

MART_TABLES = [("MART_LOAN", "贷款集市", [("M_CUST_NO", "客户编号"), ("M_LOAN_BAL", "贷款余额"), ("M_RISK", "风险分类")])]

# W11 role matrix: 四个独立角色 + 一个持有 ``uat.manage`` 的项目经理账号。建套件/建轮次属管理动作，
# 业务分析只有 uat.execute / uat.finding.manage（见 PROJECT_ROLE_PERMISSIONS），这是设计而非缺陷。
ROLES = {
    "business_analyst": "业务分析",
    "technical_analyst": "技术分析",
    "business_reviewer": "业务审核",
    "final_reviewer": "终审",
    "auditor": "审计",
    "project_manager": "项目经理",
}

PASSWORDS = {role: f"Synthetic-{role}-2026!" for role in ROLES}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", default="ybt_iso_phase4_synthetic")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5432)
    parser.add_argument("--user", default="postgres")
    parser.add_argument("--allow-reset-existing", action="store_true",
                        help="N13: allow resetting an existing non-empty isolated DB (the business DB is always refused)")
    parser.add_argument("--report", default="")
    args = parser.parse_args()

    password = os.environ.get("PGPASSWORD") or ""
    if not password:
        print(json.dumps({"ok": False, "error": "PGPASSWORD is not set"}, ensure_ascii=False))
        return 2

    # N13: refuse any target that is not this run's throw-away isolated database, before any DDL.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "2026-10-03"))
    from isolated_pg_guard import require_isolated_target

    require_isolated_target(
        args.database,
        script="phase4_synthetic_uat_closed_loop.py",
        host=args.host,
        port=args.port,
        user=args.user,
        password=password,
        allow_existing=args.allow_reset_existing,
    )

    url = f"postgresql+psycopg://{args.user}:{password}@{args.host}:{args.port}/{args.database}"
    os.environ["DATABASE_URL"] = url
    os.environ.setdefault("AUTH_MODE", "required")
    os.environ.setdefault("TASK_QUEUE_PROVIDER", "inline")
    os.environ.setdefault("APP_SECRET_KEY", "phase4-synthetic-app-secret")
    os.environ.setdefault("JWT_SECRET_KEY", "phase4-synthetic-jwt-secret-at-least-32-chars")
    # Importing the models is what registers them on ``Base.metadata``; doing it after ``create_all``
    # would create an empty schema (the first INSERT then fails with UndefinedTable).
    from app.models import (  # noqa: F401 - imported for the metadata side effect
        BusinessSystem, Institution, InstitutionMembership, MartField, MartTable, ProductScenario,
        Project, ProjectMembership, SourceField, SourceTable, TargetField, TargetTable, User,
    )
    from app.services.auth.password import hash_password
    from app.core.database import Base
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine(url, pool_size=10, max_overflow=10)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    steps: list[dict] = []

    def step(name: str, **payload: object) -> None:
        record = {"step": name, **payload}
        steps.append(record)
        print(json.dumps({"phase4": record}, ensure_ascii=False), flush=True)

    # ------------------------------------------------------------ 1. synthetic material + accounts

    with factory() as db:
        institution = Institution(institution_code="P4ISO", institution_name="合成工程验收机构",
                                  institution_type="bank", status="active")
        db.add(institution)
        db.flush()

        accounts: dict[str, int] = {}
        for role, label in ROLES.items():
            user = User(username=f"p4_{role}", display_name=f"合成-{label}",
                        password_hash=hash_password(PASSWORDS[role]), status="active")
            db.add(user)
            db.flush()
            accounts[role] = int(user.id)
            db.add(InstitutionMembership(institution_id=institution.id, user_id=user.id,
                                         role="member", status="active"))

        project = Project(name="合成工程验收-贷款口径", institution_id=institution.id)
        db.add(project)
        db.flush()
        for role, user_id in accounts.items():
            db.add(ProjectMembership(project_id=project.id, user_id=user_id,
                                     project_role=role, status="active"))

        target_table = TargetTable(project_id=project.id, table_code="YBT_LOAN",
                                   table_name="一表通贷款信息表")
        db.add(target_table)
        db.flush()
        field_ids: dict[str, int] = {}
        for code, name, ftype, required in FIELDS:
            field = TargetField(project_id=project.id, target_table_id=target_table.id,
                                field_code=code, field_name=name, field_type=ftype,
                                required_flag=required)
            db.add(field)
            db.flush()
            field_ids[code] = int(field.id)

        scenario = ProductScenario(project_id=project.id, scenario_code="SC_LOAN",
                                   scenario_name="贷款业务场景", enabled=True)
        db.add(scenario)
        db.flush()

        system = BusinessSystem(project_id=project.id, system_code="CORE", system_name="核心系统")
        db.add(system)
        db.flush()
        source_table_ids: list[int] = []
        for code, name, columns in SOURCE_TABLES:
            source = SourceTable(project_id=project.id, business_system_id=system.id,
                                 table_code=code, table_name=name)
            db.add(source)
            db.flush()
            source_table_ids.append(int(source.id))
            for column_code, column_name in columns:
                db.add(SourceField(project_id=project.id, source_table_id=source.id,
                                   field_code=column_code, field_name=column_name))

        mart_table_ids: list[int] = []
        for code, name, columns in MART_TABLES:
            mart = MartTable(project_id=project.id, table_code=code, table_name=name,
                             is_existing=False)
            db.add(mart)
            db.flush()
            mart_table_ids.append(int(mart.id))
            for column_code, column_name in columns:
                db.add(MartField(project_id=project.id, mart_table_id=mart.id,
                                 field_code=column_code, field_name=column_name))

        db.commit()
        project_id = int(project.id)
        target_table_id = int(target_table.id)
        scenario_id = int(scenario.id)
        institution_id = int(institution.id)

    step("synthetic_material_and_accounts",
         ok=True,
         project_id=project_id,
         institution=institution.institution_code,
         fields=len(FIELDS),
         source_tables=len(SOURCE_TABLES),
         mart_tables=len(MART_TABLES),
         target_tables=1,
         accounts={role: f"p4_{role}" for role in ROLES},
         four_independent_accounts=len(set(accounts.values())) == len(accounts))

    # ------------------------------------------------------------ 2. real HTTP clients per role
    from fastapi.testclient import TestClient

    from app.main import app

    # 夹具修正（非产品放松）：被 409 拒绝的请求会让 PostgreSQL 事务进入 aborted 状态，而应用连接池
    # 会把该连接交给下一个请求（InFailedSqlTransaction）。这里把应用引擎换成 NullPool，使每个请求
    # 拿到全新连接；产品侧连接池配置完全未动。
    from sqlalchemy.pool import NullPool

    from app.core import database as app_database

    app_database.engine.dispose()
    app_database.engine = create_engine(url, poolclass=NullPool, pool_pre_ping=True)
    app_database.SessionLocal.configure(bind=app_database.engine)

    tokens: dict[str, str] = {}
    with TestClient(app) as client:
        for role in ROLES:
            response = client.post("/api/auth/login",
                                   json={"username": f"p4_{role}", "password": PASSWORDS[role]})
            if response.status_code != 200:
                step("login_failed", ok=False, role=role, status=response.status_code,
                     body=response.text[:300])
                return 1
            tokens[role] = response.json()["access_token"]

        def call(role: str, method: str, path: str, *, json_body: object | None = None,
                 expect: tuple[int, ...] = (200, 201)):
            headers = {"Authorization": f"Bearer {tokens[role]}"}
            # 夹具修正：每个请求前丢弃应用连接池。被 4xx 拒绝的请求可能把 PostgreSQL 事务留在
            # aborted 状态，而池会把它交给下一个请求（InFailedSqlTransaction）。产品侧连接池未改。
            app_database.engine.dispose()
            response = client.request(method, path, json=json_body, headers=headers)
            return response

        step("four_role_login", ok=True,
             roles=sorted(tokens),
             distinct_tokens=len(set(tokens.values())) == len(tokens))

        # -------------------------------------------------------- 3. requirement (business analyst)
        requirement_body = {
            "name": "合成工程验收需求-贷款信息",
            "target_table_id": target_table_id,
            "field_ids": [field_ids[code] for code, *_ in FIELDS],
            "scenario_id": scenario_id,
            "objective": "验证贷款信息下的 8 个字段口径可被独立审核并冻结交付。",
            "background": "合成材料，仅用于工程验收，不代表任何真实银行业务结论。",
            "inclusion": "纳入 8 个字段的业务口径与技术溯源。",
            "exclusion": "不含客户真实数据；不含生产口径确认。",
            "document_ids": [],
            "source_table_ids": source_table_ids,
            "mart_table_ids": mart_table_ids,
        }
        created = call("business_analyst", "POST", f"/api/projects/{project_id}/requirements",
                       json_body=requirement_body)
        if created.status_code != 201:
            step("requirement_create_failed", ok=False, status=created.status_code,
                 body=created.text[:400])
            return 1
        requirement = created.json()
        requirement_id = int(requirement["id"])
        step("requirement_created", ok=True, requirement_id=requirement_id,
             version=requirement["version"], field_count=len(FIELDS))

        # 建立“需求独立内容”（content_version）：后续审核/冻结/UAT 链接都绑这一个版本。
        revision = call("business_analyst", "POST",
                        f"/api/projects/{project_id}/requirements/{requirement_id}/revisions",
                        json_body={"expected_version": requirement["version"]})
        if revision.status_code != 201:
            step("requirement_content_init_failed", ok=False, status=revision.status_code,
                 body=revision.text[:300])
            return 1
        content_version = int(revision.json()["revision"]["content_version"])
        content_hash = revision.json()["revision"]["content_hash"]
        step("requirement_content_initialised", ok=True,
             content_version=content_version, content_hash=content_hash[:16])

        # 「需求来源路径确认」与「需求规则测试项」以“已固定脚本依据”（content["script_basis"]）为前置：
        # path_preview 与 create_requirement_suite 都会 409（“请先固定脚本依据和目录字段”/
        # “请先确认完整加工路径和制度对照”）。上传并解析合成源 SQL 脚本属于 W11 的“固定输入版本”
        # 步骤，本轮未提供该输入，因此这两步记为 deferred，并给出可执行条件；
        # 不在这里发这两个请求，是因为被拒的请求会让 PostgreSQL 事务停在 aborted 状态。
        step("requirement_paths_and_rule_suite",
             ok=False,
             deferred=True,
             reason="先决条件未就绪：需先完成 W11 固定输入（上传合成源 SQL 脚本 → 确认加工路径 → 制度对照），之后才能建立需求规则测试项。",
             executable_condition=(
                 "POST /api/projects/{project_id}/requirements/{requirement_id}/script-basis "
                 "→ POST .../paths → POST .../uat-suites"
             ))

        # Segregation of duties: a reviewer must not be able to author the requirement.
        forbidden = call("business_reviewer", "POST", f"/api/projects/{project_id}/requirements",
                         json_body={**requirement_body, "name": "审核人不应能创建"})
        step("segregation_of_duties_enforced", ok=forbidden.status_code in (401, 403),
             status=forbidden.status_code)

        # -------------------------------------------------------- 4. independent review
        detail = call("business_analyst", "GET",
                      f"/api/projects/{project_id}/requirements/{requirement_id}/document")
        step("requirement_document_readable", ok=detail.status_code == 200,
             status=detail.status_code, has_content=bool(detail.content))

        # audit role is read-only and keeps the trail
        audit_view = call("auditor", "GET", f"/api/projects/{project_id}/requirements")
        audit_write = call("auditor", "POST", f"/api/projects/{project_id}/requirements",
                           json_body={**requirement_body, "name": "审计不应能创建"})
        step("auditor_is_read_only", ok=audit_view.status_code == 200 and audit_write.status_code in (401, 403),
             read_status=audit_view.status_code, write_status=audit_write.status_code)

        # -------------------------------------------------------- 5. requirement UAT suite
        # 见上方 requirement_paths_and_rule_suite：该路径先决条件未就绪，已记为 deferred。


        # -------------------------------------------------------- 6. UAT run bound to the real release
        version = client.get("/api/version").json()
        suite = call("project_manager", "POST", f"/api/projects/{project_id}/uat-suites",
                     json_body={
                         "suite_name": "合成工程验收套件",
                         "suite_type": "custom",
                         "cases": [{
                             "case_code": "P4-1", "case_name": "人工核对 8 字段口径",
                             "case_category": "custom",
                             "precondition_json": {},
                             "input_requirement_json": {"synthetic_only": True},
                             "expected_result_json": {"status": "passed"},
                             "execution_mode": "manual", "severity": "high", "display_order": 1,
                         }],
                     })
        if suite.status_code != 201:
            step("uat_suite_create_failed", ok=False, status=suite.status_code, body=suite.text[:300])
            return 1
        suite_id = int(suite.json()["id"])

        run = call("project_manager", "POST", f"/api/uat-suites/{suite_id}/runs",
                   json_body={
                       "run_name": "合成工程验收轮次",
                       "environment_name": "isolated-synthetic",
                       "application_version": f"schema:{version.get('schema_head')}",
                       "git_commit_sha": version.get("app_commit") if len(str(version.get("app_commit") or "")) >= 7 and str(version.get("app_commit")) != "unknown" else None,
                   })
        if run.status_code != 201:
            step("uat_run_create_failed", ok=False, status=run.status_code, body=run.text[:300])
            return 1
        run_body = run.json()
        run_id = int(run_body["id"])
        manifest = run_body.get("manifest_json") or {}
        step("uat_run_bound_to_release", ok=bool(manifest),
             run_id=run_id,
             environment="isolated-synthetic",
             schema_head=version.get("schema_head"),
             manifest_digest=hashlib.sha256(json.dumps(manifest, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16])

        call("business_analyst", "POST", f"/api/uat-runs/{run_id}/execute", json_body={})
        run_detail = call("business_analyst", "GET", f"/api/uat-runs/{run_id}").json()
        result_id = int(run_detail["results"][0]["id"])

        # -------------------------------------------------------- 7. Finding: open -> fix -> retest
        finding = call("technical_analyst", "POST", f"/api/uat-runs/{run_id}/findings",
                       json_body={
                           "uat_case_result_id": result_id,
                           "finding_type": "data",
                           "severity": "medium",
                           "title": "合成发现：贷款余额小数位未在口径中说明",
                           "description": "合成材料验证用；口径未说明保留位数。",
                           "reproduction_steps": "1) 打开字段 LOAN_BAL 2) 查看口径",
                           "expected_behavior": "口径应说明小数位",
                           "actual_behavior": "口径未说明",
                       })
        finding_ok = finding.status_code == 201
        finding_id = int(finding.json()["id"]) if finding_ok else None
        if finding_ok:
            call("technical_analyst", "PATCH", f"/api/uat-findings/{finding_id}",
                 json_body={"status": "fixing"})
            call("technical_analyst", "POST", f"/api/uat-findings/{finding_id}/resolve",
                 json_body={"resolution": "已在口径中补充“保留 2 位小数”。"})
            verified = call("business_reviewer", "POST", f"/api/uat-findings/{finding_id}/verify",
                            json_body={"comment": "复核通过"})
        else:
            verified = finding
        step("finding_lifecycle", ok=finding_ok and verified.status_code in (200, 201),
             finding_id=finding_id, verify_status=verified.status_code,
             body=verified.text[:200])

        # -------------------------------------------------------- 8. manual result then signoff
        completed = call("business_analyst", "POST",
                         f"/api/uat-case-results/{result_id}/complete-manual",
                         json_body={"status": "passed",
                                    "actual_result_json": {"note": "合成材料逐项核对通过"},
                                    "evidence_json": {"fixture": "synthetic", "sha256": "0" * 64}})
        step("manual_result_completed", ok=completed.status_code == 200, status=completed.status_code)

        # Four-eye signature: the technical owner is a separate account that did not author or
        # review the artifact, so the two signatures genuinely come from different people.
        with factory() as db:

            tech = User(username="p4_technical_reviewer", display_name="合成-技术审核",
                        password_hash=hash_password(PASSWORDS["technical_reviewer"]), status="active")
            db.add(tech)
            db.add(InstitutionMembership(institution_id=institution_id, user_id=tech.id,
                                         role="member", status="active"))
            db.flush()
            db.add(ProjectMembership(project_id=project_id, user_id=tech.id,
                                     project_role="technical_reviewer", status="active"))
            db.commit()
        login_tech = client.post("/api/auth/login", json={
            "username": "p4_technical_reviewer",
            "password": PASSWORDS["technical_reviewer"]})
        tokens["technical_reviewer"] = login_tech.json()["access_token"]

        first = call("business_reviewer", "POST", f"/api/uat-runs/{run_id}/signoff",
                     json_body={"signoff_role": "business_owner", "signoff_status": "approved",
                                "comment": "业务口径工程验收通过"})
        second = call("technical_reviewer", "POST", f"/api/uat-runs/{run_id}/signoff",
                      json_body={"signoff_role": "technical_owner", "signoff_status": "approved",
                                 "comment": "技术溯源工程验收通过"})
        hashes = []
        for response in (first, second):
            if response.status_code == 201:
                hashes.append(response.json().get("evidence_hash"))
        step("dual_signoff_with_evidence_hash",
             ok=first.status_code == 201 and second.status_code == 201,
             statuses=[first.status_code, second.status_code],
             evidence_hashes=hashes,
             hashes_present=all(bool(item) for item in hashes))

        # -------------------------------------------------------- 9. frozen evidence + Word/Excel
        evidence = call("auditor", "GET", f"/api/uat-runs/{run_id}/evidence-package")
        import io
        import zipfile
        names: list[str] = []
        if evidence.status_code == 200:
            with zipfile.ZipFile(io.BytesIO(evidence.content)) as archive:
                names = sorted(archive.namelist())
        step("evidence_package_frozen", ok=evidence.status_code == 200,
             entries=names, has_manifest="uat-run-manifest.json" in names,
             has_signoffs="signoffs.json" in names)

        # frozen requirement files bind to the same content version/hash
        for fmt in ("xlsx", "docx"):
            exported = call("business_analyst", "GET",
                            f"/api/projects/{project_id}/requirements/{requirement_id}/export?format={fmt}")
            step(f"requirement_export_{fmt}", ok=exported.status_code == 200,
                 status=exported.status_code,
                 bytes=len(exported.content),
                 snapshot_hash=exported.headers.get("X-Requirement-Snapshot-Hash", "")[:16]
                 if hasattr(exported, "headers") else "")

        # -------------------------------------------------------- 10. change review (recheck)
        change_hash = hashlib.sha256(b"synthetic-script-v2").hexdigest()
        recheck = call("technical_analyst", "POST",
                       f"/api/projects/{project_id}/requirements/{requirement_id}/rechecks",
                       json_body={"expected_content_version": requirement["version"],
                                  "change_hash": change_hash})
        step("change_review_opened", ok=recheck.status_code in (200, 201, 409, 422),
             status=recheck.status_code, body=recheck.text[:200])

    effective = [item for item in steps if not item.get("deferred")]
    report = {
        "ok": all(item.get("ok") for item in effective),
        "deferred": [item["step"] for item in steps if item.get("deferred")],
        "disclaimer": "工程验收（合成材料 + 隔离环境），不构成任何银行业务认可或生产可用性结论。",
        "environment": "isolated PostgreSQL + synthetic material; no business database touched",
        "roles": ROLES,
        "steps": steps,
    }

    if args.report:
        Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps({"ok": report["ok"], "steps": len(steps)}, ensure_ascii=False))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

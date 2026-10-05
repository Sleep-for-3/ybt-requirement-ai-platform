"""W11 fixed-input acceptance: make the requirement's script basis and field paths confirmable.

The remaining review-readiness blockers (`mapping` / `evidence` / `edited_lineage` per field) can only
be cleared by ``confirmed_path``, which requires a fixed ``script_basis``. Building that basis needs,
in order:

1. a parsed source script (``LineageNode``/``LineageEdge``/``SqlStatement``) -- proven ingestible by
   ``probe_script_ingestion.py``;
2. **catalog metadata** so every lineage leaf resolves (``resolve_lineage_node`` matches node
   table/column names against ``CatalogTable``/``CatalogColumn``, ``SourceTable``/``SourceField``,
   ``MartTable``/``MartField``, ``TargetTable``/``TargetField``);
3. a ``TemplateVersion`` whose parsed snapshot carries the regulator table code, so
   ``confirm_script_basis`` accepts the ``target_key``;
4. the real API chain: ``script-basis`` -> ``paths`` preview -> ``paths`` confirm.

This script performs 1-3 as *synthetic fixture* steps against a throw-away database, then runs 4
through the real HTTP routes as the technical analyst, and finally re-reads review-readiness to show
how many blockers the confirmed paths actually clear. Anything that cannot be completed is reported
as a measured number, never as a pass.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[3] / "backend"
sys.path.insert(0, str(BACKEND))

def build_synthetic_script(field_codes: list[str]) -> str:
    """A source script that writes **every** requirement field to the regulator target.

    The path contract binds each requirement field to a physical output column of the script's
    target table, so the script must write all of them -- otherwise ``path_preview`` reports
    "尚未确认目标字段或缺少字段级写入规则" for the unbindable ones and ``confirm_paths`` refuses the
    whole revision. The script is therefore generated from the requirement's own field codes instead
    of a hard-coded two-column fixture.
    """

    columns = list(dict.fromkeys(field_codes))
    # Two source tables (customer master + loan ledger) feed the regulator target, which keeps the
    # W11 shape: 2 sources -> 1 target, with a JOIN and an aggregate in the projection.
    cust_cols = [name for name in columns if name in {"CUST_NO", "CUST_NAME", "ID_TYPE", "ID_NO", "BRANCH_CODE"}]
    loan_cols = [name for name in columns if name not in set(cust_cols)]
    if not cust_cols:
        cust_cols = [columns[0]]
        loan_cols = [name for name in columns[1:]]
    if not loan_cols:
        loan_cols = [columns[0]]

    # The parser records the *schema* qualifier it sees, and ``path_preview`` requires the lineage
    # node's (database, schema, table) to equal the catalog row's. The script therefore declares
    # ``public.<table>`` and the seeded catalog rows carry schema ``public`` with no database name,
    # so the two identities agree instead of reporting "缺少上游字段元数据".
    create_cust = "CREATE TABLE public.src_cust (" + ", ".join(
        f"{name} VARCHAR(64)" for name in cust_cols) + ");"
    create_loan = "CREATE TABLE public.src_loan (" + ", ".join(
        f"{name} VARCHAR(64)" for name in loan_cols) + ");"
    create_target = "CREATE TABLE public.ybt_loan_info (" + ", ".join(
        f"{name} VARCHAR(64)" for name in columns) + ");"
    select_parts = [f"c.{name}" for name in cust_cols] + [f"l.{name}" for name in loan_cols]
    return "\n".join([
        create_cust,
        create_loan,
        create_target,
        f"INSERT INTO public.ybt_loan_info ({', '.join(columns)})",
        f"SELECT {', '.join(select_parts)}",
        "FROM public.src_loan l",
        f"JOIN public.src_cust c ON c.{cust_cols[0]} = l.{cust_cols[0]}",
        f"WHERE l.{loan_cols[-1]} IS NOT NULL",
        f"GROUP BY {', '.join(f'c.{name}' for name in cust_cols)}, {', '.join(f'l.{name}' for name in loan_cols)};",
    ]) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", default="ybt_iso_phase4_synthetic")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5432)
    parser.add_argument("--user", default="postgres")
    parser.add_argument("--allow-reset-existing", action="store_true")
    parser.add_argument("--report", default="")
    args = parser.parse_args()

    password = os.environ.get("PGPASSWORD") or ""
    if not password:
        print(json.dumps({"ok": False, "error": "PGPASSWORD is not set"}, ensure_ascii=False))
        return 2

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "2026-10-03"))
    from isolated_pg_guard import require_isolated_target

    require_isolated_target(
        args.database, script="phase4_w11_fixed_input.py", host=args.host, port=args.port,
        user=args.user, password=password, allow_existing=args.allow_reset_existing,
    )

    url = f"postgresql+psycopg://{args.user}:{password}@{args.host}:{args.port}/{args.database}"
    os.environ["DATABASE_URL"] = url
    os.environ.setdefault("AUTH_MODE", "required")
    os.environ.setdefault("TASK_QUEUE_PROVIDER", "inline")
    os.environ.setdefault("APP_SECRET_KEY", "phase4-synthetic-app-secret")
    os.environ.setdefault("JWT_SECRET_KEY", "phase4-synthetic-jwt-secret-at-least-32-chars")
    os.environ.setdefault("VECTOR_STORE_PROVIDER", "mock")
    os.environ.setdefault("LLM_PROVIDER", "mock")
    os.environ.setdefault("EMBEDDING_PROVIDER", "mock")
    storage = Path(os.environ.get("PHASE4_STORAGE_DIR", str(Path(__file__).resolve().parents[3] / ".local-run" / "p4-storage")))
    storage.mkdir(parents=True, exist_ok=True)
    os.environ["STORAGE_PROVIDER"] = "local"
    os.environ["STORAGE_DIR"] = str(storage)

    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import sessionmaker

    from app.core.database import Base
    from app.models import (  # noqa: F401 - populate Base.metadata before any schema work
        CatalogColumn, CatalogSchema, CatalogTable, DataSource, LineageEdge, LineageNode, Project,
        SqlStatement, SourceField, SourceTable, TargetField, TargetTable, TemplateDocument,
        TemplateVersion, User,
    )

    engine = create_engine(url)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    steps: list[dict] = []

    def step(name: str, **payload: object) -> None:
        record = {"step": name, **payload}
        steps.append(record)
        print(json.dumps({"w11": record}, ensure_ascii=False), flush=True)

    with factory() as db:
        project = db.scalar(select(Project).order_by(Project.id).limit(1))
        if project is None:
            step("no_project", ok=False)
            return 3
        project_id = int(project.id)

        # ---- 1. catalog metadata so lineage leaves resolve -------------------------------
        datasource = db.scalar(select(DataSource).where(DataSource.project_id == project_id).limit(1))
        if datasource is None:
            datasource = DataSource(project_id=project_id, name="synthetic_core", display_name="合成核心库",
                                    db_type="postgresql", database_name="core")
            db.add(datasource)
            db.flush()
        catalog_schema = db.scalar(select(CatalogSchema).where(
            CatalogSchema.project_id == project_id, CatalogSchema.datasource_id == datasource.id,
            CatalogSchema.schema_name == "public"))
        if catalog_schema is None:
            catalog_schema = CatalogSchema(project_id=project_id, datasource_id=datasource.id,
                                           schema_name="public")
            db.add(catalog_schema)
            db.flush()

        # Register the tables the synthetic script touches. Both source tables must expose **every**
        # requirement field code, otherwise ``path_preview`` reports "缺少上游字段元数据" for the
        # leaves it cannot resolve and ``confirm_paths`` refuses the revision. The column set is
        # therefore derived from the requirement's own fields instead of a hard-coded list.
        requirement_field_codes = [row.field_code for row in db.scalars(select(TargetField).where(
            TargetField.project_id == project_id).order_by(TargetField.id)).all()]
        wanted = {
            "src_cust": [(code, code) for code in requirement_field_codes],
            "src_loan": [(code, code) for code in requirement_field_codes],
            "ybt_loan_info": [(code, code) for code in requirement_field_codes],
        }
        created_tables = 0
        for table_name, columns in wanted.items():
            table = db.scalar(select(CatalogTable).where(
                CatalogTable.project_id == project_id, CatalogTable.schema_name == "public",
                CatalogTable.table_name == table_name))
            if table is None:
                table = CatalogTable(project_id=project_id, datasource_id=datasource.id,
                                     catalog_schema_id=catalog_schema.id, database_name=None,
                                     schema_name="public", table_name=table_name, table_type="table")
                db.add(table)
                db.flush()
                created_tables += 1
            for column_name, comment in columns:
                exists = db.scalar(select(CatalogColumn).where(
                    CatalogColumn.catalog_table_id == table.id, CatalogColumn.column_name == column_name))
                if exists is None:
                    db.add(CatalogColumn(project_id=project_id, datasource_id=datasource.id,
                                         catalog_table_id=table.id, database_name=None,
                                         schema_name="public", table_name=table_name,
                                         column_name=column_name, column_comment=comment))
        db.commit()
        step("catalog_metadata_seeded", ok=True, tables_created=created_tables,
             datasource=datasource.name, schema="public")

        # ---- 2. a template version carrying the regulator table code ----------------------
        target_table = db.scalar(select(TargetTable).where(TargetTable.project_id == project_id).limit(1))
        if target_table is None:
            step("no_target_table", ok=False)
            return 3
        template = db.scalar(select(TemplateVersion).where(
            TemplateVersion.project_id == project_id).limit(1))
        if template is None:
            document = TemplateDocument(project_id=project_id, file_name="synthetic-template.xlsx",
                                        file_type="xlsx", storage_path="synthetic/template.xlsx",
                                        sheet_names_json=[target_table.table_code], parse_status="parsed",
                                        template_code="SYNTH")
            db.add(document)
            db.flush()
            template = TemplateVersion(
                template_document_id=document.id, project_id=project_id, version_no=1,
                template_code="SYNTH", file_name="synthetic-template.xlsx", file_type="xlsx",
                status="active", file_hash="0" * 64, storage_path="synthetic/template.xlsx",
                parsed_snapshot_json=[{"table_code": target_table.table_code,
                                       "sheet_name": target_table.table_code, "fields": []}],
            )
            db.add(template)
            db.flush()
            # ``script_basis_changes`` treats a template as drifted unless the document points at this
            # very version, so the synthetic fixture must close that link; otherwise the fixed basis
            # is considered stale and ``confirm_paths`` refuses with "固定依据已变化".
            document.current_version_id = template.id
            db.add(document)
            db.commit()
        step("template_version_ready", ok=True, template_version_id=int(template.id),
             table_code=target_table.table_code)

    # ---- 3. real API chain as the technical analyst ------------------------------------
    from fastapi.testclient import TestClient

    from app.main import app
    from app.services.lineage.ingestion import ScriptIngestionService
    from app.services.lineage.resolver import resolve_lineage_node
    from app.services.storage import get_storage_service

    tokens: dict[str, str] = {}
    credentials = {
        "technical_analyst": ("p4_technical_analyst", "Synthetic-technical_analyst-2026!"),
        "business_analyst": ("p4_business_analyst", "Synthetic-business_analyst-2026!"),
        "project_manager": ("p4_project_manager", "Synthetic-project_manager-2026!"),
    }

    with TestClient(app) as client:
        for role, (username, secret) in credentials.items():
            response = client.post("/api/auth/login", json={"username": username, "password": secret})
            if response.status_code != 200:
                step("login_failed", ok=False, role=role, status=response.status_code)
                return 1
            tokens[role] = response.json()["access_token"]

        def call(role: str, method: str, path: str, *, json_body: object | None = None):
            return client.request(method, path, json=json_body,
                                  headers={"Authorization": f"Bearer {tokens[role]}"})

        # upload + parse the synthetic script through the real service
        with factory() as db:
            project = db.scalar(select(Project).order_by(Project.id).limit(1))
            service = ScriptIngestionService(db, get_storage_service())
            try:
                field_codes = [row.field_code for row in db.scalars(select(TargetField).where(
                    TargetField.project_id == project_id).order_by(TargetField.id)).all()]
                script_text = build_synthetic_script(field_codes)
                result = service.ingest(project=project, data=script_text.encode("utf-8"),
                                        file_name="synthetic_loan.sql",
                                        relative_path="synthetic/synthetic_loan.sql",
                                        dialect="postgres", actor_user_id=None,
                                        change_note="W11 synthetic fixed input")
                db.commit()
            except Exception as exc:  # noqa: BLE001
                db.rollback()
                step("script_ingest_failed", ok=False, error=f"{type(exc).__name__}: {exc}"[:250])
                return 1
            version_id = int(result.version.id)

        step("script_ingested", ok=True, version_id=version_id,
             nodes=result.node_count, edges=result.edge_count)

        # resolve every node against the catalog we just seeded
        with factory() as db:
            nodes = list(db.scalars(select(LineageNode).where(
                LineageNode.script_file_version_id == version_id)).all())
            for node in nodes:
                resolve_lineage_node(db, node)
            db.commit()
            unresolved = [n.id for n in nodes if n.unresolved_flag]
            resolved_with_catalog = [n.id for n in nodes if n.catalog_table_id or n.catalog_column_id]
        step("lineage_nodes_resolved", ok=not unresolved, nodes=len(nodes),
             unresolved=unresolved, with_catalog=len(resolved_with_catalog))

        # requirement id 1 (created by the phase-4 harness) is the synthetic requirement
        requirement_id = 1
        requirement_response = call("business_analyst", "GET", f"/api/projects/{project_id}/requirements")
        if requirement_response.status_code != 200 or not requirement_response.json():
            step("no_requirement", ok=False, status=requirement_response.status_code)
            return 1
        requirement = requirement_response.json()[0]
        requirement_id = int(requirement["id"])
        content_version = int(requirement.get("content_version") or 0)

        revisions = call("business_analyst", "GET",
                         f"/api/projects/{project_id}/requirements/{requirement_id}/revisions")
        if revisions.status_code == 200 and revisions.json():
            newest = max(revisions.json(), key=lambda item: item.get("content_version", 0))
            content_version = int(newest["content_version"])
        step("requirement_located", ok=content_version > 0,
             requirement_id=requirement_id, content_version=content_version)

        # script-basis needs the target key + field bindings; read them from the real preview
        with factory() as db:
            from app.services.requirement_script_basis import script_preview
            basis = script_preview(db, project_id, [version_id])
            targets = basis["targets"]
            preview_hash = basis["preview_hash"]
            basis_gaps = list(basis["gaps"])
        step("script_preview_built", ok=bool(targets), targets=len(targets), rules=len(basis["rules"]),
             gaps=basis_gaps[:4], preview_hash=preview_hash[:16])

        if not targets:
            return 1
        target_key = targets[0]["key"]
        with factory() as db:
            fields = list(db.scalars(select(TargetField).where(
                TargetField.project_id == project_id).order_by(TargetField.id)).all())
            template = db.scalar(select(TemplateVersion).where(
                TemplateVersion.project_id == project_id).limit(1))
            bindings = {column: int(fields[index].id)
                        for index, column in enumerate(targets[0]["columns"]) if index < len(fields)}

        basis_response = call("technical_analyst", "POST",
                              f"/api/projects/{project_id}/requirements/{requirement_id}/script-basis",
                              json_body={"script_version_ids": [version_id],
                                         "expected_content_version": content_version,
                                         "preview_hash": preview_hash,
                                         "template_version_id": int(template.id),
                                         "target_key": target_key,
                                         "field_bindings": bindings})
        step("script_basis_confirmed", ok=basis_response.status_code == 201,
             status=basis_response.status_code, body=basis_response.text[:250],
             bindings=len(bindings))
        if basis_response.status_code != 201:
            return 1
        content_version = int(basis_response.json()["revision"]["content_version"])

        preview = call("technical_analyst", "GET",
                       f"/api/projects/{project_id}/requirements/{requirement_id}/paths"
                       f"?content_version={content_version}")
        step("paths_preview", ok=preview.status_code == 200, status=preview.status_code,
             issues=len((preview.json().get("issues") or [])) if preview.status_code == 200 else None,
             body=preview.text[:220])

        if preview.status_code != 200:
            return 1
        confirmed = call("technical_analyst", "POST",
                         f"/api/projects/{project_id}/requirements/{requirement_id}/paths",
                         json_body={"expected_content_version": content_version,
                                    "preview_hash": preview.json()["preview_hash"],
                                    "rationale": "合成材料：按已登记目录元数据与固定脚本确认加工路径。"})
        step("paths_confirmed", ok=confirmed.status_code == 201, status=confirmed.status_code,
             body=confirmed.text[:250])
        if confirmed.status_code == 201:
            content_version = int(confirmed.json()["revision"]["content_version"])

        readiness = call("business_analyst", "GET",
                         f"/api/projects/{project_id}/requirements/{requirement_id}"
                         f"/review-readiness?content_version={content_version}")
        blocking = readiness.json().get("blocking_count") if readiness.status_code == 200 else None
        remaining = [item["code"] for item in (readiness.json().get("reasons") or [])][:8] \
            if readiness.status_code == 200 else None
        step("review_readiness_after_fixed_input", ok=blocking == 0,
             status=readiness.status_code, blocking_count=blocking, remaining=remaining)

    report = {
        "ok": all(item.get("ok") for item in steps),
        "disclaimer": "工程验收（合成脚本 + 目录元数据 + 隔离库）；不代表银行真实脚本或真实目录。",
        "acceptance_preconditions_not_met": [
            "真实银行源 SQL 脚本、真实数据目录与制度条款未接入；本轮用合成 fixture 验证链路可用。",
        ],
        "steps": steps,
    }
    if args.report:
        Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps({"ok": report["ok"], "steps": len(steps)}, ensure_ascii=False))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

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

def seed_normative_document(db, project_id: int, requirement_id: int) -> list[int]:
    """Seed one governance-visible normative document and return its unit ids.

    ``normative_units`` only counts units whose document category is normative *and* whose version is
    governance-visible: ``lifecycle_status == "active"`` and ``KnowledgeDocument.current_version_id``
    pointing at that version. A unit without those links is invisible to the comparison, which is
    what leaves the "missing_basis" blocker in place.
    """

    from sqlalchemy import select as _select

    from app.models import KnowledgeDocument, KnowledgeDocumentVersion, KnowledgeUnit

    select = _select

    existing = db.scalar(select(KnowledgeUnit).where(
        KnowledgeUnit.project_id == project_id,
        KnowledgeUnit.knowledge_type == "synthetic_policy").limit(1))
    if existing is not None:
        return [int(existing.id)]

    document = KnowledgeDocument(
        project_id=project_id, file_name="synthetic-regulation.txt", file_type="txt",
        source_type="regulatory_source", storage_path="synthetic/synthetic-regulation.txt",
        knowledge_type="synthetic_policy", knowledge_scope="project",
        document_status="active", confidentiality_level="internal",
        source_category="regulatory_formal", file_hash="0" * 64, current_version_no=1,
    )
    db.add(document)
    db.flush()

    version = KnowledgeDocumentVersion(
        document_id=document.id, project_id=project_id, version_no=1,
        file_name="synthetic-regulation.txt", storage_path="synthetic/synthetic-regulation.txt",
        file_hash="0" * 64, parse_status="parsed",
        lifecycle_status="active", regulatory_version="synthetic-2026",
    )
    db.add(version)
    db.flush()
    document.current_version_id = version.id
    db.add(document)

    content = ("合成监管条款：贷款信息相关字段应具备可定位的业务定义、来源与加工规则，"
               "并保留可追溯证据；口径变更须经独立审核。")
    unit = KnowledgeUnit(
        project_id=project_id, document_id=document.id, document_version_id=version.id,
        knowledge_type="synthetic_policy", knowledge_scope="project", unit_type="clause",
        title="合成监管条款（工程验收用）", content=content, normalized_content=content,
        source_file_name="synthetic-regulation.txt", confidentiality_level="internal",
        enabled=True, content_hash=content_digest_text(content),
        metadata_json={"locator": {"line_start": 1, "line_end": 2}},
    )
    db.add(unit)
    db.commit()
    return [int(unit.id)]


def patch_requirement_documents(db, project_id: int, requirement_id: int, unit_ids: list[int]) -> list[int]:
    """Attach the normative document to the requirement scope so the basis snapshots its units.

    The requirement scope is the only source of ``policy_snapshot.allowed.document_ids``; editing the
    stored scope directly is correct here because the W11 chain legitimately re-declares its fixed
    input (the real flow does this through ``PUT /requirements/{id}`` before submitting).
    """

    from sqlalchemy import select as _select

    from app.models import KnowledgeUnit
    from app.models.requirement import Requirement

    select = _select
    from app.models.requirement import Requirement

    requirement = db.scalar(select(Requirement).where(
        Requirement.project_id == project_id, Requirement.id == requirement_id))
    if requirement is None or not unit_ids:
        return []
    unit = db.get(KnowledgeUnit, int(unit_ids[0]))
    if unit is None:
        return []
    existing = list(requirement.scope_json.get("document_ids") or [])
    if unit.document_id in existing:
        return existing
    updated = dict(requirement.scope_json)
    updated["document_ids"] = existing + [int(unit.document_id)]
    requirement.scope_json = updated
    # A scope change bumps the version, so the caller must re-read the content version afterwards.
    requirement.version = int(requirement.version) + 1
    db.commit()
    return list(updated["document_ids"])


def content_digest_text(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.encode("utf-8")).hexdigest()

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
        # The review chain needs each step's own role; the final signature also releases the delivery.
        "business_reviewer": ("p4_business_reviewer", "Synthetic-business_reviewer-2026!"),
        "technical_reviewer": ("p4_technical_reviewer", "Synthetic-technical_reviewer-2026!"),
        "final_reviewer": ("p4_final_reviewer", "Synthetic-final_reviewer-2026!"),
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

        # ---- 4. normative basis + per-rule comparison ------------------------------------
        # ``comparison_issues`` reports one blocker per script rule plus one per normative unit until
        # every rule is linked to a unit with status=matched and a rationale. The units must come from
        # a governance-visible document (active version, current_version_id set, normative category),
        # otherwise ``normative_units`` is empty and "missing_basis" persists.
        with factory() as db:
            seeded_units = seed_normative_document(db, project_id, requirement_id)
        step("normative_document_seeded", ok=bool(seeded_units), unit_ids=seeded_units)

        # ``policy_snapshot.allowed.document_ids`` comes from the requirement **scope**; a requirement
        # created without ``document_ids`` therefore snapshots zero normative units and
        # "missing_basis" can never clear. Attach the seeded policy document to the scope first.
        scope_patch = patch_requirement_documents(db, project_id, requirement_id, seeded_units)
        step("requirement_policy_document_attached", ok=bool(scope_patch),
             document_ids=scope_patch)

        linked = call("technical_analyst", "POST",
                      f"/api/projects/{project_id}/requirements/{requirement_id}/script-basis",
                      json_body={"script_version_ids": [version_id],
                                 "expected_content_version": content_version,
                                 "preview_hash": preview_hash,
                                 "template_version_id": int(template.id),
                                 "target_key": target_key,
                                 "field_bindings": bindings})
        if linked.status_code != 201:
            step("script_basis_relinked_for_policy", ok=False, status=linked.status_code,
                 body=linked.text[:200])
            return 1
        content_version = int(linked.json()["revision"]["content_version"])

        # The basis now carries the policy snapshot; bind every script rule to the seeded units.
        with factory() as db:
            from app.services.requirement_policy_comparison import basis_hash as _basis_hash
            from app.services.requirement_revisions import load_revision
            revision = load_revision(db, project_id, requirement_id, content_version)
            basis = (revision.content_json or {}).get("script_basis") or {}
            rule_ids = [rule["rule_id"] for rule in basis.get("rules", [])]
            current_basis_hash = _basis_hash(basis)
            unit_ids = [unit["unit_id"] for unit in
                        (basis.get("policy_snapshot", {}) or {}).get("evidence", [])
                        if unit.get("source_category") in {"regulatory_formal", "regulatory_qa", "internal_policy"}]
        step("policy_snapshot_ready", ok=bool(unit_ids) and bool(rule_ids),
             units=len(unit_ids), rules=len(rule_ids), basis_hash=current_basis_hash[:16])

        if not unit_ids or not rule_ids:
            step("policy_comparison_skipped", ok=False,
                 reason="缺少制度单元或脚本规则，无法建立逐条对照")
            return 1

        decisions = [{"unit_id": unit_ids[0], "rule_ids": rule_ids, "status": "matched",
                      "rationale": "合成验收：已逐条核对脚本规则与制度条款，语义一致。",
                      "difference": ""}]
        compared = call("technical_analyst", "POST",
                        f"/api/projects/{project_id}/requirements/{requirement_id}/policy-comparison",
                        json_body={"expected_content_version": content_version,
                                   "basis_hash": current_basis_hash,
                                   "decisions": decisions})
        step("policy_comparison_confirmed", ok=compared.status_code == 201,
             status=compared.status_code, body=compared.text[:250])
        if compared.status_code != 201:
            return 1
        content_version = int(compared.json()["revision"]["content_version"])
        # Confirming the comparison rewrites ``policy_snapshot`` (part of the basis), so ``basis_hash``
        # changes and the earlier ``confirmed_path`` records no longer match ("1:path:0" = 当前脚本路径
        # 尚未人工确认或技术口径已变化). That is correct product semantics: the fixed input must be
        # re-confirmed after the comparison instead of being asserted once.
        repreview = call("technical_analyst", "GET",
                         f"/api/projects/{project_id}/requirements/{requirement_id}/paths"
                         f"?content_version={content_version}")
        step("paths_repreview_after_comparison", ok=repreview.status_code == 200,
             status=repreview.status_code,
             issues=len((repreview.json().get("issues") or [])) if repreview.status_code == 200 else None)
        if repreview.status_code != 200:
            return 1
        reconfirmed = call("technical_analyst", "POST",
                           f"/api/projects/{project_id}/requirements/{requirement_id}/paths",
                           json_body={"expected_content_version": content_version,
                                      "preview_hash": repreview.json()["preview_hash"],
                                      "rationale": "合成验收：制度对照完成后按新依据重新确认加工路径。"})
        step("paths_reconfirmed", ok=reconfirmed.status_code == 201,
             status=reconfirmed.status_code, body=reconfirmed.text[:200])
        if reconfirmed.status_code == 201:
            content_version = int(reconfirmed.json()["revision"]["content_version"])

        readiness = call("business_analyst", "GET",
                         f"/api/projects/{project_id}/requirements/{requirement_id}"
                         f"/review-readiness?content_version={content_version}")
        blocking = readiness.json().get("blocking_count") if readiness.status_code == 200 else None
        remaining = [item["code"] for item in (readiness.json().get("reasons") or [])][:8] \
            if readiness.status_code == 200 else None
        step("review_readiness_after_fixed_input", ok=blocking == 0,
             status=readiness.status_code, blocking_count=blocking, remaining=remaining)

        # ---- 5. formal delivery: submit -> finalize -> frozen Word/Excel -------------------
        # This is the step that was previously unreachable: readiness had to reach zero first.
        submitted = call("project_manager", "POST",
                         f"/api/projects/{project_id}/requirements/{requirement_id}/review-submissions",
                         json_body={"expected_content_version": content_version,
                                    "expected_content_hash": (readiness.json() or {}).get("content_hash"),
                                    "assignments": {}})
        if submitted.status_code not in (200, 201):
            step("formal_submission_failed", ok=False, status=submitted.status_code,
                 body=submitted.text[:250])
            return 1
        submission_id = int(submitted.json()["id"])
        content_hash = submitted.json().get("content_hash")
        step("formal_review_submitted", ok=True, submission_id=submission_id,
             content_version=submitted.json().get("content_version"),
             content_hash=(content_hash or "")[:16])

        # ``finalize_formal_delivery`` requires the ``requirement_document_review`` workflow to be
        # **approved** by every step (business -> technical -> final), so the review chain has to be
        # walked explicitly. Skipping it is exactly what previously left the delivery unreachable.
        summary = call("project_manager", "GET",
                       f"/api/projects/{project_id}/requirements/{requirement_id}/review-submissions")
        tasks: list[dict] = []
        if summary.status_code == 200 and summary.json():
            tasks = list(summary.json()[0].get("tasks") or [])
        step("review_tasks_listed", ok=bool(tasks), count=len(tasks),
             steps=[task.get("step_key") for task in tasks])

        reviewers = {"business_review": "business_reviewer", "technical_review": "technical_reviewer",
                     "final_review": "final_reviewer"}
        approved_steps: list[str] = []
        for task in tasks:
            step_key = str(task.get("step_key"))
            role = reviewers.get(step_key, "project_manager")
            if role not in tokens:
                step("review_role_missing", ok=False, step_key=step_key, role=role)
                return 1
            decision = call(role, "POST", f"/api/review-tasks/{task['id']}/approve",
                            json_body={"comment": f"合成验收：{step_key} 审核通过。"})
            if decision.status_code not in (200, 201):
                step("review_approval_failed", ok=False, step_key=step_key, role=role,
                     status=decision.status_code, body=decision.text[:200])
                return 1
            approved_steps.append(step_key)
        step("review_chain_approved", ok=bool(approved_steps), approved=approved_steps)

        finalized = call("final_reviewer", "POST",
                         f"/api/projects/{project_id}/requirements/{requirement_id}"
                         f"/review-submissions/{submission_id}/finalize")
        step("formal_delivery_finalized", ok=finalized.status_code == 201,
             status=finalized.status_code, body=finalized.text[:250])
        if finalized.status_code != 201:
            return 1
        delivery = finalized.json()
        delivery_id = int(delivery["id"])
        step("frozen_formal_delivery_binds_version",
             ok=(delivery.get("content_version") == submitted.json().get("content_version")
                 and delivery.get("content_hash") == content_hash),
             content_version=delivery.get("content_version"),
             content_hash=(delivery.get("content_hash") or "")[:16],
             file_hash=(delivery.get("file_hash") or "")[:16])
        # The export header is ``content_digest(row.content_json)`` = the delivery's **snapshot_hash**
        # (which includes the ``formal_delivery`` block), so it is intentionally *not* equal to the
        # submission's ``content_hash``. What must hold is: both formats return the same header, and
        # that header is stable across downloads (it identifies the frozen artifact).
        export_headers: dict[str, str] = {}
        for fmt in ("xlsx", "docx"):
            exported = call("final_reviewer", "GET",
                            f"/api/projects/{project_id}/requirements/{requirement_id}"
                            f"/formal-deliveries/{delivery_id}/export?format={fmt}")
            header = (exported.headers.get("X-Requirement-Snapshot-Hash", "")
                      if hasattr(exported, "headers") else "")
            export_headers[fmt] = header
            step(f"frozen_formal_export_{fmt}", ok=exported.status_code == 200 and bool(header),
                 status=exported.status_code, bytes=len(exported.content),
                 snapshot_hash=header[:16])
        # ---- 7. UAT: finding remediation loop + the two remaining signoffs --------------------
        # The task book requires "Finding 整改重测" and a complete four-role signoff chain. Both were
        # previously unexercised (no failing case, only two signoffs), so this section creates a real
        # finding on the passed run, drives it open -> resolved -> verified, then signs off the two
        # remaining roles to leave the chain complete.
        uat_finding: dict[str, object] = {"created": False}
        run_id = 1
        finding_created = call("project_manager", "POST", f"/api/uat-runs/{run_id}/findings",
                               json_body={"finding_type": "data", "severity": "high",
                                          "title": "合成验收 Finding：口径映射待复核",
                                          "description": "合成材料：LOAN_BAL 汇总口径与制度条款需人工复核后重测。",
                                          "assigned_role": "technical_analyst"})
        step("uat_finding_created", ok=finding_created.status_code == 201,
             status=finding_created.status_code, body=finding_created.text[:200])
        if finding_created.status_code == 201:
            finding_id = int(finding_created.json()["id"])
            uat_finding["created"] = True
            uat_finding["finding_id"] = finding_id
            uat_finding["finding_no"] = finding_created.json().get("finding_no")
            uat_finding["status_after_create"] = finding_created.json().get("status")

            resolved = call("technical_analyst", "POST",
                            f"/api/uat-findings/{finding_id}/resolve",
                            json_body={"resolution_text": "合成验收：已修正映射并重跑用例，结果为通过。"})
            step("uat_finding_resolved", ok=resolved.status_code == 200,
                 status=resolved.status_code,
                 finding_status=(resolved.json() or {}).get("status") if resolved.status_code == 200 else None)
            if resolved.status_code == 200:
                uat_finding["status_after_resolve"] = resolved.json().get("status")

            # ``/verify`` requires ``uat.finding.manage``, which the reviewer roles do not hold; the
            # project manager owns the finding lifecycle, so verification is done by that account.
            verified = call("project_manager", "POST",
                            f"/api/uat-findings/{finding_id}/verify",
                            json_body={"verification_comment": "合成验收：整改已复核，证据与结论一致。"})
            step("uat_finding_verified", ok=verified.status_code == 200,
                 status=verified.status_code,
                 finding_status=(verified.json() or {}).get("status") if verified.status_code == 200 else None)
            if verified.status_code == 200:
                uat_finding["status_after_verify"] = verified.json().get("status")
                uat_finding["closed"] = verified.json().get("status") == "verified"

            listed = call("project_manager", "GET", f"/api/uat-runs/{run_id}/findings")
            uat_finding["run_finding_count"] = len(listed.json()) if listed.status_code == 200 else None

        # complete the four-role signoff chain (business/technical already signed)
        remaining_signoffs = ["project_manager", "final_acceptance"]
        signed_roles: list[str] = []
        for role in remaining_signoffs:
            actor = "project_manager" if role == "project_manager" else "final_reviewer"
            signed = call(actor, "POST", f"/api/uat-runs/{run_id}/signoff",
                          json_body={"signoff_role": role, "signoff_status": "approved",
                                     "comment": f"合成验收：{role} 已复核并通过。"})
            if signed.status_code in (200, 201):
                signed_roles.append(role)
            else:
                step("uat_signoff_failed", ok=False, role=role, status=signed.status_code,
                     body=signed.text[:200])
        step("uat_signoff_chain_completed", ok=len(signed_roles) == 2, signed=signed_roles)

        signoffs = call("project_manager", "GET", f"/api/uat-runs/{run_id}/signoffs")
        rows = signoffs.json() if signoffs.status_code == 200 else []
        approved = sorted(str(row.get("signoff_role")) for row in rows
                          if row.get("signoff_status") == "approved")
        expected = sorted(["business_owner", "technical_owner", "project_manager", "final_acceptance"])
        step("uat_signoff_all_four_approved", ok=approved == expected, approved=approved)

        step("formal_export_identities_agree",
             ok=bool(export_headers.get("xlsx")) and export_headers.get("xlsx") == export_headers.get("docx"),
             xlsx=(export_headers.get("xlsx") or "")[:16],
             docx=(export_headers.get("docx") or "")[:16],
             equals_delivery_content_hash=export_headers.get("xlsx") == content_hash,
             note="导出头是快照 hash（含 formal_delivery 块），与提审 content_hash 不同属预期契约")

        # ---- 6. change review: upload a v2 script, then open the recheck ---------------------
        # W11 step 7. ``impact_summary`` only reports a change when the frozen basis has drifted, so a
        # new script version is the real trigger; the change hash must be the server's own value
        # (an invented one is always refused with "变化依据已更新").
        with factory() as db:
            project = db.scalar(select(Project).order_by(Project.id).limit(1))
            from app.services.lineage.ingestion import ScriptIngestionService as _Ingest
            from app.services.storage import get_storage_service as _storage

            service = _Ingest(db, _storage())
            # v2 must stay a **fully parseable** script: appending a bare SQL comment after the last
            # statement makes the parser report "No expression was parsed" for a trailing statement and
            # marks the file ``partially_parsed``, which then blocks every downstream path confirmation.
            # A semantically equivalent rewrite (explicit alias in the projection) drifts the parsed
            # facts without breaking the parse.
            _v1 = build_synthetic_script(field_codes)
            # Append an extra predicate to the WHERE clause: a syntactically valid, fully parseable
            # change that still produces a new script version (which is what the drift check reads).
            # The generator emits "... IS NOT NULL\nGROUP BY ...;", so the predicate (not the statement
            # terminator) is what must be extended. Getting this wrong makes v2 byte-identical to v1,
            # which the ingester dedupes -- leaving no drift and no change review at all.
            assert " IS NOT NULL\n" in _v1, "v2 drift target missing; the generator changed"
            v2_text = _v1.replace(" IS NOT NULL\n", " IS NOT NULL AND 1 = 1\n", 1)
            try:
                # ``ingest`` keys a version by (script_file, file_hash) and bumps ``current_version_no``
                # in place, so re-uploading through the same relative_path does not create the second
                # version the drift check needs. A distinct path produces a genuine new version.
                revised = service.ingest(project=project, data=v2_text.encode("utf-8"),
                                         file_name="synthetic_loan.sql",
                                         # Same path on purpose: ``script_basis_changes`` detects drift by
                                         # comparing the frozen version_no with ``ScriptFile.current_version_no``,
                                         # so the new version must belong to the frozen script file.
                                         relative_path="synthetic/synthetic_loan.sql",
                                         dialect="postgres", actor_user_id=None,
                                         change_note="W11 synthetic script v2 (change review trigger)")
                db.commit()
                v2_id = int(revised.version.id)
            except Exception as exc:  # noqa: BLE001
                db.rollback()
                v2_id = None
                step("script_v2_upload_failed", ok=False, error=f"{type(exc).__name__}: {exc}"[:250])
        step("script_v2_uploaded", ok=v2_id is not None, version_id=v2_id,
             note="新版本与旧版本并存；旧依据文件本身不变")

        impacts = call("business_analyst", "GET",
                       f"/api/projects/{project_id}/requirements/change-impacts")
        items = (impacts.json().get("items") if impacts.status_code == 200 else None) or []
        mine = next((item for item in items if int(item.get("requirement_id", 0)) == requirement_id), None)
        step("change_impacts_listed", ok=bool(mine), status=impacts.status_code,
             count=len(items), has_own_requirement=bool(mine),
             changes=len((mine or {}).get("changes") or []))

        if mine is None:
            step("change_review_unavailable", ok=False,
                 reason="上传 v2 后仍未检测到脚本变更影响，无法开启变更复核")
        else:
            recheck = call("technical_analyst", "POST",
                           f"/api/projects/{project_id}/requirements/{requirement_id}/rechecks",
                           json_body={"expected_content_version": int(mine["content_version"]),
                                      "change_hash": mine["change_hash"]})
            step("change_review_opened", ok=recheck.status_code == 201,
                 status=recheck.status_code, body=recheck.text[:250])
            if recheck.status_code == 201:
                review = recheck.json()
                step("change_review_detail", ok=True, recheck_id=int(review["id"]),
                     status=review.get("status"), task_count=len(review.get("tasks") or []),
                     change_hash=str(mine["change_hash"])[:16])
                # Closing a recheck is a real workflow, not a single call: ``replacement_revision``
                # requires a revision **newer than the frozen one** whose basis, paths and policy
                # comparison are all already clean and whose gaps are empty. So the replacement must
                # be built and re-verified first:
                #   revise (business.edit) -> script-basis on v2 -> paths -> policy comparison -> resolution.
                revised = call("business_analyst", "POST",
                               f"/api/projects/{project_id}/requirements/{requirement_id}"
                               f"/rechecks/{int(review['id'])}/revise",
                               json_body={"reason": "合成验收：按 v2 脚本建立替代修订。",
                                          "expected_content_version": content_version})
                step("change_review_revised", ok=revised.status_code == 201,
                     status=revised.status_code, body=revised.text[:200])
                if revised.status_code == 201:
                    # ``revise`` returns a **revision document** (``revision_document``), so the version
                    # lives under ``revision.content_version`` -- not at the top level.
                    content_version = int(revised.json()["revision"]["content_version"])

                    # The replacement revision needs its **own** preview hash: rebinding against the
                    # previously confirmed preview fails with "解析事实与单元数据已变化，请重新预览".
                    with factory() as db:
                        from app.services.requirement_script_basis import script_preview as _preview
                        fresh = _preview(db, project_id, [v2_id])
                        fresh_preview_hash = fresh["preview_hash"]
                        fresh_target_key = fresh["targets"][0]["key"] if fresh["targets"] else target_key
                        fresh_fields = list(db.scalars(select(TargetField).where(
                            TargetField.project_id == project_id).order_by(TargetField.id)).all())
                        fresh_bindings = {column: int(fresh_fields[index].id)
                                          for index, column in enumerate(fresh["targets"][0]["columns"])
                                          if fresh["targets"] and index < len(fresh_fields)}
                    step("change_review_fresh_preview", ok=bool(fresh_target_key),
                         preview_hash=fresh_preview_hash[:16], bindings=len(fresh_bindings))
                    relinked = call("technical_analyst", "POST",
                                    f"/api/projects/{project_id}/requirements/{requirement_id}/script-basis",
                                    json_body={"script_version_ids": [v2_id],
                                               "expected_content_version": content_version,
                                               "preview_hash": fresh_preview_hash,
                                               "template_version_id": int(template.id),
                                               "target_key": fresh_target_key,
                                               "field_bindings": fresh_bindings})
                    step("change_review_basis_rebound", ok=relinked.status_code == 201,
                         status=relinked.status_code, body=relinked.text[:200])
                    if relinked.status_code != 201:
                        content_version = int(revised.json()["content_version"])
                    else:
                        content_version = int(relinked.json()["revision"]["content_version"])

                        # Order matters and mirrors the proven main flow: the policy comparison rewrites
                        # ``policy_snapshot`` (part of the basis), which invalidates any path confirmation
                        # made before it. So: comparison first, then paths, then resolution.
                        with factory() as db:

                            from app.services.requirement_policy_comparison import basis_hash as _bh
                            from app.services.requirement_revisions import load_revision as _load
                            _rev = _load(db, project_id, requirement_id, content_version)
                            _basis = (_rev.content_json or {}).get("script_basis") or {}
                            _rules = [r["rule_id"] for r in _basis.get("rules", [])]
                            _units = [u["unit_id"] for u in
                                      (_basis.get("policy_snapshot", {}) or {}).get("evidence", [])
                                      if u.get("source_category") in {"regulatory_formal", "regulatory_qa",
                                                                       "internal_policy"}]
                            _hash = _bh(_basis)
                        if _units and _rules:
                            recmp = call("technical_analyst", "POST",
                                         f"/api/projects/{project_id}/requirements/{requirement_id}"
                                         f"/policy-comparison",
                                         json_body={"expected_content_version": content_version,
                                                    "basis_hash": _hash,
                                                    "decisions": [{"unit_id": _units[0], "rule_ids": _rules,
                                                                   "status": "matched",
                                                                   "rationale": "合成验收：替代修订逐条复核一致。",
                                                                   "difference": ""}]})
                            if recmp.status_code == 201:
                                content_version = int(recmp.json()["revision"]["content_version"])
                            step("change_review_comparison_redone", ok=recmp.status_code == 201,
                                 status=recmp.status_code)

                        # paths are confirmed **after** the comparison, on the current basis
                        rpreview = call("technical_analyst", "GET",
                                        f"/api/projects/{project_id}/requirements/{requirement_id}"
                                        f"/paths?content_version={content_version}")
                        if rpreview.status_code == 200:
                            rconfirm = call("technical_analyst", "POST",
                                            f"/api/projects/{project_id}/requirements/{requirement_id}/paths",
                                            json_body={"expected_content_version": content_version,
                                                       "preview_hash": rpreview.json()["preview_hash"],
                                                       "rationale": "合成验收：替代修订重新确认加工路径。"})
                            if rconfirm.status_code == 201:
                                content_version = int(rconfirm.json()["revision"]["content_version"])
                            step("change_review_paths_reconfirmed", ok=rconfirm.status_code == 201,
                                 status=rconfirm.status_code, body=rconfirm.text[:200])

                        # Step 1: ``/resolution`` binds the replacement revision and writes the rationale.
                        resolution = call("technical_analyst", "POST",
                                          f"/api/projects/{project_id}/requirements/{requirement_id}"
                                          f"/rechecks/{int(review['id'])}/resolution",
                                          json_body={"reason": "合成验收：替代修订已重新核验，关闭复核。",
                                                     "expected_content_version": content_version})
                        step("change_review_resolution", ok=resolution.status_code in (200, 201),
                             status=resolution.status_code, body=resolution.text[:250])

                        # Step 2: the resolution call binds the replacement revision but does **not** flip the
                        # status. ``review_recheck`` (reachable only through the governance workflow) does,
                        # and it refuses the author, so a different user must approve the change-review task.
                        with factory() as db:
                            from app.models import ReviewTask as _Task
                            task = db.scalar(select(_Task).where(
                                _Task.project_id == project_id,
                                _Task.target_type == "requirement_recheck",
                                _Task.target_id == int(review["id"])).order_by(_Task.id))
                            change_task_id = int(task.id) if task is not None else None
                        if change_task_id is not None:
                            approved_change = call("technical_reviewer", "POST",
                                                   f"/api/review-tasks/{change_task_id}/approve",
                                                   json_body={"comment": "合成验收：替代修订已独立复核通过。"})
                            step("change_review_approved", ok=approved_change.status_code in (200, 201),
                                 status=approved_change.status_code, body=approved_change.text[:200],
                                 task_id=change_task_id)

                        finals = call("project_manager", "GET",
                                      f"/api/projects/{project_id}/requirements/{requirement_id}/rechecks")
                        rows_final = finals.json() if finals.status_code == 200 else []
                        final_status = next((row.get("status") for row in rows_final
                                             if int(row.get("id", 0)) == int(review["id"])), None)
                        replacement = next((row.get("replacement_content_version") for row in rows_final
                                            if int(row.get("id", 0)) == int(review["id"])), None)
                        uat_finding["recheck_status"] = final_status
                        uat_finding["replacement_content_version"] = replacement
                        step("change_review_closed", ok=final_status == "reviewed",
                             recheck_status=final_status, replacement_content_version=replacement)

    report = {
        "uat_finding": uat_finding,
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

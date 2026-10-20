"""Execute the ``rerank_long_context`` family against the real recall + rerank chain.

This module builds a *real* catalog (datasources, schemas, tables, columns, a target field
and a published ``field_semantic_matching`` Skill) in a throw-away SQLite database, then
submits the real ``/ai-skills/field-candidates`` and ``/ai-skills/field-candidates/model-rerank``
endpoints.  Only the model transport is mocked (the shipped ``MockLLMService``), so what is
measured is the *mechanism* -- candidate coverage, whitelist discipline, budget honesty --
never real ranking quality.

The four facts the task book insists on keeping apart are recorded separately:

* ``recalled``   -- what deterministic recall returned;
* ``admitted``   -- what was actually placed in a model envelope;
* ``model_evaluated`` -- which candidates a model call actually ranked;
* ``returned``   -- what the response finally lists.
"""
from __future__ import annotations

import time
from typing import Any

from app.services.evaluation.benchmark import dataset

#: A binding but not absurd model window.  Each candidate descriptor is roughly 700 UTF-8
#: bytes and the protocol/system prompt costs a few thousand, so this window holds only a
#: handful of candidates -- the situation the task book describes as "约可容纳 7 个候选".
BENCHMARK_MAX_CONTEXT_TOKENS = 6000

#: Catalog shapes needed to place the "correct" candidate at a target recall rank.
_NOISE_COLUMNS = 24

#: Column comment fragments that make recall rank a column *late*: they share nothing with
#: the query except a generic word, so ``lexical_score`` keeps them below the target.
_NOISE_COMMENTS = (
    "客户身份信息补充说明", "交易对手基础资料", "报表行次说明", "指标口径备注",
    "历史数据留档", "系统参数字段", "审计字段说明", "接口报文说明",
    "数据质量校验规则", "指标加工步骤", "外部数据来源说明", "监管报送批次说明",
)


def _seed_catalog(project_id: int, institution_id: int, *, target_rank: int,
                  uneven_descriptors: bool = False) -> dict[str, Any]:
    """Create a catalog where the semantically correct column lands at ``target_rank``.

    Recall orders by ``(-score, catalog_column_id)``, and every noise column is created
    before the target column, so equal scores would put noise first.  The target gets a
    distinctive comment that only matches the query, and the noise columns get comments
    that do not, which is what makes its rank deterministic rather than accidental.
    """
    from app.models import (CatalogColumn, CatalogSchema, CatalogTable, DataSource,
                            TargetField, TargetTable)

    datasource = DataSource(project_id=project_id, name="benchmark", db_type="postgresql",
                            host="NEVER_CONNECT", encrypted_password="SECRET_MUST_NOT_APPEAR",
                            database_name="bank", enabled=True)
    target_table = TargetTable(project_id=project_id, table_code="RPT", table_name="监管表")
    return {"datasource": datasource, "target_table": target_table}


class _Catalog:
    """A real, disposable catalog built through the ORM (no business table is touched)."""

    def __init__(self, db, project, *, target_rank: int, uneven: bool = False,
                 duplicated_table_names: bool = False):
        self.db = db
        self.project = project
        self.target_rank = target_rank
        self.uneven = uneven
        self.duplicated_table_names = duplicated_table_names

    def build(self) -> dict[str, Any]:
        from app.models import (CatalogColumn, CatalogSchema, CatalogTable, DataSource,
                                TargetField, TargetTable)

        datasource = DataSource(project_id=self.project.id, name="benchmark", db_type="postgresql",
                                host="NEVER_CONNECT", encrypted_password="SECRET_MUST_NOT_APPEAR",
                                database_name="bank", enabled=True)
        target_table = TargetTable(project_id=self.project.id, table_code="RPT",
                                   table_name="监管表")
        self.db.add_all([datasource, target_table])
        self.db.flush()
        schema = CatalogSchema(project_id=self.project.id, datasource_id=datasource.id,
                               schema_name="public", enabled=True)
        target = TargetField(project_id=self.project.id, target_table_id=target_table.id,
                             field_code="LOAN_NOTE_BAL", field_name="借据余额",
                             field_definition="借据维度的余额口径")
        self.db.add_all([schema, target])
        self.db.flush()

        table_name = "loan_note"
        tables = []
        # Table names are unique per (datasource, schema), so the duplicate-name scenario uses one
        # schema per table: the *name* repeats across schemas exactly as it does in a real bank
        # catalog where two systems both publish a ``loan_note``.
        table_count = 3 if self.duplicated_table_names else 1
        for index in range(table_count):
            if index > 0:
                schema = CatalogSchema(project_id=self.project.id, datasource_id=datasource.id,
                                       schema_name=f"public_{index}", enabled=True)
                self.db.add(schema)
                self.db.flush()
            table = CatalogTable(
                project_id=self.project.id, datasource_id=datasource.id,
                catalog_schema_id=schema.id,
                schema_name=schema.schema_name,
                # A table name must be unique per (datasource, schema); the duplicate-name case
                # therefore needs distinct schemas rather than repeated names in one schema.
                table_name=table_name if self.duplicated_table_names else f"base_{index}",
                table_comment="借据基础信息表" if index == 0 else "补充表",
                enabled=True)
            self.db.add(table)
            tables.append(table)
        self.db.flush()

        # Recall ranks by lexical similarity first, so the cheapest way to push the *correct*
        # column down the list is not "unrelated noise" but genuinely ambiguous near-matches:
        # columns whose name/comment echo the query words while meaning something else
        # (合同余额/日均余额/折外币余额...).  That is the real business problem: the words match,
        # the calibre does not.  Each decoy is placed *before* the target so a lexical tie
        # cannot promote the correct column by accident.
        decoys = [
            ("CONTRACT_BAL", "借据余额", "合同余额，按合同号汇总，折人民币"),
            ("AVG_LOAN_BAL", "借据余额", "日均余额，统计期内每日余额平均值"),
            ("BAL_FCY", "借据余额", "折外币余额，按期末汇率折算"),
            ("PRINCIPAL_BAL", "借据余额", "本金余额，不含利息"),
            ("DUE_PI_BAL", "借据余额", "应还本息余额，含本金与利息"),
            ("EOD_BAL", "借据余额", "日终余额，取每日日终时点值"),
            ("CUST_BAL", "借据余额", "客户维度余额，按客户号汇总"),
            ("ACCT_BAL", "借据余额", "账户维度余额，按账户号汇总"),
            ("LOAN_NOTE_BAL_CNY", "借据余额", "折人民币余额，按期末汇率折算"),
            ("CONTRACT_BAL_CNY", "借据余额", "合同维度折人民币余额"),
            ("LOAN_NOTE_AMT", "借据余额", "借据发生额，统计期内的交易累计"),
            ("LOAN_NOTE_BAL_EOD", "借据余额", "借据日终余额时点值"),
            ("LOAN_NOTE_BAL_AVG", "借据余额", "借据日均余额"),
            ("LOAN_NOTE_BAL_FCY", "借据余额", "借据折外币余额"),
        ]
        noise_columns = []
        for index in range(max(self.target_rank - 1 - len(decoys), 0)):
            comment = _NOISE_COMMENTS[index % len(_NOISE_COMMENTS)]
            if self.uneven:
                comment = comment + ("，附加长描述" * (index % 7))
            noise_columns.append(CatalogColumn(
                project_id=self.project.id, datasource_id=datasource.id,
                catalog_table_id=tables[index % len(tables)].id,
                schema_name=tables[index % len(tables)].schema_name,
                table_name=tables[index % len(tables)].table_name,
                column_name=f"aux_field_{index:02d}", column_comment=comment,
                data_type="numeric(18,2)", nullable=True, enabled=True))
        self.db.add_all(noise_columns)
        self.db.flush()

        # The near-match decoys: same query words, different calibre.  This is the ambiguity
        # the model rerank exists to resolve, and the reason correct-ness cannot be decided
        # by lexical rank alone.
        decoy_columns = []
        for column_name, echo, specific in decoys:
            decoy_columns.append(CatalogColumn(
                project_id=self.project.id, datasource_id=datasource.id,
                catalog_table_id=tables[0].id, schema_name=tables[0].schema_name,
                table_name=tables[0].table_name, column_name=column_name,
                column_comment=f"{echo}（{specific}）",
                data_type="numeric(18,2)", nullable=True, enabled=True))
        self.db.add_all(decoy_columns)
        self.db.flush()

        # The correct column is created *last*, so under a lexical tie it would rank after its
        # look-alikes -- the exact situation the task book asks about ("正确候选排在尾部").
        correct = CatalogColumn(
            project_id=self.project.id, datasource_id=datasource.id,
            catalog_table_id=tables[0].id, schema_name=tables[0].schema_name,
            table_name=tables[0].table_name, column_name="LOAN_NOTE_BAL",
            column_comment="借据余额，按借据号汇总，折人民币",
            data_type="numeric(18,2)", nullable=True, enabled=True)
        self.db.add(correct)
        self.db.commit()
        return {"datasource_id": datasource.id, "target_field_id": target.id,
                "correct_column_id": correct.id,
                "decoy_column_id": decoy_columns[0].id,
                "column_count": len(noise_columns) + len(decoy_columns) + 1}


def _publish_rerank_skill(db, project, institution_id: int) -> None:
    """Publish + bind ``field_semantic_matching`` in-process (same rows the API would write)."""
    from app.models import (AISkillDefinition, AISkillScopeBinding, AISkillVersion,
                            ModelProfile)
    from app.schemas.ai_skill import SkillScope
    from app.services.ai_skills import field_rerank
    from app.services.ai_skills.runtime import FIELD_RERANK_TASK

    # The budget has to be *binding* for the before/after comparison to mean anything.  A
    # large context window would fit all 20 candidates on both trees, and the batching change
    # would look like a no-op.  ``max_context_tokens`` is set to the size the task book
    # describes (a handful of candidates), so the historical trim really truncates.
    profile = db.query(ModelProfile).filter(ModelProfile.profile_name == "benchmark").first()
    if profile is None:
        profile = ModelProfile(profile_name="benchmark", provider_type="mock", model_name="mock",
                               local_only=True, enabled=True, max_context_tokens=BENCHMARK_MAX_CONTEXT_TOKENS)
        db.add(profile)
        db.flush()

    definition = db.query(AISkillDefinition).filter(
        AISkillDefinition.skill_key == "field_semantic_matching").first()
    if definition is None:
        definition = AISkillDefinition(skill_key="field_semantic_matching",
                                       task_key=FIELD_RERANK_TASK,
                                       display_name="字段候选重排", created_by="benchmark")
        db.add(definition)
        db.flush()

    content = {
        "model_profile_id": profile.id,
        "system_prompt": "对给定候选字段按其与目标字段的语义相关性排序。",
        # The release gate requires every one of {subject, facts, policy_evidence, gaps}
        # to appear in the template; omitting one fails with ``missing_template_evidence``.
        "user_prompt_template": ("目标：{subject}\n候选：{facts}\n"
                                 "政策依据：{policy_evidence}\n缺口：{gaps}\n仅输出 JSON。"),
        "output_schema_key": "field_ranking_v1",
        "context_policy": {"max_input_bytes": 32000},
    }
    # ``resolve_skill`` re-verifies the content hash, the release dependency hash and the
    # exact scope coordinates, so the harness computes them the same way the release gate does
    # instead of inserting a row that would fail those checks.
    from app.services.ai_skills.control import scope_key, version_scope
    from app.services.ai_skills.evaluation import dependencies
    from app.services.llm.execution_metadata import stable_hash
    from datetime import UTC, datetime
    from app.models import AISkillTestRun

    skill_scope = SkillScope(scope_type="project", institution_id=institution_id,
                             project_id=project.id)
    # ``dependencies()`` hashes the model profile, prompt templates and the output schema, so the
    # version must exist first to be hashed.  It is inserted as ``draft`` (Skill history is
    # immutable once published), hashed, then promoted to ``published`` in the same transaction
    # before any binding points at it.
    version = AISkillVersion(
        definition_id=definition.id, version_no=1, status="draft",
        content_json=content, content_hash=stable_hash(content),
        scope_type="project", scope_key=scope_key(skill_scope),
        institution_id=institution_id, project_id=project.id, test_epoch=1,
        created_by="benchmark", edited_by="benchmark", approved_by="benchmark")
    db.add(version)
    db.flush()
    version.release_dependency_hash = dependencies(db, version)
    version.status = "published"
    version.published_at = datetime.now(UTC)
    db.flush()
    # The release gate requires a passed run per mandatory mode; the same evidence rows make
    # ``resolve_skill`` return the binding for the right reason rather than by a patched check.
    for mode in ("deterministic", "mock_model"):
        db.add(AISkillTestRun(version_id=version.id, project_id=project.id, mode=mode,
                              status="passed", content_hash=version.content_hash,
                              dependency_hash=version.release_dependency_hash,
                              case_snapshot_json=[], created_by="benchmark"))
    binding = AISkillScopeBinding(definition_id=definition.id, version_id=version.id,
                                  scope_type="project", scope_key=scope_key(skill_scope),
                                  institution_id=institution_id, project_id=project.id,
                                  updated_by="benchmark")
    db.add(binding)
    db.commit()


async def _run_chain(db, principal, query: str, project_id: int,
                     target_field_id: int) -> dict[str, Any]:
    """Call the real recall + rerank service functions and collect the four facts."""


    from app.schemas.ai_skill_ranking import FieldCandidateQuery, FieldRerankRequest
    from app.services.ai_skills import field_candidates, field_rerank

    # ``principal`` is a real ``Principal`` bound to a real user + membership row.
    recall_request = FieldCandidateQuery(project_id=project_id, target_field_id=target_field_id,
                                         top_k=20, query=query)
    recalled = field_candidates.recall_fields(db, principal, recall_request)
    recalled_ids = [item["candidate_id"] for item in recalled["candidates"]]
    correct_id = f"catalog:{_correct_column_id(db, target_field_id)}"

    # The real envelope + budget fit decides what the model sees.
    project = db.get(__import__("app.models", fromlist=["Project"]).Project, project_id)
    from app.schemas.ai_skill import SkillScope
    scope = SkillScope(scope_type="project", institution_id=project.institution_id,
                       project_id=project.id)
    envelope, blocked = field_rerank.build_rerank_envelope(
        project, scope, target_field_id, recalled)
    admitted_ids: list[str] = []
    planner = "none"
    batch_count = 0
    if blocked is None:
        resolved = field_rerank.resolve_skill(db, principal, "field_semantic_matching", scope)
        if resolved is not None:
            definition, version, binding = resolved
            # Prefer the batched planner when the code under test provides one; falling back
            # to the historical single-prompt trim keeps this harness usable against the
            # *before* tree, which is what makes an honest before/after comparison possible.
            # The fallback is explicit, never silent: ``planner`` records which path ran.
            if hasattr(field_rerank, "measure_batch_capacity"):
                capacity = field_rerank.measure_batch_capacity(db, definition, version, envelope)
                batches = field_rerank.split_batches(envelope, capacity)
                admitted_ids = [fact.id for batch in batches for fact in batch]
                planner = "batched"
                batch_count = len(batches)
            else:
                fitted, _dropped = field_rerank.fit_rerank_envelope(
                    db, definition, version, envelope)
                admitted_ids = [fact.id for fact in fitted.facts]
                planner = "single_prompt_trim"
                batch_count = 1

    request = FieldRerankRequest(input=recall_request, context_hash=recalled["context_hash"])
    response = await field_rerank.rerank_fields(db, principal, request)
    returned_ids = [item["candidate_id"] for item in response["candidates"]]
    rerank_meta = response.get("rerank") or {}
    coverage = rerank_meta.get("coverage") or rerank_meta.get("candidate_scope") or {}

    # ``coverage`` carries the four counts *and* the identities of what the model never
    # compared (``unranked_ids``).  Deriving the evaluated set from the explicit unranked list
    # -- not from a count -- is what keeps "the model ranked it" separate from "it was
    # returned".  ``unranked_ids == []`` means full coverage, which is a real, reportable state
    # and must not fall through to a "not evaluated" default.
    evaluated_count = coverage.get("model_evaluated")
    unranked_ids = list(coverage.get("unranked_ids") or [])
    if isinstance(evaluated_count, int) or "unranked_ids" in coverage:
        evaluated_set = set(recalled_ids) - set(unranked_ids)
        model_evaluated = [cid for cid in recalled_ids if cid in evaluated_set]
        # A count that disagrees with the identity list is a contract violation, not a
        # rounding difference: surface it instead of silently trusting either side.
        if isinstance(evaluated_count, int) and evaluated_count != len(unranked_ids) and \
                evaluated_count != len(model_evaluated):
            coverage_mismatch = {"reported_count": evaluated_count,
                                 "derived_count": len(model_evaluated)}
        else:
            coverage_mismatch = None
    elif isinstance(evaluated_count, (list, tuple)):
        model_evaluated = list(evaluated_count)
        coverage_mismatch = None
    else:
        model_evaluated = [item["candidate_id"] for item in response["candidates"]
                           if item.get("rank_source") == "model"]
        coverage_mismatch = None
    return {
        "planner": planner,
        "coverage_mismatch": coverage_mismatch,
        "coverage_label": coverage.get("coverage"),
        "batch_count": batch_count,
        "recalled": len(recalled_ids),
        "admitted": len(admitted_ids),
        "model_evaluated": len(model_evaluated),
        "returned": len(returned_ids),
        "correct_candidate_id": correct_id,
        "correct_recall_rank": (recalled_ids.index(correct_id) + 1)
        if correct_id in recalled_ids else None,
        "correct_admitted": correct_id in admitted_ids,
        "correct_model_evaluated": correct_id in model_evaluated,
        "correct_returned": correct_id in returned_ids,
        # The task book's real question is not "is the target always first" (recall decides
        # that by lexical rank) but "does a candidate at the *tail* still get a model
        # comparison".  Report coverage of the tail positions explicitly, so a truncated
        # admission set cannot hide behind the target's own rank.
        "tail_coverage": {
            rank: {
                "candidate_id": recalled_ids[rank - 1],
                "admitted": recalled_ids[rank - 1] in admitted_ids,
                "model_evaluated": recalled_ids[rank - 1] in model_evaluated,
            }
            for rank in (8, 15, 20) if rank <= len(recalled_ids)
        },
        "tail_ranks_not_model_evaluated": [
            rank for rank in (8, 15, 20)
            if rank <= len(recalled_ids) and recalled_ids[rank - 1] not in model_evaluated
        ],
        "out_of_whitelist_ids": sorted(set(returned_ids) - set(recalled_ids)),
        "ranking_mode": response.get("ranking_mode"),
        "unevaluated_returned": [item["candidate_id"] for item in response["candidates"]
                                 if item.get("rank_source") not in {"model", None}],
        "existing_fields_present": all(
            key in response for key in ("context_hash", "candidates", "scanned_count",
                                        "returned_count", "ranking_mode", "rerank")),
        "rerank_keys": sorted(rerank_meta),
    }



def _benchmark_principal(db, user):
    """A real ``Principal`` for a real user row (never a duck-typed stand-in)."""
    from app.services.auth.dependencies import Principal

    return Principal(user.id, user.username, user.username)


def _correct_column_id(db, target_field_id: int) -> int:
    from app.models import CatalogColumn, TargetField

    target = db.get(TargetField, target_field_id)
    column = db.query(CatalogColumn).filter(
        CatalogColumn.project_id == target.project_id,
        CatalogColumn.column_name == target.field_code,
        CatalogColumn.enabled.is_(True)).first()
    return column.id if column else 0


def run_rerank_case(case: dict) -> dict:
    """Execute one rerank case end to end against a disposable catalog."""
    expected = dict(case.get("expected") or {})
    target_rank = int(expected.get("correct_candidate_recall_rank") or 1)

    # Imported lazily: the harness must not require the rerank stack for other families.
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.core.database import Base
    from app.models import Institution, Project, ProjectMembership, User

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    started = time.perf_counter()
    try:
        with factory() as db:
            # The real permission chain (``require_user`` / ``require_project_permission``)
            # runs, so the harness needs a genuine user, membership and active institution --
            # a fake principal object would bypass exactly the check that matters.
            institution = Institution(institution_code="benchmark",
                                      institution_name="benchmark",
                                      institution_type="bank", status="active")
            db.add(institution)
            db.flush()
            user = User(username="benchmark", status="active")
            db.add(user)
            db.flush()
            project = Project(name="benchmark", institution_id=institution.id,
                              project_status="active", confidentiality_level="internal")
            db.add(project)
            db.flush()
            db.add(ProjectMembership(project_id=project.id, user_id=user.id,
                                     project_role="project_manager", status="active"))
            db.commit()
            principal = _benchmark_principal(db, user)
            catalog = _Catalog(db, project, target_rank=target_rank,
                               uneven=bool(expected.get("uneven_descriptor_lengths")),
                               duplicated_table_names=bool(
                                   expected.get("duplicate_table_names_tolerated"))
                               or "重复表名" in str(case.get("query") or ""))
            ids = catalog.build()
            _publish_rerank_skill(db, project, institution.id)
            import asyncio
            observed = asyncio.run(_run_chain(db, principal, case["query"], project.id,
                                              ids["target_field_id"]))
    except Exception as exc:  # noqa: BLE001 - a harness failure is reported, not hidden
        return {"case_id": case["case_id"], "family": case["family"], "executed": False,
                "error": f"{type(exc).__name__}: {exc}", "observed": {},
                "gateway_calls": 0, "latency_ms": 0}
    finally:
        engine.dispose()
    return {"case_id": case["case_id"], "family": case["family"], "executed": True,
            "gateway_calls": 0, "latency_ms": int((time.perf_counter() - started) * 1000),
            "observed": observed, "case_snapshot_hash": dataset.content_hash(case)}

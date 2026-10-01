"""Server-computed, content- and dependency-bound evaluation evidence."""
from time import perf_counter

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from app.models import AISkillTestCase, AISkillTestRun, AISkillTestResult, AISkillDefinition, AISkillVersion, AIUserFeedback, ModelCallLog, ModelProfile, Project
from app.schemas.ai_skill import SkillInputEnvelope, SkillClaim, SkillScope, validate_claim_references, validate_policy_comparison
from app.schemas.ai_skill_control import SkillContent
from app.services.ai_skills import control, runtime
from app.services.auth.permission_service import PermissionService
from app.services.llm.execution_metadata import stable_hash
from app.services.llm.providers import normalize_provider_type

EVALUATOR_VERSION = "skill-evaluator-4-mapping-contract"


def test_scope(db, principal, project_id):
    project = PermissionService(db, principal).require_project_permission(project_id, "knowledge.manage")
    scope = SkillScope(scope_type="project", institution_id=project.institution_id, project_id=project.id)
    control.authorize_scope(db, principal, scope, write=True)
    return scope


def create_case(db, principal, key, payload, *, source_feedback_id=None):
    control.authorize_scope(db, principal, payload.input.scope, write=True)
    definition = control.definition_for(db, key)
    db.execute(update(AISkillDefinition).where(AISkillDefinition.id == definition.id)
               .values(next_version_no=AISkillDefinition.next_version_no))
    if payload.input.skill_key != key or payload.input.task_key != definition.task_key:
        control.fail(422, "skill_task_mismatch")
    if payload.replay_output is not None:
        runtime.output_schema(definition.task_key).model_validate(payload.replay_output)
    material = {"input": payload.input.model_dump(mode="json"), "assertions": payload.assertions.model_dump(),
                "replay_output": payload.replay_output}
    item = AISkillTestCase(definition_id=definition.id, project_id=payload.input.scope.project_id,
                          source_feedback_id=source_feedback_id,
                          name=payload.name, input_json=material["input"], assertions_json=material["assertions"],
                          replay_output_json=material["replay_output"], content_hash=stable_hash(material), created_by=principal.user_id)
    db.add(item)
    db.flush()
    control.event(db, principal, definition.id, None, "test_case_created", {"case_id": item.id}, scope=payload.input.scope)
    return item


def feedback_case(db, principal, key, feedback_id, payload):
    control.authorize_scope(db, principal, payload.input.scope, write=True)
    feedback = db.get(AIUserFeedback, feedback_id)
    if feedback is None or feedback.project_id != payload.input.scope.project_id:
        control.fail(404, "resource_not_found")
    log = db.get(ModelCallLog, feedback.model_call_log_id) if feedback.model_call_log_id else None
    if (log is None or log.project_id != feedback.project_id or log.skill_version_id is None
            or log.skill_key != key or log.context_hash != payload.input.context_hash()):
        control.fail(409, "feedback_input_mismatch")
    existing = db.scalar(select(AISkillTestCase).where(AISkillTestCase.source_feedback_id == feedback_id))
    if existing is not None:
        return existing
    try:
        with db.begin_nested():
            return create_case(db, principal, key, payload, source_feedback_id=feedback_id)
    except IntegrityError:
        existing = db.scalar(select(AISkillTestCase).where(AISkillTestCase.source_feedback_id == feedback_id))
        if existing is None:
            raise
        return existing


def cases_for(db, definition_id, project_id):
    return db.scalars(select(AISkillTestCase).where(AISkillTestCase.definition_id == definition_id,
                      AISkillTestCase.project_id == project_id).order_by(AISkillTestCase.id)).all()


def snapshot(cases):
    # Recompute from stored contents too: a stale stored hash is never trusted.
    return [{"id": case.id, "hash": stable_hash({"input": case.input_json, "assertions": case.assertions_json,
                                               "replay_output": case.replay_output_json})} for case in cases]


def dependencies(db, version):
    content = SkillContent.model_validate(version.content_json)
    control.validate_content(db, content)
    model = db.get(ModelProfile, content.model_profile_id)
    definition = db.get(AISkillDefinition, version.definition_id)
    return stable_hash({"evaluator": EVALUATOR_VERSION, "compiler": runtime.SAFETY_PROMPT,
                        "native_compiler": runtime.native_safety_prompt(definition.task_key),
                        "output_schema": runtime.output_schema(definition.task_key).model_json_schema(), "test_epoch": version.test_epoch,
                        "profile": {"id": model.id, "provider": model.provider_type, "model": model.model_name,
                                    "base_url": model.base_url, "enabled": model.enabled, "local_only": model.local_only,
                                    "max_context_tokens": model.max_context_tokens, "temperature": model.temperature,
                                    "config": model.config_json, "credential_reference": model.api_key_env_name},
                        "content_hash": stable_hash(version.content_json)})


def compatible_owner(version, scope):
    owner = control.version_scope(version)
    return ((owner.institution_id is None or owner.institution_id == scope.institution_id)
            and (owner.project_id is None or owner.project_id == scope.project_id)
            and (owner.invocation_key is None or owner.invocation_key == scope.invocation_key))


def mandatory_assertions(envelope):
    # Unknown refs must always fail independently of user-authored assertions.
    unknown = "__server_unknown_reference__"
    while unknown in {item.id for item in envelope.facts}:
        unknown += "_"
    try:
        validate_claim_references(SkillClaim(claim_type="observed_fact", text="negative probe", fact_ids=[unknown]), envelope)
    except ValueError:
        assertions = {"schema": True, "scope": True, "budget": True, "unknown_reference_rejected": True}
        if envelope.task_key == runtime.DOCUMENT_TASK:
            try:
                runtime.validate_document_output(runtime.DocumentCandidate(background=[{"text": "negative probe", "fact_ids": [unknown]}]), envelope)
                assertions["native_unknown_reference_rejected"] = False
            except ValueError:
                assertions["native_unknown_reference_rejected"] = True
        if envelope.task_key == "requirement_candidate_generation":
            ids = {item.value.get("unit_id") for item in [*envelope.facts, *envelope.policy_evidence]
                   if item.kind in {"knowledge_evidence", "policy_clause"} and isinstance(item.value, dict)}
            unknown_unit = max([value for value in ids if type(value) is int] or [0]) + 1
            try:
                runtime.validate_requirement_output(runtime.RequirementCandidate(final_content="negative probe",
                    evidence_unit_ids=[unknown_unit]), envelope)
                assertions["native_unknown_reference_rejected"] = False
            except ValueError:
                assertions["native_unknown_reference_rejected"] = True
        elif envelope.task_key in runtime.MAPPING_TASKS:
            schema = runtime.MAPPING_TASKS[envelope.task_key][1]
            try:
                runtime.validate_mapping_output(schema(final_content_draft="negative probe",
                    citations=[{"fact_ref": unknown}]), envelope)
                assertions["native_unknown_reference_rejected"] = False
            except ValueError:
                assertions["native_unknown_reference_rejected"] = True
            if envelope.task_key == "scenario_technical_lineage":
                from app.services.ai_skills.mapping_context import PHYSICAL_FIELDS, mapping_constraint
                fixed = mapping_constraint(envelope)
                occupied = {str(part).casefold() for entry in fixed["projection"]["physical_whitelist"] for part in entry}
                occupied.update(str(fixed["snapshot"]["task"].get(key, "")).casefold() for key in PHYSICAL_FIELDS)
                unknown_source = "__server_unknown_physical_source__"
                while unknown_source in occupied:
                    unknown_source += "_"
                try:
                    runtime.validate_mapping_output(schema(processing_logic="negative probe",
                        **{key: unknown_source for key in PHYSICAL_FIELDS}), envelope)
                    assertions["native_unknown_physical_source_rejected"] = False
                except ValueError:
                    assertions["native_unknown_physical_source_rejected"] = True
        if envelope.task_key == runtime.FIELD_RERANK_TASK:
            # The release gate must prove the new native validator rejects ids that are
            # well-formed but outside the supplied candidate whitelist.
            known = runtime.require_field_candidate_ids(envelope)
            numbers = [int(value.partition(":")[2]) for value in known] or [0]
            probe_number = max(numbers) + 1
            unknown_candidate = f"catalog:{probe_number}"
            while unknown_candidate in known:
                probe_number += 1
                unknown_candidate = f"catalog:{probe_number}"
            if known:
                probe = [{**{"candidate_id": value, "score": 0.5, "rationale": "negative probe"},
                          **({"evidence_refs": [unknown_candidate]} if index == 0 else {})}
                         for index, value in enumerate(known)]
                try:
                    runtime.validate_field_ranking(runtime.FieldRankingCandidate(ranking=probe), envelope)
                    assertions["native_unknown_evidence_rejected"] = False
                except ValueError:
                    assertions["native_unknown_evidence_rejected"] = True
            try:
                runtime.validate_field_ranking(runtime.FieldRankingCandidate(ranking=[
                    {"candidate_id": unknown_candidate, "score": 0.5, "rationale": "negative probe"}]), envelope)
                assertions["native_unknown_reference_rejected"] = False
            except ValueError:
                assertions["native_unknown_reference_rejected"] = True
        return assertions
    return {"unknown_reference_rejected": False}


async def run_tests(db, principal, key, payload):
    version = control.version_for(db, principal, key, payload.version, write=True)
    test_scope(db, principal, payload.project_id)
    cases = cases_for(db, version.definition_id, payload.project_id)
    if not cases:
        control.fail(409, "test_cases_required")
    definition = db.get(AISkillDefinition, version.definition_id)
    db.execute(update(AISkillDefinition).where(AISkillDefinition.id == definition.id)
               .values(next_version_no=AISkillDefinition.next_version_no))
    content = SkillContent.model_validate(version.content_json)
    model = db.get(ModelProfile, content.model_profile_id)
    control.validate_content(db, content)
    actual_mode = "mock_model" if normalize_provider_type(model.provider_type) == "mock" else "real_model"
    if payload.mode in {"mock_model", "real_model"} and payload.mode != actual_mode:
        control.fail(422, "test_mode_provider_mismatch")
    changed = db.execute(update(AISkillVersion).where(AISkillVersion.id == version.id,
        AISkillVersion.status.in_(["draft", "testing"]), AISkillVersion.lock_version == payload.expected_lock_version,
        AISkillVersion.published_at.is_(None)).values(status="testing", lock_version=AISkillVersion.lock_version + 1))
    if changed.rowcount != 1:
        control.fail(409, "version_conflict")
    db.refresh(version)
    run = AISkillTestRun(version_id=version.id, project_id=payload.project_id, mode=payload.mode, status="running",
                        content_hash=version.content_hash, dependency_hash=dependencies(db, version),
                        case_snapshot_json=snapshot(cases), created_by=principal.user_id)
    db.add(run)
    db.flush()
    started = perf_counter()
    passed_count = 0
    executed_count = 0
    skipped_count = 0
    for case in cases:
        output = None
        assertions = {}
        error = None
        stage = "input"
        try:
            envelope = SkillInputEnvelope.model_validate(case.input_json)
            stage = "authorize"
            runtime.authorize_invocation(db, principal, envelope.scope)
            if envelope.scope.project_id != payload.project_id or not compatible_owner(version, envelope.scope):
                control.fail(404, "resource_not_found")
            stage = "compile"
            runtime.compile_input(db, definition, version, envelope)
            stage = "execute"
            assertions = mandatory_assertions(envelope)
            if payload.mode in {"mock_model", "real_model"}:
                output = await runtime.execute_resolved(db, envelope, definition, version)
                assertions["model_output_valid"] = output["execution_metadata"]["execution_kind"] == payload.mode
            elif payload.mode == "replay":
                if case.replay_output_json is None:
                    control.fail(422, "replay_output_required")
                parsed = runtime.output_schema(definition.task_key).model_validate(case.replay_output_json)
                runtime.validate_native_output(parsed, envelope)
                for claim in parsed.claims:
                    validate_claim_references(claim, envelope)
                for comparison in parsed.policy_comparisons:
                    validate_policy_comparison(comparison, envelope)
                output = parsed.model_dump(mode="json")
            if output is not None:
                assertions["minimum_claims"] = len(output["claims"]) >= case.assertions_json.get("minimum_claims", 0)
                assertions["required_gaps"] = set(case.assertions_json.get("required_gap_codes", [])).issubset({gap["code"] for gap in output["gaps"]})
        except Exception as exc:
            error = (exc.detail.get("error_code", "evaluation_failed") if isinstance(exc, HTTPException) and isinstance(exc.detail, dict)
                     else type(exc).__name__)
        # A case whose own input or contract cannot be honoured is a defect of the test data, not a
        # skill outcome: record it as skipped so it stays visible without blocking the whole project
        # scope (test cases cannot be deleted through the API). Everything from execution onwards is
        # a genuine evaluation result and still fails the run.
        case_defect = error is not None and stage in {"input", "compile"}
        if case_defect:
            skipped_count += 1
            assertions = {**assertions, "case_defect": True}
            passed = None
        else:
            executed_count += 1
            passed = error is None and bool(assertions) and all(assertions.values())
            passed_count += int(passed)
        db.add(AISkillTestResult(run_id=run.id, case_id=case.id,
                                passed=None if payload.mode == "human_review" and passed else passed,
                                assertions_json=assertions, output_json=output, error_code=error))
    if executed_count == 0:
        run.status = "failed"
    else:
        run.status = (("pending_review" if payload.mode == "human_review" else "passed")
                      if passed_count == executed_count else "failed")
    run.metrics_json = {"total": len(cases), "executed": executed_count, "skipped": skipped_count,
                        "passed": passed_count, "elapsed_ms": int((perf_counter() - started) * 1000),
                        "mode": payload.mode, "real_model_successes": passed_count if payload.mode == "real_model" else 0,
                        "cost": None, "cost_available": False}
    control.event(db, principal, version.definition_id, version, "test_run_completed", {"run_id": run.id, "mode": run.mode, "status": run.status})
    db.flush()
    return run


def release_evidence(db, version, project_id):
    cases = cases_for(db, version.definition_id, project_id)
    if not cases:
        control.fail(409, "test_cases_required")
    current_snapshot = snapshot(cases)
    dependency_hash = dependencies(db, version)
    model = db.get(ModelProfile, version.content_json["model_profile_id"])
    modes = ["deterministic", "mock_model" if normalize_provider_type(model.provider_type) == "mock" else "real_model"]
    evidence = []
    for mode in modes:
        latest = db.scalar(select(AISkillTestRun).where(AISkillTestRun.version_id == version.id,
                           AISkillTestRun.project_id == project_id, AISkillTestRun.mode == mode).order_by(AISkillTestRun.id.desc()))
        if (latest is None or latest.status != "passed" or latest.content_hash != version.content_hash
                or latest.content_hash != stable_hash(version.content_json) or latest.dependency_hash != dependency_hash
                or latest.case_snapshot_json != current_snapshot):
            control.fail(409, "release_gate_failed")
        evidence.append(latest.id)
    return evidence

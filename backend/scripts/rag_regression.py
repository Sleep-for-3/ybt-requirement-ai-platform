"""Reproducible dataset snapshots and fail-closed RAG result comparison.

No application imports or network calls in snapshot/check/compare modes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time
import unicodedata


def source_code_hashes(repository):
    files = subprocess.check_output(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=repository).decode().split("\0")
    prefixes = ("backend/app/", "backend/scripts/", "frontend/app/", "frontend/lib/",
                "frontend/components/", "frontend/hooks/")
    return {name: hashlib.sha256((repository / name).read_bytes()).hexdigest()
            for name in files if name.startswith(prefixes) and (repository / name).is_file()}


def freeze_environment(database_file, project_id, dataset, *, session=None):
    """Read SQLite without creating or mutating it; no provider is invoked."""
    import sqlite3
    from dataclasses import asdict
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import Session

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from app.core.settings import get_settings
    from app.models import KnowledgeDocument, KnowledgeDocumentVersion, KnowledgeUnit
    from app.services.llm.prompt_runtime import get_prompt_runtime
    from app.services.semantic_index.versioning import get_active_index_version

    from contextlib import nullcontext
    database = Path(database_file).resolve(strict=True) if session is None else None
    engine = create_engine("sqlite://", creator=lambda: sqlite3.connect(
        database.as_uri() + "?mode=ro", uri=True)) if session is None else None
    try:
        with Session(engine) if session is None else nullcontext(session) as db:
            rows = db.execute(select(KnowledgeUnit, KnowledgeDocument, KnowledgeDocumentVersion)
                .join(KnowledgeDocument, KnowledgeDocument.id == KnowledgeUnit.document_id)
                .join(KnowledgeDocumentVersion, KnowledgeDocumentVersion.id == KnowledgeUnit.document_version_id)
                .where(KnowledgeUnit.project_id == project_id).order_by(KnowledgeUnit.id)).all()
            corpus = [{
                "unit_id": unit.id, "document_id": document.id, "version_id": version.id,
                "source": document.file_name, "version": version.regulatory_version or version.internal_revision or str(version.version_no),
                "source_category": document.source_category,
                "enabled": unit.enabled, "lifecycle": version.lifecycle_status,
                "content": unit.content, "content_hash": digest(unit.content),
                "source_sheet_name": unit.source_sheet_name, "source_cell_range": unit.source_cell_range,
                "target_field_code": unit.target_field_code, "target_table_code": unit.target_table_code,
                "file_hash": version.file_hash, "unit_content_hash": unit.content_hash,
                "scope": unit.knowledge_scope, "confidentiality": unit.confidentiality_level,
                "document_status": document.document_status,
                "applicable_projects": document.applicable_project_ids_json,
                "applicable_institutions": document.applicable_institution_names_json,
                "effective_at": str(version.effective_at), "expires_at": str(version.expires_at),
            } for unit, document, version in rows]
            prompts = []
            for key in ("regulatory_field_explanation", "rag_query_plan", "citation_support_check", "rag_faithfulness_judge"):
                runtime = asdict(get_prompt_runtime(db, key))
                entry = {key: runtime[key] for key in (
                    "prompt_key", "version", "system_prompt", "user_template",
                    "model_profile_id", "provider_type", "model_name", "local_only")}
                entry["runtime_options"] = {name: runtime["config"][name] for name in (
                    "max_output_tokens", "temperature", "json_mode", "retry_count", "timeout_seconds")
                    if name in runtime["config"]}
                prompts.append(entry)
            index = get_active_index_version(db, project_id)
            index_snapshot = None if index is None else {
                "id": index.id, "collection": index.collection_name,
                "model": index.model_name, "model_fingerprint": index.model_fingerprint,
                "corpus_hash": index.corpus_hash, "config": index.config_json,
                "dimension": index.vector_dimension,
            }
            source_versions = {version.id: {
                "version_id": version.id, "document_id": document.id, "file_name": version.file_name,
                "file_hash": version.file_hash, "parse_summary": version.parse_summary_json,
                "warnings": version.warnings_json,
            } for _, document, version in rows}
            settings = get_settings()
            config = {key: value for key, value in settings.model_dump().items()
                      if key.startswith(("rag_", "reranker_", "retrieval_", "query_expansion_", "keyword_", "hybrid_", "chunk_"))
                      and "cache_dir" not in key}
            config.update({key: getattr(settings, key) for key in (
                "embedding_provider", "embedding_model", "embedding_dimension",
                "vector_store_provider", "fusion_strategy", "rrf_k", "citation_support_check",
                "llm_max_output_tokens", "llm_timeout_seconds", "llm_interactive_timeout_seconds")})
    finally:
        if engine is not None:
            engine.dispose()
    repository = Path(__file__).resolve().parents[2]
    code = source_code_hashes(repository)
    return {
        "schema": "rag-environment-v1", "project_id": project_id,
        "dataset_version": dataset["dataset_version"],
        "git_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repository).decode().strip(),
        "code_hash": digest(code), "code_files": code, "corpus": corpus,
        "source_versions": list(source_versions.values()),
        "corpus_hash": digest(corpus), "index": index_snapshot, "prompts": prompts,
        "config": config, "config_fingerprint": digest(config),
        "blockers": list(dataset.get("blockers", [])) + ([] if corpus else ["empty_corpus"])
        + (["source_parse_has_blocking_findings"] if any(
            (v["parse_summary"] or {}).get("parse_blocked") for v in source_versions.values()) else []),
        "evidence_tier": "sqlite_snapshot" if session is None else "component_snapshot", "external_calls": 0,
    }


def evaluate_results(dataset, manifest, rows):
    """Score explicit case identities; never infer gold from answer text."""
    if manifest.get("dataset_version") != dataset["dataset_version"]:
        raise ValueError("dataset version does not match frozen environment")
    by_id = {}
    for row in rows:
        if row["case_id"] in by_id:
            raise ValueError("duplicate result case_id")
        by_id[row["case_id"]] = row
    known = {case["case_id"] for case in dataset["cases"]}
    if by_id.keys() - known:
        raise ValueError("unknown result case_id")
    blockers = set(manifest.get("blockers") or [])
    details, hits, reciprocals, ndcgs, latencies = [], [], [], [], []
    citation_yes = citation_total = role_context = role_cited = role_total = 0
    complete_yes = complete_total = false_refuse = missed_refuse = refuse_total = 0
    permission_leaks = version_leaks = critical_failures = 0
    safety_complete = True
    tiers = set()
    for case in dataset["cases"]:
        row = by_id.get(case["case_id"])
        if row is None:
            blockers.add("missing_case_results")
            details.append({"case_id": case["case_id"], "status": "missing"})
            continue
        tiers.add(row.get("evidence_tier"))
        if any(row.get(key) != expected for key, expected in (
                ("dataset_version", dataset["dataset_version"]),
                ("corpus_hash", manifest["corpus_hash"]))):
            blockers.add("result_snapshot_mismatch")
        if row.get("status") != "completed":
            blockers.add(row.get("status") or "incomplete_result")
        for key in ("permission_leaks", "version_leaks", "critical_failures"):
            if type(row.get(key)) is not int or row[key] < 0:
                blockers.add("missing_safety_measurements")
                safety_complete = False
        safety_value = lambda key: row[key] if type(row.get(key)) is int and row[key] >= 0 else 0
        permission_leaks += safety_value("permission_leaks")
        version_leaks += safety_value("version_leaks")
        critical_failures += safety_value("critical_failures")
        latency = row.get("latency_ms")
        if isinstance(latency, (int, float)) and math.isfinite(latency) and latency >= 0:
            latencies.append(latency)
        else:
            blockers.add("invalid_latency")
        gold = case.get("gold")
        if (case.get("review_status") != "approved" or not gold or not gold.get("reviewer")
                or gold.get("corpus_hash") != manifest["corpus_hash"]):
            blockers.add("unreviewed_or_unresolved_gold")
            details.append({"case_id": case["case_id"], "status": "unreviewed",
                            "split": case["split"]})
            continue
        refused = row.get("answer_status") != "grounded"
        must_refuse = gold.get("must_refuse")
        if type(must_refuse) is bool:
            refuse_total += 1
            false_refuse += int(refused and not must_refuse)
            missed_refuse += int(not refused and must_refuse)
        else:
            blockers.add("missing_refusal_gold")
        relevant = set(gold.get("relevant_ids", []))
        ranked = list(dict.fromkeys(row.get("retrieved_ids", [])))
        detail = {"case_id": case["case_id"], "status": row.get("status"),
                  "split": case["split"], "false_refusal": refused and must_refuse is False,
                  "missed_refusal": not refused and must_refuse is True}
        if relevant:
            hit = int(bool(relevant.intersection(ranked[:5])))
            rr = next((1 / rank for rank, identity in enumerate(ranked, 1) if identity in relevant), 0)
            dcg = sum(1 / math.log2(rank + 1) for rank, identity in enumerate(ranked[:5], 1) if identity in relevant)
            ideal = sum(1 / math.log2(rank + 1) for rank in range(1, min(5, len(relevant)) + 1))
            # The release gate uses holdout only; tuning cases remain in per-case results.
            detail.update(hit5=hit, mrr=rr, ndcg5=dcg / ideal)
            if case["split"] == "holdout":
                hits.append(hit); reciprocals.append(rr); ndcgs.append(dcg / ideal)
        if case["split"] == "holdout":
            for alternatives in gold.get("roles", {}).values():
                role_total += 1
                role_context += int(bool(set(alternatives).intersection(row.get("context_ids", []))))
                role_cited += int(bool(set(alternatives).intersection(row.get("cited_ids", []))))
            assessment = row.get("assessment", {})
            if not assessment.get("reviewer"):
                blockers.add("missing_answer_assessment")
            else:
                supported, total = assessment.get("supported_citations"), assessment.get("total_citations")
                if type(supported) is int and type(total) is int and 0 <= supported <= total:
                    citation_yes += supported
                    citation_total += total
                else:
                    blockers.add("invalid_citation_assessment")
                if type(assessment.get("complete")) is bool:
                    complete_total += 1
                    complete_yes += int(assessment["complete"])
                else:
                    blockers.add("missing_completeness_assessment")
        details.append(detail)
    if not hits:
        blockers.add("no_labeled_holdout")
    if not citation_total:
        blockers.add("no_assessed_citations")
    ratio = lambda value, count: value / count if count else None
    metrics = {
        "hit5": ratio(sum(hits), len(hits)), "hit5_samples": len(hits),
        "mrr": ratio(sum(reciprocals), len(reciprocals)), "mrr_samples": len(reciprocals),
        "ndcg5": ratio(sum(ndcgs), len(ndcgs)), "ndcg5_samples": len(ndcgs),
        "citation_precision": ratio(citation_yes, citation_total), "citation_precision_samples": citation_total,
        "role_context_rate": ratio(role_context, role_total), "role_cited_rate": ratio(role_cited, role_total),
        "role_samples": role_total, "completeness": ratio(complete_yes, complete_total),
        "completeness_samples": complete_total, "false_refusals": false_refuse,
        "missed_refusals": missed_refuse, "refusal_samples": refuse_total,
        "latency_p95_ms": sorted(latencies)[max(0, math.ceil(len(latencies) * .95) - 1)] if latencies else None,
        "latency_samples": len(latencies),
        "permission_leaks": permission_leaks if safety_complete else None,
        "version_leaks": version_leaks if safety_complete else None,
        "critical_failures": critical_failures if safety_complete else None,
    }
    return {"schema": "rag-results-v1", "dataset_version": dataset["dataset_version"],
            "corpus_hash": manifest["corpus_hash"], "config_fingerprint": manifest.get("config_fingerprint"),
            "evaluation_environment": manifest.get("evaluation_environment"),
            "evidence_tier": next(iter(tiers)) if len(tiers) == 1 else "mixed",
            "blockers": sorted(blockers), "metrics": metrics, "cases": details,
            "external_calls": 0}


def retrieve_isolated(database_file, project_id, dataset):
    """Replay keyword retrieval on an in-memory copy; never call providers."""
    import sqlite3
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from sqlalchemy.pool import StaticPool

    for key, value in {
        "ENVIRONMENT": "test", "AUTH_MODE": "optional", "LLM_PROVIDER": "mock",
        "EMBEDDING_PROVIDER": "mock", "VECTOR_STORE_PROVIDER": "mock",
        "RERANKER_ENABLED": "false", "CITATION_SUPPORT_CHECK": "off",
        "RAG_QUERY_PLANNING_ENABLED": "false", "LINEAGE_GIT_ENABLED": "false",
    }.items():
        os.environ[key] = value
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from app.services.retrieval import HybridRetriever
    from app.services.rag.context_assembly import assemble_context

    manifest = freeze_environment(database_file, project_id, dataset)
    identity = {"dataset_version": dataset["dataset_version"],
                "corpus_hash": manifest["corpus_hash"], "code_hash": manifest["code_hash"],
                "config_fingerprint": manifest["config_fingerprint"]}
    source = sqlite3.connect(Path(database_file).resolve(strict=True).as_uri() + "?mode=ro", uri=True)
    copy = sqlite3.connect(":memory:", check_same_thread=False)
    try:
        source.backup(copy)
    finally:
        source.close()
    engine = create_engine("sqlite://", creator=lambda: copy, poolclass=StaticPool)
    rows = []
    try:
        with Session(engine) as db:
            for case in dataset["cases"]:
                started = time.perf_counter()
                try:
                    log, items = HybridRetriever(db).search(
                        project_id, case["query"], top_k=50,
                        retrieval_mode="keyword_only", commit=False)
                    context, assembly = assemble_context(items, budget=6000)
                    rows.append({
                        **identity, "case_id": case["case_id"], "status": "retrieval_only",
                        "evidence_tier": "sqlite_keyword", "external_calls": 0,
                        "retrieved_ids": [item["knowledge_unit_id"] for item in items],
                        "context_ids": [item["knowledge_unit_id"] for item in context],
                        "cited_ids": [], "context_assembly": assembly,
                        "diagnostics": log.filters_json,
                        "latency_ms": (time.perf_counter() - started) * 1000,
                    })
                except Exception as error:
                    db.rollback()
                    rows.append({**identity, "case_id": case["case_id"], "status": "failed",
                                 "evidence_tier": "sqlite_keyword", "external_calls": 0,
                                 "error_type": type(error).__name__})
    finally:
        engine.dispose()
    return rows


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def normalize_sources(paths):
    merged = {}
    sources = []
    for path in paths:
        raw = read_json(path)
        rows = raw.get("cases", []) if isinstance(raw, dict) else raw
        source_hash = digest(raw)
        sources.append({"name": Path(path).name, "sha256": source_hash, "count": len(rows)})
        for row in rows:
            query = row.get("question") or row.get("query") or ""
            key = " ".join(unicodedata.normalize("NFKC", query).split())
            if not key:
                raise ValueError("empty query in source dataset")
            entry = merged.setdefault(key, {
                "case_id": digest(key)[:16], "query": query,
                "families": [], "provenance": [], "annotations": [],
                # Legacy engineering labels are never silently promoted to gold.
                "review_status": "needs_business_review",
            })
            family = row.get("family") or row.get("category") or "unclassified"
            if family not in entry["families"]:
                entry["families"].append(family)
            entry["provenance"].append({
                "source": Path(path).name, "source_sha256": source_hash,
                "original_id": row.get("id") or row.get("case_id"),
                "original_split": row.get("split"),
            })
            annotation = {
                "expected": row.get("expected") or row.get("golden") or {},
                "evidence_anchor": row.get("evidence_anchor"),
                "annotator": row.get("annotator") or row.get("source") or "engineering",
            }
            if annotation not in entry["annotations"]:
                entry["annotations"].append(annotation)
    cases = sorted(merged.values(), key=lambda row: row["case_id"])
    # Components join shared families and annotated source documents. A small
    # corpus can legitimately have one component: report that, never fake a split.
    groups = {}
    for case in cases:
        keys = {f"family:{name}" for name in case["families"]}
        for annotation in case["annotations"]:
            expected = annotation["expected"]
            names = expected.get("document_family") or []
            for name in ([names] if isinstance(names, str) else names):
                keys.add(f"document:{name}")
            anchor = annotation.get("evidence_anchor")
            if anchor:
                keys.add(f"document:{anchor.split('!')[0]}")
        overlapping = [group for group, members in groups.items() if members["keys"] & keys]
        group = overlapping[0] if overlapping else case["case_id"]
        target = groups.setdefault(group, {"keys": set(), "cases": []})
        for other in overlapping[1:]:
            target["keys"].update(groups[other]["keys"])
            target["cases"].extend(groups.pop(other)["cases"])
        target["keys"].update(keys)
        target["cases"].append(case)
    for group, members in groups.items():
        split = "holdout" if int(digest(sorted(members["keys"]))[:8], 16) % 5 == 0 else "tuning"
        for case in members["cases"]:
            case.update(group_id=group, split=split)
    return {"schema": "rag-regression-v1", "sources": sources, "cases": cases,
            "deduplicated_count": len(cases), "group_count": len(groups),
            "blockers": ["business_labels_not_reviewed", "corpus_anchors_not_resolved"]
            + (["independent_holdout_unavailable"] if len(groups) < 2
               or len({case["split"] for case in cases}) < 2 else [])}


def compare(baseline, candidate):
    reasons = []
    for key in ("dataset_version", "corpus_hash", "evaluation_environment"):
        if not baseline.get(key) or baseline.get(key) != candidate.get(key):
            reasons.append(f"incomparable:{key}")
    for payload in (baseline, candidate):
        if payload.get("blockers"):
            reasons.append("blocked_evaluation")
        if payload.get("evidence_tier") not in {"real_components", "real_model"}:
            reasons.append("business_acceptance_requires_real_components")
        for metric in ("hit5", "mrr", "citation_precision", "latency"):
            count = payload.get("metrics", {}).get(f"{metric}_samples")
            if type(count) is not int or count <= 0:
                reasons.append(f"missing_denominator:{metric}")
    metrics = candidate.get("metrics", {})
    for key in ("permission_leaks", "version_leaks", "critical_failures"):
        if metrics.get(key) != 0:
            reasons.append(key)
    for key in ("hit5", "mrr", "citation_precision"):
        old, new = baseline.get("metrics", {}).get(key), metrics.get(key)
        if not isinstance(old, (int, float)) or not isinstance(new, (int, float)):
            reasons.append(f"missing:{key}")
        elif not math.isfinite(old) or not math.isfinite(new) or new < old:
            reasons.append(f"regressed:{key}")
        if metrics.get(f"{key}_samples", 0) <= 0:
            reasons.append(f"missing_denominator:{key}")
    old = baseline.get("metrics", {}).get("latency_p95_ms")
    new = metrics.get("latency_p95_ms")
    if not isinstance(old, (int, float)) or not isinstance(new, (int, float)) or old <= 0:
        reasons.append("missing:latency_p95_ms")
    elif not math.isfinite(old) or not math.isfinite(new) or new < 0 or new > old * 1.2:
        reasons.append("regressed:latency_p95_ms")
    return {"passed": not reasons, "reasons": sorted(set(reasons))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    snap = sub.add_parser("snapshot")
    snap.add_argument("--sources", nargs="+", required=True)
    snap.add_argument("--output", required=True)
    check = sub.add_parser("check")
    check.add_argument("snapshot")
    compare_parser = sub.add_parser("compare")
    compare_parser.add_argument("--baseline", required=True)
    compare_parser.add_argument("--candidate", required=True)
    tests = sub.add_parser("correctness")
    tests.add_argument("--junitxml")
    freeze = sub.add_parser("freeze")
    freeze.add_argument("--database-file", required=True)
    freeze.add_argument("--project-id", type=int, required=True)
    freeze.add_argument("--dataset", required=True)
    freeze.add_argument("--output", required=True)
    evaluate = sub.add_parser("evaluate")
    evaluate.add_argument("--dataset", required=True)
    evaluate.add_argument("--manifest", required=True)
    evaluate.add_argument("--results", required=True)
    evaluate.add_argument("--output", required=True)
    retrieve = sub.add_parser("retrieve")
    retrieve.add_argument("--database-file", required=True)
    retrieve.add_argument("--project-id", type=int, required=True)
    retrieve.add_argument("--dataset", required=True)
    retrieve.add_argument("--output", required=True)
    args = parser.parse_args()
    if args.command == "snapshot":
        payload = normalize_sources(args.sources)
        payload["dataset_version"] = digest(payload)
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"cases": len(payload["cases"]), "dataset_version": payload["dataset_version"],
                          "blockers": payload["blockers"]}, ensure_ascii=False))
    elif args.command == "check":
        payload = read_json(args.snapshot)
        expected = payload.pop("dataset_version")
        if digest(payload) != expected:
            raise SystemExit("snapshot checksum mismatch")
        print(json.dumps({"integrity": "passed", "blockers": payload["blockers"]}))
    elif args.command == "compare":
        result = compare(read_json(args.baseline), read_json(args.candidate))
        print(json.dumps(result))
        raise SystemExit(0 if result["passed"] else 1)
    elif args.command in {"freeze", "evaluate", "retrieve"}:
        dataset = read_json(args.dataset)
        if dataset["dataset_version"] != digest({key: value for key, value in dataset.items() if key != "dataset_version"}):
            raise SystemExit("snapshot checksum mismatch")
        if args.command == "freeze":
            payload = freeze_environment(args.database_file, args.project_id, dataset)
            payload["evaluation_environment"] = digest({"tier": "sqlite_mock",
                "index": payload["index"], "project_id": args.project_id})
        elif args.command == "evaluate":
            payload = evaluate_results(dataset, read_json(args.manifest), read_json(args.results))
        else:
            payload = retrieve_isolated(args.database_file, args.project_id, dataset)
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
        print(json.dumps({"output": str(output),
                          "blockers": payload["blockers"] if isinstance(payload, dict) else ["retrieval_only"],
                          "external_calls": 0}))
    else:
        command = [sys.executable, "-m", "pytest", "-q",
                   "tests/test_rag_upgrade_correctness.py", "tests/test_rag_deterministic_support.py",
                   "tests/test_retrieval_eligibility_unified.py", "tests/test_retrieval_reranker.py",
                   "tests/test_rag_regression.py", "tests/test_vnext2_pinned_versions.py",
                   "tests/test_rag_query_context.py", "tests/test_rag_citation_support.py",
                   "tests/test_agent_knowledge_question.py", "tests/test_retrieval_query_expansion.py",
                   "tests/test_knowledge_rag.py", "tests/test_overnight_citation_status.py",
                   "tests/test_vnext2_citation_trust.py", "tests/test_rag_component_tooling.py",
                   "tests/test_xlsx_parse_diagnostics.py"]
        if args.junitxml:
            command.append(f"--junitxml={args.junitxml}")
        environment = {**os.environ, "ENVIRONMENT": "test", "AUTH_MODE": "optional",
                       "DATABASE_URL": "sqlite://", "LLM_PROVIDER": "mock",
                       "EMBEDDING_PROVIDER": "mock", "VECTOR_STORE_PROVIDER": "mock",
                       "TASK_QUEUE_PROVIDER": "inline", "LINEAGE_GIT_ENABLED": "false",
                       "CITATION_SUPPORT_CHECK": "off", "RERANKER_ENABLED": "false",
                       "RAG_TOKEN_CONTEXT_ENABLED": "false", "RAG_QUERY_PLANNING_ENABLED": "false",
                       "VNEXT_ALLOW_REAL_RUNTIME": "0"}
        raise SystemExit(subprocess.call(command, cwd=Path(__file__).resolve().parents[1],
                                        env=environment))


if __name__ == "__main__":
    main()

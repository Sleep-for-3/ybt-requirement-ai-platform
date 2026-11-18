"""Bind agent-reviewed source anchors and previously unobserved documents."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys

from rag_regression import digest, freeze_environment, read_json
from rag_source_review import write_json


def build(dataset, adjudications, holdout, corpus, source_hash):
    if not holdout.get("cases"):
        raise ValueError("Independent holdout must contain at least one case")
    if not holdout.get("sources"):
        raise ValueError("Independent holdout must declare source documents")
    if adjudications["source_sha256"] != source_hash:
        raise ValueError("Adjudications belong to different workbook bytes")
    decisions = {row[0]: row for row in adjudications["decisions"]}
    if len(decisions) != len(adjudications["decisions"]) or set(decisions) != {c['case_id'] for c in dataset['cases']}:
        raise ValueError("Every original case must have exactly one explicit source review")
    active = [u for u in corpus if u.get("enabled") and u.get("lifecycle") == "active"]
    cases = []
    for case in dataset["cases"]:
        _, anchors, decision, note = decisions[case["case_id"]]
        gold_anchors = []
        for token in anchors.split():
            sheet = adjudications["anchor_prefixes"][token[0]]
            row = int(token[1:])
            matches = [u for u in active if u['file_hash'] == source_hash and u['source_sheet_name'] == sheet
                       and re.match(rf"A{row}:", u["source_cell_range"] or "")]
            if len(matches) != 1:
                raise ValueError(f"Source anchor does not uniquely resolve: {token}")
            gold_anchors.append(matches[0])
        identities = [u['unit_id'] for u in gold_anchors]
        cases.append({**case, "original_split": case["split"], "split": "tuning",
            "review_status": "agent_reviewed", "review_kind": "agent_source_review",
            "gold": {"reviewer": "Codex source review", "decision": decision,
                "expected_summary": note, "must_refuse": decision == "refuse",
                "must_confirm": decision in {"pending", "partial", "insufficient"},
                "relevant_ids": identities, "roles": {f"{u['source_sheet_name']}:{u['source_cell_range']}": [u['unit_id']] for u in gold_anchors},
                "evidence": [{key:u[key] for key in ("unit_id", "document_id", "file_hash", "source_sheet_name", "source_cell_range", "content_hash")} for u in gold_anchors],
                "human_business_approved": False}})
    for identity, prefix, start, end, query, answer in holdout["cases"]:
        filename = holdout["sources"][prefix]
        candidates = []
        for u in active:
            if u['source'] != filename or u.get('unit_type') != 'sql_text':
                continue
            # SQL source units carry locators in their database metadata; the
            # caller adds them before binding the frozen dataset.
            locator = u.get("locator") or {}
            if type(locator.get("paragraph_index")) is not int:
                continue
            if locator.get("line_start", 10**9) <= start and locator.get("line_end", -1) >= end:
                candidates.append(u)
        if not candidates:
            raise ValueError(f"Holdout source lines not covered by a citable unit: {identity}")
        # Prefer the smallest complete interval; sql_summary is never evidence.
        u = min(candidates, key=lambda x:len(x['content']))
        cases.append({"case_id": identity, "query": query, "split": "holdout",
            "families": ["archived_credit_card_sql_implementation"],
            "provenance": [{"source": filename, "source_sha256": u['file_hash'], "lines": [start,end]}],
            "review_status": "agent_reviewed", "review_kind": "agent_source_review",
            "gold": {"reviewer": "Codex source review", "decision": "answerable", "expected_summary": answer,
                "must_refuse": False, "must_confirm": False, "relevant_ids": [u['unit_id']],
                "roles": {"archived_sql_implementation": [u['unit_id']]},
                "evidence": [{key:u[key] for key in ("unit_id", "document_id", "file_hash", "content_hash")}],
                "source_lines": [start,end], "human_business_approved": False}})
    split_documents = {split: sorted({e['document_id'] for c in cases if c['split']==split for e in c['gold']['evidence']}) for split in ('tuning','holdout')}
    split_files = {split: sorted({e['file_hash'] for c in cases if c['split']==split for e in c['gold']['evidence']}) for split in ('tuning','holdout')}
    if not split_documents['holdout'] or not split_files['holdout']:
        raise ValueError("Independent holdout must resolve to citable documents and file hashes")
    if set(split_documents['tuning']) & set(split_documents['holdout']) or set(split_files['tuning']) & set(split_files['holdout']):
        raise ValueError("Document/file leakage in the independent holdout")
    for c in cases[:len(dataset['cases'])]:
        if any(name in c['query'] for name in holdout['sources'].values()):
            raise ValueError("Holdout script appeared in an original query")
    result = {"schema": "rag-agent-reviewed-dataset-v1", "previous_dataset_version": dataset['dataset_version'],
        "review_policy": "agent_source_review_not_human_business_signoff", "created_at": datetime.now(timezone.utc).isoformat(),
        "split_policy": "all_previously_observed_cases_tuning_new_original_sql_documents_holdout",
        "sources": [{"source_sha256":source_hash}, *[{"source":name} for name in holdout['sources'].values()]],
        "cases":cases, "split_documents":split_documents, "split_file_hashes":split_files,
        "blockers":["human_business_signoff_not_supplied"],
        "summary":{"original_cases_reviewed":len(decisions), "new_holdout_cases":len(holdout['cases']),
            "decisions":dict(Counter(c['gold']['decision'] for c in cases)), "human_approved":0}}
    result['dataset_version'] = digest(result)
    return result


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--workspace', required=True)
    p.add_argument('--dataset', required=True)
    p.add_argument('--adjudications', required=True)
    p.add_argument('--holdout', required=True)
    p.add_argument('--output-directory', required=True)
    a=p.parse_args()
    root=Path(a.workspace).resolve()
    import os
    os.environ.update(read_json(root/'environment.json'))
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
    from app.core.database import SessionLocal
    from app.models import KnowledgeUnit
    from sqlalchemy import select
    state=read_json(root/'state.json')
    dataset=read_json(a.dataset)
    with SessionLocal() as db:
        manifest=freeze_environment(None,state['corpus_project_id'],dataset,session=db)
        by_id={u.id:u for u in db.scalars(select(KnowledgeUnit).where(KnowledgeUnit.project_id==state['corpus_project_id']))}
        extended=[{**u,'unit_type':by_id[u['unit_id']].unit_type,
                   'locator':(by_id[u['unit_id']].metadata_json or {}).get('locator',{})}
                  for u in manifest['corpus']]
        adjudications=read_json(a.adjudications)
        result=build(dataset,adjudications,read_json(a.holdout),extended,adjudications['source_sha256'])
        manifest=freeze_environment(None,state['corpus_project_id'],result,session=db)
        for c in result['cases']:
            c['gold']['corpus_hash']=manifest['corpus_hash']
        result.pop('dataset_version')
        result['dataset_version']=digest(result)
        manifest['dataset_version']=result['dataset_version']
        target=Path(a.output_directory)
        if (target/'reviewed-dataset.json').exists():
            raise ValueError('Never overwrite an existing frozen reviewed dataset')
        write_json(target/'reviewed-dataset.json',result)
        write_json(target/'reviewed-environment.json',manifest)
        print(json.dumps({'summary':result['summary'],'split_documents':result['split_documents'],'dataset_version':result['dataset_version']}))

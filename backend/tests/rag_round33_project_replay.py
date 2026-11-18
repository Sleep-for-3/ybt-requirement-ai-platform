"""Guarded retrieval-only replay for the previously observed round29 dataset."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

REPOSITORY = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY / "backend" / "scripts"))

EXPECTED_DATASET = "10120bb574470ab94b7a0ba781c80600fcb306fd91a2d787ed2d068c1bdfea3a"
EXPECTED_CORPUS = "072efb43292a6e5c23328a9ed912bf47fd1adaa7702ae109ddc81a77c1221948"
EXPECTED_COLLECTION = "rag_p0_20261113_p7_v8_901a207e1369_d512"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--enable-sql-identifier-boost", action="store_true")
    args = parser.parse_args()

    os.environ.update({
        "LLM_PROVIDER": "mock",
        "QUERY_EXPANSION_ENABLED": "false",
        "RETRIEVAL_SQL_IDENTIFIER_BOOST_ENABLED": str(args.enable_sql_identifier_boost).lower(),
    })

    import rag_component_acceptance as acceptance

    settings = acceptance.local_environment_only()
    if settings.query_expansion_enabled or settings.retrieval_sql_identifier_boost_enabled != args.enable_sql_identifier_boost:
        raise ValueError("Retrieval experiment flags do not match the requested group")

    original_read_json = acceptance.read_json

    def read_round29_project_state(path):
        value = original_read_json(path)
        if Path(path).name == "state.json":
            value["corpus_project_id"] = 7
        return value

    acceptance.read_json = read_round29_project_state
    original_freeze = acceptance.freeze_environment

    def verify_round29_identity(engine, project_id, dataset, **kwargs):
        manifest = original_freeze(engine, project_id, dataset, **kwargs)
        index = manifest.get("index") or {}
        config = manifest.get("config") or {}
        if (
            project_id != 7
            or manifest.get("dataset_version") != EXPECTED_DATASET
            or manifest.get("corpus_hash") != EXPECTED_CORPUS
            or len(manifest.get("corpus") or []) != 5985
            or index.get("id") != 8
            or index.get("collection") != EXPECTED_COLLECTION
            or "source_parse_has_blocking_findings" in manifest.get("blockers", [])
            or config.get("query_expansion_enabled") is not False
            or config.get("retrieval_sql_identifier_boost_enabled") is not args.enable_sql_identifier_boost
        ):
            raise ValueError("Round29 dataset, corpus, index or retrieval configuration identity mismatch")
        return manifest

    acceptance.freeze_environment = verify_round29_identity
    acceptance.replay(args.workspace.resolve(), args.dataset.resolve(), args.output.resolve())


if __name__ == "__main__":
    main()

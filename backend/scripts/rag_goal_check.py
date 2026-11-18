"""Read-only structural guard for the long-run goal ledger; never marks goals done."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re


POLICY = {
    "G-P0-A": ((), ("source_traceability", "split_integrity", "approval_boundary")),
    "G-P0-B": ((), ("correctness", "governance", "judge_paths", "degradation")),
    "G-P0-C": (("G-P0-B",), ("components", "model", "browser", "version_original")),
    "G-P1-A": (("G-P0-B", "G-P0-C"), ("stage_metrics", "holdout", "quality_latency_cost", "rollback")),
    "G-P1-B": (("G-P0-B", "G-P0-C"), ("history_bounds", "authorization", "planning_bounds", "real_acceptance")),
    "G-P1-C": (("G-P1-A",), ("shadow", "calibration", "holdout", "judge_agreement")),
    "G-P2-CHUNK": (("G-P1-A", "G-P1-C"), ("single_factor", "independent_index", "quality_latency_cost", "rollback")),
    "G-P2-EMBED": (("G-P1-A", "G-P1-C"), ("single_factor", "independent_index", "quality_latency_cost", "rollback")),
    "G-P2-INDEX": (("G-P1-A", "G-P1-C"), ("single_factor", "independent_index", "quality_latency_cost", "rollback")),
    "G-UX-AUDIT": ((), ("current_ui", "official_patterns", "interaction_findings")),
    "G-UX-IMPLEMENT": (("G-UX-AUDIT",), ("changes", "contract", "recovery_accessibility")),
    "G-UX-ACCEPT": (("G-UX-IMPLEMENT",), ("desktop", "mobile", "keyboard", "real_states", "evidence_permissions")),
    "G-REMOTE-INVENTORY": ((), ("host_identity", "services", "data_locations")),
    "G-REMOTE-BACKUP": (("G-REMOTE-INVENTORY",), ("database", "uploads", "deployment", "restore")),
    "G-REMOTE-DEPLOY": (("G-REMOTE-BACKUP",), ("release_identity", "isolated_start", "health", "controlled_switch")),
    "G-REMOTE-ACCEPT": (("G-REMOTE-DEPLOY",), ("components", "model", "browser", "preserved_data")),
    "G-REMOTE-ROLLBACK": (("G-REMOTE-DEPLOY",), ("previous_release", "compatibility", "verified_commands")),
    "G-FINAL-DELIVERY": ((), ("status_table", "all_evidence", "metrics", "external_items", "recovery")),
}
STATUSES = {"pending", "in_progress", "verified", "blocked_external", "awaiting_business"}
REQUIRED_FILES = ("GOAL-LOCK.md", "CURRENT-CHECKPOINT.md", "NEXT-TASK.md", "FAILURES.md", "BUDGET.json")
HASH_PATTERN = re.compile(r"[0-9a-f]{64}")


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _evidence_file(base: Path, value: object, errors: list[str], label: str) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{label}: missing evidence path")
        return None
    path = (base / value).resolve()
    if not path.is_file():
        errors.append(f"{label}: evidence file missing: {value}")
        return None
    return path


def check(root: Path, *, require_complete: bool = False, source_hash: str | None = None) -> dict:
    errors: list[str] = []
    for name in REQUIRED_FILES:
        path = root / name
        if not path.is_file() or not path.stat().st_size:
            errors.append(f"required checkpoint missing or empty: {name}")
    try:
        ledger = _read_json(root / "GOALS.json")
        goals = ledger["goals"]
        if not isinstance(goals, list) or not all(isinstance(goal, dict) for goal in goals):
            raise ValueError("goals must be a list of objects")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return {"consistent": False, "complete": False, "errors": errors + [f"invalid goal ledger: {type(exc).__name__}"]}
    ids = [goal.get("id") for goal in goals]
    if set(str(value) for value in ids) != set(POLICY) or len(ids) != len(POLICY):
        errors.append("goal coverage changed: exactly the original 18 unique goal IDs are required")
    by_id = {goal.get("id"): goal for goal in goals if isinstance(goal.get("id"), str)}
    for goal in goals:
        goal_id = str(goal.get("id"))
        status = goal.get("status")
        if not isinstance(status, str) or status not in STATUSES:
            errors.append(f"{goal_id}: invalid status")
        evidence = goal.get("evidence", [])
        if not isinstance(evidence, list):
            errors.append(f"{goal_id}: evidence must be a list")
            evidence = []
        for value in evidence:
            _evidence_file(root, value, errors, goal_id)
        if status != "verified" or goal_id not in POLICY:
            continue
        dependencies, criteria = POLICY[goal_id]
        if goal_id == "G-FINAL-DELIVERY":
            dependencies = tuple(key for key in POLICY if key != goal_id)
        for dependency in dependencies:
            if by_id.get(dependency, {}).get("status") != "verified":
                errors.append(f"{goal_id}: unverified dependency {dependency}")
        closure_path = _evidence_file(root, goal.get("closure_record"), errors, goal_id)
        if closure_path is None:
            continue
        try:
            closure = _read_json(closure_path)
            identity = closure["source_hash"]
            if closure["goal_id"] != goal_id or not isinstance(identity, str) or not HASH_PATTERN.fullmatch(identity):
                raise ValueError("invalid closure identity")
            if source_hash is not None and identity != source_hash:
                errors.append(f"{goal_id}: closure source identity differs from candidate")
            results = closure["criteria"]
            for criterion in criteria:
                result = results.get(criterion, {})
                if result.get("passed") is not True:
                    errors.append(f"{goal_id}/{criterion}: missing passing criterion")
                path = _evidence_file(closure_path.parent, result.get("path"), errors, f"{goal_id}/{criterion}")
                if path and hashlib.sha256(path.read_bytes()).hexdigest() != result.get("sha256"):
                    errors.append(f"{goal_id}/{criterion}: evidence hash mismatch")
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            errors.append(f"{goal_id}: invalid closure record")
    try:
        budget = _read_json(root / "BUDGET.json")
        keys = ("max_new_provider_requests", "max_new_total_tokens", "provider_requests_used", "provider_requests_reserved", "total_tokens_used", "unknown_usage_requests")
        if any(type(budget.get(key)) is not int or budget[key] < 0 for key in keys):
            raise ValueError("budget counters must be nonnegative integers")
        if budget["provider_requests_used"] + budget["provider_requests_reserved"] > budget["max_new_provider_requests"]:
            errors.append("request budget exceeded, including reservations")
        reserved_tokens = budget.get("total_tokens_reserved", 0)
        if type(reserved_tokens) is not int or reserved_tokens < 0:
            errors.append("invalid token reservation counter")
        elif budget["total_tokens_used"] + reserved_tokens > budget["max_new_total_tokens"]:
            errors.append("token budget exceeded, including reservations")
        if budget["unknown_usage_requests"] > budget["provider_requests_used"]:
            errors.append("unknown usage count exceeds requests used")
    except (OSError, ValueError, KeyError, TypeError):
        errors.append("invalid budget ledger")
    remaining = [str(goal.get("id")) for goal in goals if goal.get("status") != "verified"]
    complete = not remaining and not errors
    if require_complete and not complete:
        errors.append("delivery incomplete: outstanding goals or invalid evidence")
    return {"consistent": not errors, "complete": complete, "counts": dict(Counter(str(goal.get("status")) for goal in goals)), "remaining": remaining, "errors": errors}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2] / "docs/development/long-run")
    parser.add_argument("--require-complete", action="store_true")
    parser.add_argument("--source-hash", help="Require all verified closures to match this candidate source SHA-256")
    args = parser.parse_args()
    if args.source_hash and not HASH_PATTERN.fullmatch(args.source_hash):
        parser.error("--source-hash must be a lowercase SHA-256")
    result = check(args.root, require_complete=args.require_complete, source_hash=args.source_hash)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["consistent"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

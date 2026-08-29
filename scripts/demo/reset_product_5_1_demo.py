from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from product_5_1_common import DEFAULT_RUNTIME_ROOT, DEMO_PROJECT_NAME, SOURCE_DATABASES


GENERATED_REPORTS = (
    "build_summary.json",
    "platform_bootstrap_summary.json",
    "platform_verification_summary.json",
)


def build_reset_plan(runtime_root: Path) -> dict[str, Any]:
    resolved_root = runtime_root.resolve()
    known_names = set(SOURCE_DATABASES.values()) | set(GENERATED_REPORTS)
    existing_files = [item for item in resolved_root.iterdir()] if resolved_root.is_dir() else []
    runtime_files = sorted(
        str(item.resolve())
        for item in existing_files
        if item.is_file() and item.name in known_names
    )
    retained_unknown_files = sorted(
        str(item.resolve())
        for item in existing_files
        if item.name not in known_names
    )
    return {
        "mode": "dry-run",
        "project_name": DEMO_PROJECT_NAME,
        "runtime_root": str(resolved_root),
        "runtime_files": runtime_files,
        "retained_unknown_files": retained_unknown_files,
        "platform_cleanup": {
            "status": "not-supported",
            "detail": (
                "The current project API has no project-delete endpoint. The exact demo project container "
                "and its governed objects are retained for idempotent bootstrap reuse."
            ),
        },
    }


def validate_execute_confirmation(value: str | None) -> None:
    if value != DEMO_PROJECT_NAME:
        raise ValueError(f"--confirm-project-name must equal the exact demo project name: {DEMO_PROJECT_NAME}")


def execute_reset(plan: dict[str, Any]) -> dict[str, Any]:
    runtime_root = Path(plan["runtime_root"]).resolve()
    deleted: list[str] = []
    for raw_path in plan["runtime_files"]:
        path = Path(raw_path).resolve()
        if path.parent != runtime_root:
            raise RuntimeError(f"Refusing to delete a file outside the exact runtime directory: {path}")
        path.unlink(missing_ok=True)
        deleted.append(str(path))
    result = dict(plan)
    result["mode"] = "execute"
    result["deleted_runtime_files"] = deleted
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Safely reset only generated Product 5.1 runtime artifacts (dry-run by default)."
    )
    parser.add_argument("--runtime-root", type=Path, default=DEFAULT_RUNTIME_ROOT)
    parser.add_argument("--dry-run", action="store_true", help="Explicitly request the default preview mode.")
    parser.add_argument("--execute", action="store_true", help="Delete only the exact files shown in the plan.")
    parser.add_argument("--confirm-project-name")
    args = parser.parse_args()
    if args.execute and args.dry_run:
        raise SystemExit("Choose either --execute or --dry-run, not both.")

    plan = build_reset_plan(args.runtime_root)
    if args.execute:
        try:
            validate_execute_confirmation(args.confirm_project_name)
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
        plan = execute_reset(plan)
    print(json.dumps(plan, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

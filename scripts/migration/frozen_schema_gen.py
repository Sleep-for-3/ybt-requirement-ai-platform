"""Freeze the *historical* schema of every lineage migration revision.

``backend/alembic/versions/202607070001_initial_schema.py`` used to call
``Base.metadata.create_all()``, so every historical revision silently created
the schema of *the current working tree* instead of the schema of its own date.
That made the migration chain unreproducible.

This tool rebuilds the real history from git:

1. ``_metadata_dump.py`` is executed inside a read-only ``git archive`` export
   of the commit that introduced each revision, producing a JSON description of
   the metadata that existed at that moment;
2. consecutive dumps are diffed so we know exactly which tables each revision
   introduced (and which existing tables changed);
3. ``backend/app/schema_freeze/data.py`` is regenerated from those facts.

The generated module is plain data: no import of ``app.models`` happens at
migration run time any more.

Usage (run from the repository root, inside the dev container)::

    python scripts/migration/frozen_schema_gen.py --probe-dir .tmp-migration-probe \
        --out backend/app/schema_freeze/data.py --report /tmp/frozen-schema-report.md
"""

from __future__ import annotations

import argparse
import json
import pprint
from pathlib import Path


# revision -> (commit that introduced it, backend package dir inside that commit)
REVISION_HISTORY: dict[str, tuple[str, str]] = {
    "202607070001": ("ff1f41f", "ybt-requirement-ai-platform/backend"),
    "202607070002": ("5815f28", "ybt-requirement-ai-platform/backend"),
    "202607070003": ("c97fb32", "ybt-requirement-ai-platform/backend"),
    "202607100004": ("aeaeaa7", "ybt-requirement-ai-platform/backend"),
    "202607140005": ("8632330", "ybt-requirement-ai-platform/backend"),
    "202607140006": ("d2344b4", "ybt-requirement-ai-platform/backend"),
    "202607150007": ("dbdf9fc", "ybt-requirement-ai-platform/backend"),
    "202607150008": ("580efce", "ybt-requirement-ai-platform/backend"),
    "202607150009": ("0674072", "ybt-requirement-ai-platform/backend"),
    "202607200010": ("c01f2dd", "ybt-requirement-ai-platform/backend"),
    "202607220011": ("345064b", "ybt-requirement-ai-platform/backend"),
    "202607230012": ("9995884", "ybt-requirement-ai-platform/backend"),
    "202607270013": ("eda378d", "backend"),
    "202607300014": ("ece473b", "backend"),
    "202608200015": ("1c6f2cd", "backend"),
    "202608200016": ("ae41592", "backend"),
    "202608260017": ("8ba28fc", "backend"),
    "202608270018": ("2116802", "backend"),
    "202608270019": ("05ddfe3", "backend"),
    "202608280020": ("80f5d33", "backend"),
    "202608290021": ("b31faea", "backend"),
}

# Revisions that were written after the last frozen history point.  Their table
# sets are reconciled by the equality gate in
# ``backend/tests/test_migration_schema_freeze.py`` instead of by this tool.
POST_FREEZE_REVISIONS = (
    "202609100022",
    "202609100023",
    "202609100024",
    "202609100025",
)


def load_dumps(probe_dir: Path) -> dict[str, dict]:
    dumps = {}
    for revision in REVISION_HISTORY:
        path = probe_dir / f"{revision}.json"
        if not path.is_file():
            raise SystemExit(
                f"missing metadata dump {path}; run the git-archive probe described in the module docstring"
            )
        dumps[revision] = json.loads(path.read_text(encoding="utf-8"))
    return dumps


def _column_signature(table: dict) -> dict[str, str]:
    return {column["name"]: json.dumps(column, sort_keys=True) for column in table["columns"]}


def diff_revisions(previous: dict, current: dict) -> tuple[list[str], dict[str, dict]]:
    previous_tables = {table["name"]: table for table in previous["tables"]}
    current_tables = {table["name"]: table for table in current["tables"]}

    added = [table["name"] for table in current["tables"] if table["name"] not in previous_tables]
    removed = sorted(set(previous_tables) - set(current_tables))
    mutated: dict[str, dict] = {}
    for name, table in current_tables.items():
        if name not in previous_tables:
            continue
        before, after = previous_tables[name], table
        before_columns, after_columns = _column_signature(before), _column_signature(after)
        added_columns = sorted(set(after_columns) - set(before_columns))
        removed_columns = sorted(set(before_columns) - set(after_columns))
        changed_columns = sorted(
            name_
            for name_ in set(before_columns) & set(after_columns)
            if before_columns[name_] != after_columns[name_]
        )
        if added_columns or removed_columns or changed_columns:
            mutated[name] = {
                "added_columns": added_columns,
                "removed_columns": removed_columns,
                "changed_columns": changed_columns,
            }
    if removed:
        mutated["<removed tables>"] = {"removed_columns": removed, "added_columns": [], "changed_columns": []}
    return added, mutated


def build_plan(dumps: dict[str, dict]) -> tuple[dict[str, list[str]], dict[str, dict]]:
    revisions = list(REVISION_HISTORY)
    creation: dict[str, list[str]] = {revisions[0]: [table["name"] for table in dumps[revisions[0]]["tables"]]}
    mutations: dict[str, dict] = {}
    for index in range(1, len(revisions)):
        added, mutated = diff_revisions(dumps[revisions[index - 1]], dumps[revisions[index]])
        creation[revisions[index]] = added
        if mutated:
            mutations[revisions[index]] = mutated
    first_added, first_mutated = diff_revisions({"tables": []}, dumps[revisions[0]])
    if first_mutated:
        mutations[revisions[0]] = first_mutated
    del first_added
    return creation, mutations


def _render_table(table: dict) -> str:
    # ``pprint`` keeps the payload valid Python (True/False/None) while staying
    # deterministic, because the dumps are loaded from sorted JSON.
    return pprint.pformat(table, width=160, sort_dicts=True)


def render_module(dumps: dict[str, dict], creation: dict[str, list[str]]) -> str:
    by_name: dict[str, dict] = {}
    for revision in REVISION_HISTORY:
        for table in dumps[revision]["tables"]:
            by_name.setdefault(table["name"], table)

    lines = [
        '"""Frozen historical schema for the lineage migration chain.',
        "",
        "GENERATED FILE - do not edit by hand.  Regenerate with::",
        "",
        "    python scripts/migration/frozen_schema_gen.py \\",
        "        --probe-dir .tmp-migration-probe --out backend/app/schema_freeze/data.py",
        "",
        "Each entry is the metadata that really existed in the commit that",
        "introduced the owning revision, reconstructed from git history.",
        '"""',
        "",
        "from __future__ import annotations",
        "",
        "# revision -> tables introduced by that revision, in dependency order",
        "CREATED_BY_REVISION: dict[str, tuple[str, ...]] = {",
    ]
    for revision in REVISION_HISTORY:
        names = creation[revision]
        rendered = ", ".join(f'"{name}"' for name in names)
        if not names:
            lines.append(f'    "{revision}": (),')
        elif len(rendered) > 96:
            lines.append(f'    "{revision}": (')
            chunk: list[str] = []
            for name in names:
                chunk.append(f'"{name}"')
                if len(", ".join(chunk)) > 88:
                    lines.append("        " + ", ".join(chunk) + ",")
                    chunk = []
            if chunk:
                lines.append("        " + ", ".join(chunk) + ",")
            lines.append("    ),")
        else:
            lines.append(f'    "{revision}": ({rendered},),')
    lines.append("}")
    lines.append("")
    lines.append("# table name -> frozen metadata description")
    lines.append("TABLES: dict[str, dict] = {")
    for name, table in by_name.items():
        rendered = _render_table(table)
        lines.append(f'    "{name}":')
        lines.append(_indent(rendered, 8) + ",")
    lines.append("}")
    lines.append("")
    lines.append("# revisions reconstructed from git history, in chain order")
    lines.append("SCHEMA_FREEZE_REVISIONS: tuple[str, ...] = (")
    for revision in REVISION_HISTORY:
        lines.append(f'    "{revision}",')
    lines.append(")")
    lines.append("")
    return "\n".join(lines)


def _indent(text: str, spaces: int) -> str:
    prefix = " " * spaces
    return "\n".join(prefix + line for line in text.splitlines())


def render_report(creation: dict[str, list[str]], mutations: dict[str, dict], dumps: dict[str, dict]) -> str:
    lines = ["# 迁移历史重建报告", "", "| revision | 时点表数 | 本 revision 新增表 | 既有表定义变化 |", "|---|---|---|---|"]
    for revision in REVISION_HISTORY:
        total = len(dumps[revision]["tables"])
        added = ", ".join(creation[revision]) or "-"
        mutated = mutations.get(revision, {})
        if mutated:
            mutated_text = "; ".join(
                f"{name}(+" + ",".join(detail["added_columns"]) + "/-" + ",".join(detail["removed_columns"]) + ")"
                for name, detail in mutated.items()
            )
        else:
            mutated_text = "-"
        lines.append(f"| {revision} | {total} | {added} | {mutated_text} |")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--probe-dir", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()

    dumps = load_dumps(args.probe_dir)
    creation, mutations = build_plan(dumps)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(render_module(dumps, creation), encoding="utf-8")
    if args.report:
        args.report.write_text(render_report(creation, mutations, dumps), encoding="utf-8")

    total = sum(len(names) for names in creation.values())
    print(f"revisions={len(creation)} frozen_tables={total}")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

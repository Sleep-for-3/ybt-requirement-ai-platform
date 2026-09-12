"""Dump the SQLAlchemy metadata of an arbitrary checkout as JSON.

The script is executed *inside* a historical checkout that was extracted from
git history (see ``frozen_schema_gen.py``).  It only reads the checkout, never
touches a database and never writes to the checkout.

Usage::

    cd <checkout>/<backend package dir>
    python <repo>/scripts/migration/_metadata_dump.py > /tmp/dump.json
"""

from __future__ import annotations

import json
import sys

import sqlalchemy as sa


_TYPE_PARAM_KEYS = ("length", "precision", "scale", "timezone", "asdecimal")


def _type_spec(type_) -> dict:
    params = {}
    for key in _TYPE_PARAM_KEYS:
        value = getattr(type_, key, None)
        if value is not None:
            params[key] = value
    return {"name": type_.__class__.__name__, "params": params}


def _server_default(column):
    default = column.server_default
    if default is None:
        return None
    arg = getattr(default, "arg", None)
    if arg is None:
        return None
    return str(getattr(arg, "text", arg))


def _column_spec(column) -> dict:
    return {
        "name": column.name,
        "type": _type_spec(column.type),
        "nullable": bool(column.nullable),
        "primary_key": bool(column.primary_key),
        "autoincrement": bool(column.autoincrement) if column.autoincrement is not None else None,
        "server_default": _server_default(column),
    }


def _constraint_specs(table):
    foreign_keys = []
    for constraint in table.foreign_key_constraints:
        foreign_keys.append(
            {
                "name": constraint.name,
                "columns": [element.parent.name for element in constraint.elements],
                "ref_table": sorted({element.column.table.name for element in constraint.elements})[0]
                if len({element.column.table.name for element in constraint.elements}) == 1
                else None,
                "ref_columns": [element.column.name for element in constraint.elements],
                "ondelete": constraint.ondelete,
            }
        )
    uniques = []
    for constraint in table.constraints:
        if isinstance(constraint, sa.UniqueConstraint):
            uniques.append(
                {
                    "name": constraint.name,
                    "columns": [column.name for column in constraint.columns],
                }
            )
    return foreign_keys, uniques


def _index_specs(table):
    indexes = []
    for index in sorted(table.indexes, key=lambda item: (item.name or "")):
        indexes.append(
            {
                "name": index.name,
                "columns": [column.name for column in index.columns],
                "unique": bool(index.unique),
            }
        )
    return indexes


def dump() -> dict:
    import app.models  # noqa: F401  - registers every model on the shared metadata
    from app.core.database import Base

    tables = []
    for table in Base.metadata.sorted_tables:
        foreign_keys, uniques = _constraint_specs(table)
        tables.append(
            {
                "name": table.name,
                "columns": [_column_spec(column) for column in table.columns],
                "foreign_keys": foreign_keys,
                "unique_constraints": uniques,
                "indexes": _index_specs(table),
            }
        )
    return {"table_count": len(tables), "tables": tables}


def main() -> int:
    json.dump(dump(), sys.stdout, ensure_ascii=False, sort_keys=True, indent=1)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

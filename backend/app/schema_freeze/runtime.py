"""Turn the frozen schema data into real tables inside a migration."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

import sqlalchemy as sa

from app.schema_freeze import data as frozen_data


FROZEN_REVISIONS: tuple[str, ...] = tuple(frozen_data.SCHEMA_FREEZE_REVISIONS)

_TYPE_FACTORIES: dict[str, type[sa.types.TypeEngine]] = {
    "Integer": sa.Integer,
    "BigInteger": sa.BigInteger,
    "SmallInteger": sa.SmallInteger,
    "String": sa.String,
    "Text": sa.Text,
    "Unicode": sa.Unicode,
    "UnicodeText": sa.UnicodeText,
    "Boolean": sa.Boolean,
    "Float": sa.Float,
    "Numeric": sa.Numeric,
    "Date": sa.Date,
    "Time": sa.Time,
    "DateTime": sa.DateTime,
    "Interval": sa.Interval,
    "JSON": sa.JSON,
    "LargeBinary": sa.LargeBinary,
    "UUID": sa.Uuid,
}

_NOW_DEFAULT_MARKERS = {"now()", "CURRENT_TIMESTAMP"}


def _build_type(spec: dict[str, Any]) -> sa.types.TypeEngine:
    name = spec["name"]
    factory = _TYPE_FACTORIES.get(name)
    if factory is None:
        raise ValueError(f"unsupported frozen column type {name!r}; extend _TYPE_FACTORIES deliberately")
    params = dict(spec.get("params") or {})
    if name == "DateTime" and params.get("timezone") is None:
        params.pop("timezone", None)
    return factory(**params)


def _build_server_default(value: str | None) -> sa.sql.ClauseElement | None:
    if value is None:
        return None
    # ``server_default=sa.func.now()`` was the historical spelling.  Rebuilding it
    # through ``func`` keeps dialect-specific compilation (PostgreSQL ``now()``,
    # SQLite ``CURRENT_TIMESTAMP``) identical to the original model.
    if value.strip() in _NOW_DEFAULT_MARKERS:
        return sa.func.now()
    return sa.text(value)


def _build_column(spec: dict[str, Any]) -> sa.Column:
    return sa.Column(
        spec["name"],
        _build_type(spec["type"]),
        nullable=bool(spec["nullable"]),
        primary_key=bool(spec["primary_key"]),
        server_default=_build_server_default(spec.get("server_default")),
    )


def _build_constraints(spec: dict[str, Any]):
    constraints: list[sa.schema.ColumnCollectionConstraint] = []
    for foreign_key in spec.get("foreign_keys") or ():
        reference_table = foreign_key.get("ref_table")
        if not reference_table:
            # Composite or ambiguous target: skip rather than guess, the data is
            # asserted to be empty for these cases by the freeze test.
            raise ValueError(f"ambiguous frozen foreign key on {spec['name']}: {foreign_key}")
        targets = [f"{reference_table}.{column}" for column in foreign_key["ref_columns"]]
        constraints.append(
            sa.ForeignKeyConstraint(
                list(foreign_key["columns"]),
                targets,
                name=foreign_key.get("name"),
                ondelete=foreign_key.get("ondelete"),
            )
        )
    for unique in spec.get("unique_constraints") or ():
        constraints.append(sa.UniqueConstraint(*unique["columns"], name=unique.get("name")))
    return constraints


def _build_indexes(spec: dict[str, Any]):
    indexes = []
    for index in spec.get("indexes") or ():
        indexes.append(sa.Index(index["name"], *index["columns"], unique=bool(index.get("unique"))))
    return indexes


def build_table(name: str, metadata: sa.MetaData | None = None) -> sa.Table:
    """Rebuild a frozen table exactly as it existed in its own revision."""

    spec = frozen_data.TABLES.get(name)
    if spec is None:
        raise KeyError(f"{name!r} is not part of the frozen schema")
    metadata = metadata if metadata is not None else sa.MetaData()
    return sa.Table(
        name,
        metadata,
        *[_build_column(column) for column in spec["columns"]],
        *_build_constraints(spec),
        *_build_indexes(spec),
    )


@lru_cache(maxsize=1)
def _full_metadata() -> sa.MetaData:
    """Every frozen table in one MetaData so foreign keys always resolve.

    A revision only *creates* its own tables, but those tables may reference
    tables introduced by other revisions, so the referenced definitions have to
    be present in the same MetaData for DDL compilation.
    """

    metadata = sa.MetaData()
    for name in frozen_data.TABLES:
        build_table(name, metadata)
    return metadata


def frozen_table_names(revision: str) -> tuple[str, ...]:
    try:
        return tuple(frozen_data.CREATED_BY_REVISION[revision])
    except KeyError as exc:  # pragma: no cover - defensive
        raise KeyError(f"{revision!r} is not a frozen revision") from exc


def frozen_table_names_until(revision: str, *, inclusive: bool = True) -> tuple[str, ...]:
    """Every table frozen up to ``revision`` (chain order preserved)."""

    names: list[str] = []
    for candidate in FROZEN_REVISIONS:
        if candidate == revision and not inclusive:
            break
        names.extend(frozen_table_names(candidate))
        if candidate == revision:
            break
    else:
        raise KeyError(f"{revision!r} is not a frozen revision")
    return tuple(names)


def create_frozen_tables(revision: str, bind: sa.engine.Connection | None = None) -> list[str]:
    """Create the tables introduced by ``revision`` (idempotent)."""

    metadata = _full_metadata()
    created: list[str] = []
    for name in frozen_table_names(revision):
        metadata.tables[name].create(bind=bind, checkfirst=True)
        created.append(name)
    return created


def create_frozen_table(name: str, bind: sa.engine.Connection | None = None) -> bool:
    """Create one frozen table (idempotent).  Returns ``True`` when it was missing."""

    metadata = _full_metadata()
    if name not in metadata.tables:
        raise KeyError(f"{name!r} is not part of the frozen schema")
    if bind is not None and sa.inspect(bind).has_table(name):
        return False
    metadata.tables[name].create(bind=bind, checkfirst=True)
    return True


def drop_frozen_tables(revision: str, bind: sa.engine.Connection | None = None) -> list[str]:
    """Drop the tables introduced by ``revision`` in reverse dependency order."""

    metadata = _full_metadata()
    dropped: list[str] = []
    for name in reversed(frozen_table_names(revision)):
        metadata.tables[name].drop(bind=bind, checkfirst=True)
        dropped.append(name)
    return dropped

"""Shared Excel cell normalization for every workbook exporter."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


def excel_value(value: Any) -> Any:
    """Return a value that openpyxl can always write into a worksheet.

    PostgreSQL returns timezone-aware datetimes for ``timestamptz`` columns
    while SQLite returns naive ones, and openpyxl refuses any datetime that
    still carries a ``tzinfo`` ("Excel does not support timezones in
    datetimes").  The instant is preserved by normalizing to UTC and then
    dropping the tzinfo, so the rendered workbook is identical on every
    database.
    """

    if isinstance(value, datetime) and value.tzinfo is not None:
        return value.astimezone(UTC).replace(tzinfo=None)
    return value


__all__ = ["excel_value"]

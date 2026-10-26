r"""One-off patch: project the script template to the *requested* field subset.

Round 75 follow-up.  ``build_requirement_input`` projected the script basis with
all of the requirement's bound columns (``confirmation.field_bindings``, 18 for
T_5_1) even when the caller asked for a single field or a small batch.  The
template block therefore always carried all 18 rows (~32KB), which made any
18-field input impossible to fit under the 128KB safety budget.

The projection now intersects the confirmed bindings with the fields requested
for this run, so the template rows and rules follow the actual request, while
the frozen basis itself stays untouched (identity/hash still comes from the
unprojected frozen basis).
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def patch(relative: str, replacements: list[tuple[str, str]]) -> None:
    path = ROOT / relative
    with path.open("r", encoding="utf-8", newline="") as handle:
        raw = handle.read()
    text = raw.replace("\r\n", "\n")
    for old, new in replacements:
        if text.count(old) != 1:
            raise SystemExit(f"anchor missing/not unique in {relative}: {old[:120]!r}")
        text = text.replace(old, new)
    with path.open("w", encoding="utf-8", newline="") as handle:
        handle.write(text.replace("\n", "\r\n"))
    print(f"patched {relative}")


patch("app/services/mapping/requirement_input.py", [
    (
        """        _bound = set(((content["script_basis"].get("confirmation") or {}).get("field_bindings") or {}).keys())""",
        """        # 只投影本次请求的字段：确认过 18 个字段，不代表一次生成要送 18 行模板。
        _bound = set(((content["script_basis"].get("confirmation") or {}).get("field_bindings") or {}).keys()) & set(bound_codes)""",
    ),
])

print("done")

"""Patch retrieval_eval.py for the query-expansion A/B (round 76 G2). CRLF safe."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(r"C:\Users\李儒伟\Desktop\ai-platform-dsh-20260930-150943 (2)\ai-platform\backend")
EDITS: list[tuple[str, str, str]] = []


def add(old: str, new: str, label: str) -> None:
    EDITS.append((old, new, label))


add(
    "    authority_mode: str = \"boost\"\n",
    "    authority_mode: str = \"boost\"\n    query_expansion: bool = True\n",
    "config-field",
)

add(
    '        parts.append(f"rr{int(self.reranker_enabled)}")\n',
    '        parts.append(f"rr{int(self.reranker_enabled)}")\n'
    '        if not self.query_expansion:\n'
    '            parts.append("noexp")\n',
    "config-label",
)

add(
    '    Config("hybrid_rrf_boost", retrieval_mode="hybrid", fusion_strategy="rrf"),\n',
    '    Config("hybrid_rrf_boost", retrieval_mode="hybrid", fusion_strategy="rrf"),\n'
    '    # G2：query 展开（默认开）与关闭展开的对照。\n'
    '    Config("hybrid_rrf_noexp", retrieval_mode="hybrid", fusion_strategy="rrf", query_expansion=False),\n',
    "config-list",
)

add(
    "    settings.retrieval_authority_mode = config.authority_mode\n",
    "    settings.retrieval_authority_mode = config.authority_mode\n"
    "    settings.query_expansion_enabled = config.query_expansion\n",
    "apply-config",
)

add(
    '        "retrieval_authority_mode": settings.retrieval_authority_mode,\n',
    '        "retrieval_authority_mode": settings.retrieval_authority_mode,\n'
    '        "query_expansion_enabled": settings.query_expansion_enabled,\n',
    "baseline-settings",
)


def main() -> int:
    path = ROOT / "scripts" / "retrieval_eval.py"
    raw = path.read_bytes().decode("utf-8")
    text = raw.replace("\r\n", "\n")
    for old, new, label in EDITS:
        count = text.count(old)
        if count == 0 and new in text:
            print(f"skip {label}")
            continue
        if count != 1:
            print(f"FAIL {label}: count={count}")
            return 1
        text = text.replace(old, new, 1)
        print(f"ok {label}")
    path.write_bytes(text.replace("\n", "\r\n").encode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

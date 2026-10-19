"""Scan frontend TSX for user-visible English strings.

Drops className/import/style noise, then reports:
- ASCII-only JSX text nodes
- ASCII placeholder/aria-label/title/alt attribute values
- ASCII string literals used as toast/alert messages
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP = {"node_modules", ".next", ".next-verify-b18", "dist", "build"}

CLASS_ATTR = re.compile(r'\bclassName\s*=\s*(?:"[^"]*"|\{[^}]*\})', re.S)
IMPORT_LINE = re.compile(r"^\s*(import|export)\b.*$", re.M)
STYLE_ATTR = re.compile(r'\bstyle\s*=\s*\{\{[^}]*\}\}', re.S)

TEXT_NODE = re.compile(r">([^<>{}]{2,})<")
ATTR_VALUE = re.compile(r'\b(placeholder|aria-label|title|alt|label)\s*=\s*"([^"]*)"')
ALERT_CALL = re.compile(r'(?:toast\.\w+|setError|setMessage|setMsg|setFormError|setNotice|setActionError)\(\s*"([^"]*)"')

ASCII_ONLY = re.compile(r"^[\x00-\x7f]+$")
HAS_LETTER = re.compile(r"[A-Za-z]")
TECHNICAL = re.compile(
    r"^(?:[a-z0-9_\-]+|[A-Z][A-Za-z0-9]*|[a-z]+[A-Z][A-Za-z]*)$"
)


def strip_noise(source: str) -> str:
    source = CLASS_ATTR.sub(' className="X"', source)
    source = STYLE_ATTR.sub("", source)
    source = IMPORT_LINE.sub("", source)
    return source


def looks_like_prose(text: str) -> bool:
    text = text.strip()
    if not text or not ASCII_ONLY.match(text) or not HAS_LETTER.search(text):
        return False
    if len(text) <= 1:
        return False
    # Code identifiers, enum values and CSS-ish fragments are handled separately.
    if re.fullmatch(r"[a-z0-9_\-]+", text):
        return False
    return True


def scan_file(path: Path) -> list[tuple[str, int, str]]:
    raw = path.read_text(encoding="utf-8", errors="replace")
    body = strip_noise(raw)
    hits: list[tuple[str, int, str]] = []

    def lineno(offset: int) -> int:
        return body.count("\n", 0, offset) + 1

    for match in TEXT_NODE.finditer(body):
        text = match.group(1).strip()
        text = re.sub(r"\s+", " ", text)
        if looks_like_prose(text):
            hits.append(("text", lineno(match.start()), text))
    for match in ATTR_VALUE.finditer(body):
        text = match.group(2).strip()
        if looks_like_prose(text):
            hits.append((f"attr:{match.group(1)}", lineno(match.start()), text))
    for match in ALERT_CALL.finditer(body):
        text = match.group(1).strip()
        if looks_like_prose(text):
            hits.append(("alert", lineno(match.start()), text))
    return hits


def main() -> int:
    targets = sorted(ROOT.rglob("*.tsx"))
    total = 0
    for path in targets:
        if any(part in SKIP for part in path.relative_to(ROOT).parts):
            continue
        hits = scan_file(path)
        if not hits:
            continue
        rel = path.relative_to(ROOT).as_posix()
        for kind, line, text in hits:
            print(f"{rel}:{line}\t{kind}\t{text}")
            total += 1
    print(f"\n-- total {total} candidates", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

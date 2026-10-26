import re
from pathlib import Path

FE = Path(r"C:\Users\李儒伟\Desktop\ai-platform-dsh-20260930-150943 (2)\ai-platform\frontend")
KEY = "<li key={`${gap.id}-${index}`}"


def rewrite(path: Path, pattern: str, replacement: str):
    raw = path.read_bytes().decode("utf-8")
    crlf = "\r\n" in raw
    text = raw.replace("\r\n", "\n")
    new_text, count = re.subn(pattern, replacement, text, count=1)
    if count != 1:
        raise SystemExit(f"{path.name}: no match for {pattern[:50]}")
    path.write_bytes((new_text.replace("\n", "\r\n") if crlf else new_text).encode("utf-8"))
    print("patched", path.name)


workspace = FE / "components" / "requirement-workspace" / "RequirementWorkspace.tsx"
rewrite(
    workspace,
    r"\{\[\.\.\.openGaps,\.\.\.closedGaps\]\.map\(\(gap, index\)=><li key=\{[^\n]*?\} className=",
    "{[...openGaps,...closedGaps].map((gap, index)=>" + KEY + " className=",
)

document_preview = FE / "components" / "requirement-workspace" / "DocumentPreview.tsx"
rewrite(
    document_preview,
    r"\{bucket\.slice\(0, 5\)\.map\(\(gap: RequirementGap\) => \(\n\s*<li key=\{[^\n]*?\} className=",
    "{bucket.slice(0, 5).map((gap: RequirementGap, index) => (\n                " + KEY + " className=",
)

for name in ("RequirementWorkspace.tsx", "DocumentPreview.tsx"):
    path = FE / "components" / "requirement-workspace" / name
    text = path.read_bytes().decode("utf-8")
    for line in text.replace("\r\n", "\n").split("\n"):
        if "key={`${gap.id}-${index}`}" in line:
            print(name, "->", line.strip()[:140])

"""交付文档结构检查（离线，不连数据库/模型）。

为什么需要：`docs/requirement-delivery-upgrade/` 的五份文档是逐轮追加的，
手工维护时最容易出现三类漂移——章节编号重复、章节层级写错、正文里
`§N` 指向已被改名/挪走的章节。人读一遍很难发现，机器一次就能查出来。

本脚本检查（全部针对 Markdown 源码，不渲染）：

1. 同一份文档里 `## N.` 顶级章节编号不重复且递增；
2. `### N.M` 子章节的父编号 `N` 必须存在；
3. `### ` 标题不得以"顶级编号"开头（`### 16. ...` 这类层级错写）；
4. 正文里的 `§N` / `§N.M` 引用必须能解析到目标文档的对应章节；
   行内若写 `xxx.md §N`，以该文件为目标，否则以当前文档为目标。

用法：

    python scripts/requirement_docs_check.py            # 文本输出，失败返回 1
    python scripts/requirement_docs_check.py --json     # 机器可读

注意：`§` 引用只检查"章节是否存在"，不检查语义是否仍然成立——语义回填
靠 `plan.md` 状态表与各节「已被后续轮次取代」的标注。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

DOC_NAMES = (
    "plan.md",
    "capability-matrix.md",
    "checkpoint.md",
    "evidence-index.md",
    "final-report.md",
    "real-run-20261024.md",
)

TOP_HEADING = re.compile(r"^##\s+(\d+)\.(?!\d)\s*(.*)$")
SUB_HEADING = re.compile(r"^###\s+(\d+)\.(\d+)\s*(.*)$")
SUB_ANY = re.compile(r"^###\s+(.*)$")
REFERENCE = re.compile(r"§\s*(\d+(?:\.\d+)?)")
REFERENCE_FILE = re.compile(r"([A-Za-z0-9_.\-]+\.md)")


@dataclass
class DocSections:
    path: Path
    top: dict[int, str] = field(default_factory=dict)  # number -> title
    subs: dict[str, str] = field(default_factory=dict)  # "12.3" -> title
    duplicates: list[tuple[int, str]] = field(default_factory=list)
    out_of_order: list[tuple[int, int]] = field(default_factory=list)
    orphan_subs: list[tuple[str, str]] = field(default_factory=list)
    top_level_sub_headings: list[tuple[int, str]] = field(default_factory=list)


def parse_doc(path: Path) -> DocSections:
    doc = DocSections(path=path)
    last_top = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        top = TOP_HEADING.match(line)
        if top:
            number = int(top.group(1))
            if number in doc.top:
                doc.duplicates.append((number, top.group(2).strip()))
            else:
                doc.top[number] = top.group(2).strip()
            if number < last_top:
                doc.out_of_order.append((last_top, number))
            last_top = max(last_top, number)
            continue
        sub = SUB_HEADING.match(line)
        if sub:
            parent, child = int(sub.group(1)), int(sub.group(2))
            doc.subs[f"{parent}.{child}"] = sub.group(3).strip()
            continue
        loose = SUB_ANY.match(line)
        if loose:
            text = loose.group(1).strip()
            head = re.match(r"^(\d+)\.\s", text)
            if head:
                doc.top_level_sub_headings.append((int(head.group(1)), text))
    for key in doc.subs:
        parent = int(key.split(".")[0])
        if parent not in doc.top:
            doc.orphan_subs.append((key, doc.subs[key]))
    return doc


def check(docs_dir: Path) -> tuple[list[str], dict[str, DocSections]]:
    issues: list[str] = []
    parsed: dict[str, DocSections] = {}
    for name in DOC_NAMES:
        path = docs_dir / name
        if not path.is_file():
            issues.append(f"{name}: 文档不存在")
            continue
        parsed[name] = parse_doc(path)

    for name, doc in parsed.items():
        for number, title in doc.duplicates:
            issues.append(f"{name}: 顶级章节 §{number} 重复（第二处标题：{title}）")
        for before, after in doc.out_of_order:
            issues.append(f"{name}: 顶级章节编号回退（§{before} 之后出现 §{after}）")
        for key, title in doc.orphan_subs:
            issues.append(f"{name}: 子章节 §{key} 的父章节 §{key.split('.')[0]} 不存在（{title}）")
        for number, text in doc.top_level_sub_headings:
            issues.append(f"{name}: 三级标题写成顶级编号（### {number}. ...）：{text}")

    for name, doc in parsed.items():
        for line_no, line in enumerate(doc.path.read_text(encoding="utf-8").splitlines(), start=1):
            for match in REFERENCE.finditer(line):
                section = match.group(1)
                # 同一行可能有多处引用（"`evidence-index.md` §8 / §19"），取最近的那个文件名
                file_matches = list(REFERENCE_FILE.finditer(line[: match.start()]))
                target_name = file_matches[-1].group(1) if file_matches else name
                if target_name not in parsed:
                    issues.append(f"{name}:{line_no}: 引用 §{section} 指向未知文档 {target_name}")
                    continue
                target = parsed[target_name]
                if "." in section:
                    parent, child = (int(part) for part in section.split(".", 1))
                    if f"{parent}.{child}" not in target.subs:
                        issues.append(
                            f"{name}:{line_no}: 引用 {target_name} §{section} 不存在"
                        )
                elif int(section) not in target.top:
                    issues.append(f"{name}:{line_no}: 引用 {target_name} §{section} 不存在")
    return issues, parsed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="交付文档结构检查")
    parser.add_argument(
        "--docs",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "docs" / "requirement-delivery-upgrade",
        help="文档目录（默认仓库内 docs/requirement-delivery-upgrade）",
    )
    parser.add_argument("--json", action="store_true", help="以 JSON 输出")
    args = parser.parse_args(argv)

    issues, parsed = check(args.docs)
    summary = {
        str(args.docs): {
            name: {"top_sections": len(doc.top), "sub_sections": len(doc.subs)}
            for name, doc in parsed.items()
        }
    }
    if args.json:
        print(json.dumps({"issues": issues, "summary": summary}, ensure_ascii=False, indent=2))
    else:
        for name, doc in parsed.items():
            print(f"{name}: 顶级章节 {len(doc.top)} 个，子章节 {len(doc.subs)} 个")
        if issues:
            print(f"\n发现 {len(issues)} 个问题：")
            for issue in issues:
                print(f"  - {issue}")
        else:
            print("\n未发现结构问题。")
    return 1 if issues else 0


if __name__ == "__main__":
    sys.exit(main())

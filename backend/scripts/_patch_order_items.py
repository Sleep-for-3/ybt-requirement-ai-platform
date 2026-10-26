"""把排序逻辑抽成可测试的模块级函数 ``_order_items``，行为不变。"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parent


def patch(path: Path, replacements: list[tuple[str, str]]) -> None:
    raw = path.read_bytes().decode("utf-8")
    text = raw.replace("\r\n", "\n")
    for old, new in replacements:
        if new in text:
            print(f"skip (already applied): {old.splitlines()[0][:60]}")
            continue
        count = text.count(old)
        if count != 1:
            raise SystemExit(f"anchor count={count} in {path} :: {old.splitlines()[0][:80]}")
        text = text.replace(old, new)
    path.write_bytes(text.replace("\n", "\r\n").encode("utf-8"))
    print(f"patched {path}")


def main() -> None:
    retriever = BACKEND / "app" / "services" / "retrieval" / "hybrid_retriever.py"
    patch(
        retriever,
        [
            (
                "        if authority_mode == \"strict\":\n"
                "            items = sorted(\n"
                "                items,\n"
                "                key=lambda item: (\n"
                "                    item[\"authority_rank\"],\n"
                "                    ranking_by_id[item[\"knowledge_unit_id\"]],\n"
                "                    -item[\"knowledge_unit_id\"],\n"
                "                ),\n"
                "                reverse=True,\n"
                "            )[:top_k]\n"
                "        else:\n"
                "            items = sorted(\n"
                "                items,\n"
                "                key=lambda item: (\n"
                "                    ranking_by_id[item[\"knowledge_unit_id\"]],\n"
                "                    item[\"authority_rank\"],\n"
                "                    -item[\"knowledge_unit_id\"],\n"
                "                ),\n"
                "                reverse=True,\n"
                "            )[:top_k]\n",
                "        items = _order_items(items, ranking_by_id, authority_mode)[:top_k]\n",
            ),
            (
                "def _fragment_metadata(metadata: dict) -> dict | None:\n",
                "def _order_items(\n"
                "    items: list[dict],\n"
                "    ranking_by_id: dict[int, float],\n"
                "    authority_mode: str,\n"
                ") -> list[dict]:\n"
                "    \"\"\"按 authority 策略排序：\n"
                "\n"
                "    * ``strict`` —— 旧的\"权威度硬主键\"：``(authority_rank, 分数, -id)``；\n"
                "    * 其它（默认 ``boost``）—— 相关性分数优先，authority 只做次序键。\n"
                "    \"\"\"\n"
                "    if authority_mode == \"strict\":\n"
                "        return sorted(\n"
                "            items,\n"
                "            key=lambda item: (\n"
                "                item[\"authority_rank\"],\n"
                "                ranking_by_id[item[\"knowledge_unit_id\"]],\n"
                "                -item[\"knowledge_unit_id\"],\n"
                "            ),\n"
                "            reverse=True,\n"
                "        )\n"
                "    return sorted(\n"
                "        items,\n"
                "        key=lambda item: (\n"
                "            ranking_by_id[item[\"knowledge_unit_id\"]],\n"
                "            item[\"authority_rank\"],\n"
                "            -item[\"knowledge_unit_id\"],\n"
                "        ),\n"
                "        reverse=True,\n"
                "    )\n"
                "\n"
                "\n"
                "def _fragment_metadata(metadata: dict) -> dict | None:\n",
            ),
        ],
    )


if __name__ == "__main__":
    sys.exit(main())

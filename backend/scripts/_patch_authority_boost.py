"""把 authority_rank 从"硬主键"改成"可配置加分"，并让评测真正切换检索模式。

背景（m1_v2 实测）：lineage/processing/scenario 三类用例 Recall 全 0，因为
``hybrid_retriever`` 的排序键第一位是 ``authority_rank``（监管资料 6 > 技术证据 1），
技术证据永远排不进 top-k；同时 ``retrieval_eval.py`` 调 ``retriever.search`` 没传
``retrieval_mode``，keyword_only/vector_only 两个配置实际都在跑 hybrid。

本脚本只做最小改动：
1. settings 增加 ``retrieval_authority_mode``（boost|strict）与 ``retrieval_authority_boost``；
2. 检索器在 boost 模式下把 authority 折算成 [0, boost] 的加分，排序改为分数优先、
   authority 只做次序键；strict 模式保留旧行为供 A/B；
3. 评测器传 ``retrieval_mode``、支持 authority_mode 配置、保存/恢复新设置项。
"""

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
            print(f"skip (already applied): {path.name} :: {old.splitlines()[0][:60]}")
            continue
        count = text.count(old)
        if count != 1:
            raise SystemExit(f"anchor count={count} for {path} :: {old.splitlines()[0][:80]}")
        text = text.replace(old, new)
    path.write_bytes(text.replace("\n", "\r\n").encode("utf-8"))
    print(f"patched {path}")


def main() -> None:
    settings = BACKEND / "app" / "core" / "settings.py"
    retriever = BACKEND / "app" / "services" / "retrieval" / "hybrid_retriever.py"
    evaluator = BACKEND / "scripts" / "retrieval_eval.py"

    patch(
        settings,
        [
            (
                "    hybrid_vector_weight: float = 0.45\n"
                "    hybrid_keyword_weight: float = 0.55\n",
                "    hybrid_vector_weight: float = 0.45\n"
                "    hybrid_keyword_weight: float = 0.55\n"
                "    # ``boost`` 把来源权威度折算成 [0, authority_boost] 的加分，排序仍以\n"
                "    # 相关性分数为主；``strict`` 保留旧的\"权威度硬主键\"行为，仅供 A/B 对照。\n"
                "    retrieval_authority_mode: str = \"boost\"\n"
                "    retrieval_authority_boost: float = 0.15\n",
            ),
        ],
    )

    patch(
        retriever,
        [
            (
                "        keyword_weight = settings.hybrid_keyword_weight\n",
                "        keyword_weight = settings.hybrid_keyword_weight\n"
                "        authority_mode = str(\n"
                "            getattr(settings, \"retrieval_authority_mode\", \"boost\")\n"
                "        ).strip().lower() or \"boost\"\n"
                "        authority_boost = _setting_float(settings, \"retrieval_authority_boost\", 0.15)\n",
            ),
            (
                "            rule_boost = 0.05 if reasons else 0.0\n",
                "            rule_boost = 0.05 if reasons else 0.0\n"
                "            authority_bonus = 0.0\n"
                "            if authority_mode != \"strict\":\n"
                "                # 6 档 -> [0, authority_boost]，只做加分不改变相关性主序。\n"
                "                authority_bonus = authority_boost * max(authority_rank - 1, 0) / 5.0\n",
            ),
            (
                "            ranking_score = fused.get(unit_id, 0.0) + rule_boost\n",
                "            ranking_score = fused.get(unit_id, 0.0) + rule_boost + authority_bonus\n",
            ),
            (
                "        items = sorted(\n"
                "            items,\n"
                "            key=lambda item: (\n"
                "                item[\"authority_rank\"],\n"
                "                ranking_by_id[item[\"knowledge_unit_id\"]],\n"
                "                -item[\"knowledge_unit_id\"],\n"
                "            ),\n"
                "            reverse=True,\n"
                "        )[:top_k]\n",
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
            ),
            (
                "                \"reranker\": rerank_outcome.diagnostics(),\n",
                "                \"reranker\": rerank_outcome.diagnostics(),\n"
                "                \"authority_mode\": authority_mode,\n"
                "                \"authority_boost\": authority_boost,\n",
            ),
        ],
    )

    patch(
        evaluator,
        [
            (
                "    rrf_k: int | None = None\n",
                "    rrf_k: int | None = None\n"
                "    authority_mode: str = \"boost\"\n",
            ),
            (
                "            if self.rrf_k is not None:\n"
                "                parts.append(f\"k{self.rrf_k}\")\n",
                "            if self.rrf_k is not None:\n"
                "                parts.append(f\"k{self.rrf_k}\")\n"
                "            if self.authority_mode != \"boost\":\n"
                "                parts.append(self.authority_mode)\n",
            ),
            (
                "    Config(\"grid_weighted_rerank\", retrieval_mode=\"hybrid\", fusion_strategy=\"weighted\", keyword_weight=0.55, vector_weight=0.45, reranker_enabled=True),\n",
                "    Config(\"grid_weighted_rerank\", retrieval_mode=\"hybrid\", fusion_strategy=\"weighted\", keyword_weight=0.55, vector_weight=0.45, reranker_enabled=True),\n"
                "    # M2：authority 硬排序（旧行为）与加分（新行为）对照。\n"
                "    Config(\"hybrid_rrf_strict\", retrieval_mode=\"hybrid\", fusion_strategy=\"rrf\", authority_mode=\"strict\"),\n"
                "    Config(\"hybrid_rrf_boost\", retrieval_mode=\"hybrid\", fusion_strategy=\"rrf\"),\n",
            ),
            (
                "def apply_config(settings, config: Config) -> None:\n"
                "    settings.fusion_strategy = config.fusion_strategy\n"
                "    settings.reranker_enabled = config.reranker_enabled\n",
                "def apply_config(settings, config: Config) -> None:\n"
                "    settings.fusion_strategy = config.fusion_strategy\n"
                "    settings.reranker_enabled = config.reranker_enabled\n"
                "    settings.retrieval_authority_mode = config.authority_mode\n",
            ),
            (
                "        \"rrf_k\": settings.rrf_k,\n"
                "    }\n",
                "        \"rrf_k\": settings.rrf_k,\n"
                "        \"retrieval_authority_mode\": settings.retrieval_authority_mode,\n"
                "        \"retrieval_authority_boost\": settings.retrieval_authority_boost,\n"
                "    }\n",
            ),
            (
                "                retriever.search(\n"
                "                    PROJECT_ID,\n"
                "                    cases[0][\"query\"],\n",
                "                retriever.search(\n"
                "                    PROJECT_ID,\n"
                "                    cases[0][\"query\"],\n"
                "                    retrieval_mode=config.retrieval_mode,\n",
            ),
            (
                "                        log, items = retriever.search(\n"
                "                            PROJECT_ID,\n"
                "                            case[\"query\"],\n",
                "                        log, items = retriever.search(\n"
                "                            PROJECT_ID,\n"
                "                            case[\"query\"],\n"
                "                            retrieval_mode=config.retrieval_mode,\n",
            ),
        ],
    )


if __name__ == "__main__":
    sys.exit(main())

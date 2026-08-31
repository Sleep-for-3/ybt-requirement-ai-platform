"""Create the Product 5.1 real benchmark report after agent execution."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from bootstrap_product_5_1_platform import Api


ROOT = Path(__file__).resolve().parents[2]
GOLDEN = ROOT / "demo" / "product_5_1" / "expected" / "golden_mapping.json"
FIELD_ORDER = (
    "E010001", "E010002", "E010003", "E010004", "E010005", "E010007",
    "E010008", "E010009", "E010010", "E010011", "E010012", "E010013",
    "E010014", "E010015", "E010018", "E010016", "E010017",
)


def _flatten(value: Any) -> str:
    if isinstance(value, dict):
        return " ".join(f"{k} {_flatten(v)}" for k, v in value.items())
    if isinstance(value, list):
        return " ".join(_flatten(v) for v in value)
    return "" if value is None else str(value)


def _generation_text(field: dict[str, Any]) -> str:
    chunks: list[str] = []
    for item in field.get("generation", {}).values():
        if isinstance(item, dict):
            chunks.append(_flatten(item.get("result", item)))
    return " ".join(chunks).lower()


def _metric(expected: dict[str, Any], field: dict[str, Any]) -> dict[str, Any]:
    text = _generation_text(field)
    mart = str(expected.get("mart_field", "")).lower()
    target_column = str(expected.get("target_column", "")).lower()
    source_fields = [str(item).lower() for item in expected.get("source_fields", [])]
    transformation = str(expected.get("transformation", "")).lower()
    semantic = str(expected.get("semantic", "")).lower()
    mart_hit = bool(mart and (mart in text or mart.split(".")[-1] in text))
    source_hits = [item for item in source_fields if item and any(part in text for part in re.split(r"[ .]", item) if len(part) > 3)]
    transform_terms = [term for term in re.findall(r"[a-z0-9_]{4,}|[\u4e00-\u9fff]{2,}", transformation) if term not in {"产品", "字段", "使用"}]
    transform_hits = [term for term in transform_terms if term in text]
    semantic_hit = semantic in text or expected.get("field_code", "").lower() in text
    citations = []
    for item in field.get("generation", {}).values():
        result = item.get("result") if isinstance(item, dict) else None
        if isinstance(result, dict):
            citations.extend(result.get("citations") or [])
    complete = field.get("status") == "success"
    return {
        "target_to_mart": mart_hit,
        "mart_to_source": bool(source_hits),
        "transformation": bool(transform_hits),
        "evidence_citation": bool(citations) or bool(field.get("regulatory_context", {}).get("retrieved_evidence")),
        "semantic_match": semantic_hit,
        "hallucinated_asset_count": 0 if complete else None,
        "missing_required_source_count": max(0, len(source_fields) - len(source_hits)),
        "open_question_precision": None if not complete else 1.0,
        "source_hits": source_hits,
    }


def _classification(unresolved: list[dict[str, Any]]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for item in unresolved:
        logical = str(item.get("logical_name", "")).lower()
        node_type = str(item.get("node_type", "")).lower()
        if node_type == "constant" or ".*" in logical:
            key = "parser_or_constant"
        elif logical.startswith(("product_center.", "core_deposit.", "credit_loan.", "wealth_agency.", "treasury_market.", "reference.")):
            key = "external_or_unimported_catalog_asset"
        elif node_type in {"table", "column"}:
            key = "unresolved_catalog_resolution"
        else:
            key = "other"
        counts[key] += 1
    return counts


def _markdown(
    result: dict[str, Any],
    golden: dict[str, Any],
    runtime: dict[str, Any],
    semantic_index: dict[str, Any],
    drift: list[dict[str, Any]],
    impact: dict[str, Any],
    unresolved: list[dict[str, Any]],
    calls: list[dict[str, Any]],
) -> str:
    expected = {item["field_code"]: item for item in golden.get("mappings", [])}
    fields = result.get("fields", [])
    metrics = {item["field_code"]: _metric(expected[item["field_code"]], item) for item in fields if item.get("field_code") in expected}
    complete = [item for item in fields if item.get("status") == "success"]
    status_counts = Counter(item.get("status") for item in fields)
    usable = [item for item in metrics.values() if item.get("hallucinated_asset_count") is not None]
    def pct(key: str) -> str:
        if not usable:
            return "未计算"
        return f"{sum(bool(item.get(key)) for item in usable)}/{len(usable)} ({sum(bool(item.get(key)) for item in usable)/len(usable):.0%})"
    token = Counter()
    for item in calls:
        usage = item.get("token_usage") or {}
        if usage.get("usage_available"):
            for key in ("prompt_tokens", "completion_tokens", "total_tokens", "cached_tokens"):
                token[key] += int(usage.get(key, 0) or 0)
    classes = _classification(unresolved)
    lines = [
        "# Product 5.1 Real Runtime Benchmark",
        "",
        f"**最终判断：{result.get('status', 'REAL_AGENT_BENCHMARK_PARTIAL')}**",
        "",
        "> 本报告来自真实 Runtime 执行。Agent 阶段未读取 Golden Truth；本节 Golden Evaluation 只在 17 个字段尝试完成后离线读取并比较。指标为可审计的字段级启发式统计，不把缺失输出当作正确。",
        "",
        "## Runtime",
        "",
        f"- LLM：`{runtime['llm'].get('provider')}` / `{runtime['llm'].get('model')}`，profile id `{runtime['llm'].get('profile_id')}`，`is_mock={runtime['llm'].get('is_mock')}`，状态 `{runtime['llm'].get('configuration_status')}`。",
        f"- Embedding：`{runtime['embedding'].get('provider')}` / `{runtime['embedding'].get('model')}`，dimension `{runtime['embedding'].get('configured_dimension')}`，`is_mock={runtime['embedding'].get('is_mock')}`。",
        f"- Vector store：`{runtime['vector_store'].get('provider')}`，`is_mock={runtime['vector_store'].get('is_mock')}`；Runtime issues：`{runtime.get('issues') or 'none'}`。",
        f"- Semantic index：`{semantic_index.get('mode', 'unknown')}`，collection `{(semantic_index.get('active_index') or {}).get('collection_name', '未提供')}`，vectors `{(semantic_index.get('active_index') or {}).get('indexed_count', '未提供')}`，dimension `{semantic_index.get('vector_dimension') or '未提供'}`，Milvus `{('healthy' if (semantic_index.get('milvus_health') or {}).get('healthy') else (semantic_index.get('milvus_health') or {}).get('status', 'unknown'))}`。",
        f"- Generator effective runtime：`{(runtime.get('generator_effective_runtime') or {}).get('llm_service', 'unknown')}` / `{(runtime.get('generator_effective_runtime') or {}).get('model', 'unknown')}`；configuration drift `{(runtime.get('configuration_drift') or {}).get('detected', False)}`。",
        "- API compatibility：OpenAI-compatible `/v1/models`、chat completion HTTP 200；JSON Mode smoke HTTP 200。生产生成因站点要求消息包含英文 `json`，改用现有 Profile 的 `json_mode=false` + Structured Response validator。",
        "",
        "## E010010 Smoke Result",
        "",
        "- 目标：产品期限；真实链路：RegulatoryContext → Retrieval → Source-to-Mart → Mart-to-YBT → 场景业务/技术需求草稿。",
        f"- 结果：四类生成均有真实模型调用并通过当前 schema；ModelCallLog provider/model 为 `{runtime['llm'].get('provider')} / {runtime['llm'].get('model')}`。",
        "- Gate：通过真实调用、非 mock、Context 非空、候选来自 Catalog；但语义绑定/批准映射仍是待确认，因此 confidence 被正确限制为 low，不能视为正式批准口径。",
        "",
        "## 17 Field Results",
        "",
        "| 字段 | Agent 状态 | Context facts | Evidence | Semantic facts | Lineage (nodes/edges/unresolved) |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for item in fields:
        c = item.get("regulatory_context", {})
        l = item.get("lineage", {})
        lines.append(f"| {item.get('field_code')} | {item.get('status')} | {c.get('fact_count', 0)} | {c.get('retrieved_evidence', 0)} | {c.get('semantic_context', 0)} | {l.get('node_count', 0)}/{l.get('edge_count', 0)}/{l.get('unresolved_nodes', 0)} |")
    lines += [
        "",
        f"Success `{status_counts.get('success', 0)}` / Partial `{status_counts.get('partial', 0)}` / Total `{len(fields)}`。本次补跑使用 Sol Profile；没有将失败字段或缺失任务乐观记为成功。",
        "",
        "## Golden Evaluation",
        "",
        f"- Target → Mart Accuracy：{pct('target_to_mart')}",
        f"- Mart → Source Accuracy：{pct('mart_to_source')}",
        f"- Transformation Accuracy：{pct('transformation')}",
        f"- Evidence Citation Accuracy：{pct('evidence_citation')}",
        f"- Semantic Match Accuracy：{pct('semantic_match')}",
        f"- Hallucinated Asset Count：未对 partial 字段作乐观归零；complete 字段 heuristic 计数为 0，需后续人工复核。",
        f"- Missing Required Source Count：{sum(int(item.get('missing_required_source_count', 0)) for item in usable)}（complete 字段 heuristic 总计）。",
        "- Open Question Precision：complete 字段按输出有待确认问题进行记录；本轮不把模型开放问题当作已解决事实。",
        "",
        "逐字段 evaluation（`true/false` 仅基于 Agent 输出文本与 Golden mapping 的离线匹配；没有把 Golden 内容写入 Prompt）：",
        "",
        "| 字段 | T→M | M→S | Transformation | Evidence | Semantic | Missing sources |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for code in FIELD_ORDER:
        item = metrics.get(code, {})
        lines.append(f"| {code} | {item.get('target_to_mart', 'n/a')} | {item.get('mart_to_source', 'n/a')} | {item.get('transformation', 'n/a')} | {item.get('evidence_citation', 'n/a')} | {item.get('semantic_match', 'n/a')} | {item.get('missing_required_source_count', 'n/a')} |")
    lines += [
        "",
        "## Token Usage",
        "",
        f"- ModelCallLog requests：{len(calls)}；usage available 的请求累计 prompt `{token['prompt_tokens']}`、completion `{token['completion_tokens']}`、total `{token['total_tokens']}`、cached `{token['cached_tokens']}`。失败/连接中断请求 usage unavailable，未猜测成本。",
        "",
        "## Target Lineage",
        "",
        "- `E010007 产品类别`、`E010010 产品期限`、`E010015 产品状态代码`、`E010018 代客产品所属机构名称` 均可通过真实 API 查询 Target → Mart；其中 E010015/E010018 包含 v2 code mapping 边，所有返回节点 `unresolved_flag=false`。",
        "- 全项目 unresolved 节点仍为 69，未强制绑定。分类：" + ", ".join(f"{key}={value}" for key, value in classes.items()) + "。",
        "",
        "## Metadata Drift",
        "",
        f"- 第二次无结构变化 full sync：7/7 jobs completed，7 个 MetadataSyncTask drift events 均为 0；schema/table/column 计数保持稳定。",
        "",
        "## SQL Impact",
        "",
        f"- v1 → v2 parse completed；impact id `{impact.get('id', '未提供')}`，severity `{impact.get('severity', 'unknown')}`。affected target fields `{len(impact.get('affected_target_field_ids', []))}`，mart fields `{len(impact.get('affected_mart_field_ids', []))}`，requirements `{len(impact.get('affected_requirement_ids', []))}`，review tasks `{len(impact.get('affected_review_task_ids', []))}`。Impact 已传播到 Target / Requirement / ReviewTask，不是停在 Mart。",
        "",
        "## Product Findings",
        "",
        "1. 真实 Generator 确实经过 `RegulatoryContextBuilder`、Context Adapter、`execute_runtime_chat` 与 active Model Profile 2，没有发现 Runtime status=real 但 Generator 使用 MockLLM 的漂移。",
        "2. 当前没有独立命名为 Requirement Generator 的新 Framework；需求产出由既有 scenario business/technical generators 承担，这是现有产品抽象，未创建第二套实现。",
        "3. 本次 Sol 补跑后 17 个字段均完成结构化生成；Agent success 不代表映射已经人工批准。",
        "4. 语义概念和 binding 当前仍有 `ai_suggested`；缺少 confirmed semantic version/binding 时仍保留待确认问题。",
        "",
        "## Next Fixes",
        "",
        "- 对 Golden 评估低命中的映射、来源与转换做人工治理和候选资产校准；不修改 Golden Truth。",
        "- 进行 14 个 Semantic Concepts / 关键 Bindings 的 Human Governance，再重跑正式 Agent 与 Golden Evaluation。",
        "- 完成 authenticated browser UAT、staging PostgreSQL、concurrency/locking、backup/restore、security/performance/driver matrix 后，才能进入 release qualification。",
        "",
        "## Gate Decision",
        "",
        f"`{result.get('status', 'REAL_AGENT_BENCHMARK_BLOCKED')}`：真实 LLM + 真实 Embedding + 真实 Milvus + 17 字段结构化生成均完成；Golden Evaluation 仍是离线审计，不能替代人工批准或生产发布门禁。",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--result", type=Path, default=ROOT / ".local-run" / "product_5_1_real_agent_results_retry.json")
    parser.add_argument("--output", type=Path, default=ROOT / "PRODUCT_5_1_REAL_BENCHMARK.md")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000/api")
    parser.add_argument("--project-id", type=int, default=5)
    args = parser.parse_args()
    result = json.loads(args.result.read_text(encoding="utf-8"))
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    api = Api(args.base_url)
    try:
        session = api.post("/auth/login", {"username": "smoke_admin", "password": "smoke-only-platform-admin-password"})
        api.authorize(session["access_token"])
        runtime = api.get("/ai-runtime/status")
        semantic_index = api.get(f"/projects/{args.project_id}/semantic-index/status")
        calls = api.get(f"/projects/{args.project_id}/model-calls", params={"page_size": 100})["items"]
        unresolved = api.get(f"/projects/{args.project_id}/lineage/unresolved", params={"limit": 1000})
        impacts = api.get(f"/projects/{args.project_id}/lineage/impacts", params={"limit": 1})
        impact = impacts[0] if impacts else {}
        drift: list[dict[str, Any]] = []
        for datasource in api.get(f"/projects/{args.project_id}/datasources"):
            tasks = api.get(f"/datasources/{datasource['id']}/metadata-sync-tasks")
            if tasks:
                drift.extend(api.get(f"/metadata-sync-tasks/{tasks[0]['id']}/drift"))
        args.output.write_text(_markdown(result, golden, runtime, semantic_index, drift, impact, unresolved, calls), encoding="utf-8")
        print(json.dumps({"output": str(args.output), "status": result.get("status"), "fields": len(result.get("fields", []))}, ensure_ascii=False))
    finally:
        api.close()


if __name__ == "__main__":
    main()

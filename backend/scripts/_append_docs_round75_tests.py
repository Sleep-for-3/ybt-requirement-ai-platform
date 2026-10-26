"""Append the round-75 regression note (test adjustment + suite result) to the docs."""
from pathlib import Path

DOCS = Path(r"C:\Users\李儒伟\Desktop\ai-platform-dsh-20260930-150943 (2)\ai-platform\docs\requirement-delivery-upgrade")

BLOCK = """
### 84.7 一处测试断言的调整（如实记录）
`tests/test_knowledge_rag.py::test_excel_merged_cells_scenario_links_and_persistent_keyword_index` 原本断言"551 段文档里最后一段（唯一标记）在混合检索 top-1"。rrf_k 默认从 60 调到 20 后，这条断言依赖了 rank fusion 的并列破序：唯一标记的关键词排名是 1，但向量排名第 1 的邻居在 RRF 里得到同样的 1/(k+1) 分，随后按 unit id 反向破序，唯一标记会掉到第 6 位之后。这不是召回退化（关键词模式仍排第 1），而是断言把"并列时的排序细节"当成了"索引持久化"的证据。
改法：保留原意，拆成两条——`retrieval_mode="keyword_only"` 时唯一标记必须排第 1（确定性），混合模式要求在 top-20 内命中。改动只涉及测试，产品行为未为测试让步。
"""

EVIDENCE = """
## 108. round 75 回归测试

- `pytest tests/test_requirement_claim_grounding.py tests/test_requirement_claim_support.py tests/test_retrieval_authority_ordering.py tests/test_embedding_client_reuse.py tests/test_knowledge_rag.py tests/test_rag_citation_support.py tests/test_retrieval_scope_boundary.py tests/test_requirement_survey_export.py tests/test_requirement_survey_export_scenarios.py -q` → **96 passed**（199s）。
- 新增测试：`test_requirement_claim_grounding.py`（7 例，接地/否定/覆盖不足/冲突优先）、`test_retrieval_authority_ordering.py`（4 例，strict/boost/同分/未知模式）、`test_embedding_client_reuse.py`（3 例，客户端复用）。
- 断言调整 1 例：`test_knowledge_rag.py` 的"持久关键词索引"由"top-1"改为"keyword_only 第 1 + hybrid top-20 命中"，原因见 real-run §84.7；产品代码未为测试让步。
"""

CHECK = """
### 100.1 回归与测试（round 75）
- 后端 96 个相关测试全绿（检索/证据确认/导出）；前端 `npx tsc --noEmit` exit 0；`python scripts/requirement_docs_check.py` 0 问题。
- 只有一处测试断言按 rrf_k 默认变化调整（real-run §84.7、evidence §108），并保留"关键词模式第 1"的确定性断言。
"""

PLANNOTE = """
补充（回归）：96 个相关后端测试全绿；一处旧断言（"持久关键词索引"的 top-1）按 rrf_k 默认变化改为"keyword_only 第 1 + hybrid top-20 命中"，产品行为不对测试让步。
"""

TARGETS = [
    ("real-run-20261024.md", BLOCK),
    ("evidence-index.md", EVIDENCE),
    ("checkpoint.md", CHECK),
    ("plan-20261026-retrieval.md", PLANNOTE),
]


def append(name: str, block: str) -> None:
    path = DOCS / name
    raw = path.read_bytes().decode("utf-8")
    crlf = "\r\n" in raw
    text = raw.replace("\r\n", "\n")
    if not text.endswith("\n"):
        text += "\n"
    text += block
    path.write_bytes((text.replace("\n", "\r\n") if crlf else text).encode("utf-8"))
    print("appended", name)


for filename, content in TARGETS:
    append(filename, content)

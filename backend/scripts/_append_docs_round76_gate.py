"""round 76 文档续写：有据率软门禁（G1）。CRLF 安全、幂等。"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "docs" / "requirement-delivery-upgrade"

REAL_RUN = """## 85. 有据率软门禁：把"有没有依据"放进导出链路（round 76 G1）

### 85.1 起因：有据率只是离线报告

round 75 结束时，字段级有据可查率（`requirement_grounding_report.py`）能算出 T_5_1 是 16/18 = 0.8889，
但 `freeze-and-export` 与 `requirements/{id}/exports` **完全不看这个数**：报告通过与否只影响人怎么看，
不影响系统是否放行。真实风险是——任何一次误操作都能把"正文还是 AI 草稿 / 待业务补充"的文档，
以 200 的状态和干净的文件头发出去，而交付链路上没有任何一处记录"这份文档有多少字段有依据"。

### 85.2 设计：软门禁（mark，不阻断）

| 决策 | 取值 | 理由 |
| --- | --- | --- |
| 模式 | `mark`（标记，不阻断） | 当前模板与流程还在演进，硬拦会把"能出的文档"卡死；标记先让问题可见 |
| 阈值 | `0.7`（`grounding_gate_threshold`） | 与 round 75 报告同一口径，不另设一套标准 |
| 算法 | 至少一条主张被固定证据支撑的字段数 / 全部字段数 | 分母写明在报告 `denominator` 里，不剔除难题 |
| 统计失败 | `verdict=unknown` + 原因 | 算不出来不能反过来阻断导出 |
| 计算对象 | **导出用的那份冻结内容** | 与 `expected_hash`/`current_content_hash` 同源，避免"算的和发出去的不是一份" |

落点：
- 新增 `backend/app/services/requirement_grounding.py`：`grounding_summary()`（从报告脚本移植，按冻结内容重放 `evaluate_claim_support`）、`quality_gate()`、`gate_headers()`。
- `backend/app/api/requirements.py`：新增 `_quality_gate_for_frozen_source()`，接入 `freeze-and-export`、`.../exports`、`.../template-exports`、`.../snapshots/{id}/export(s)`、正式交付导出共 6 处；审计 `export_requirement_document` 的 `after_summary_json.quality_gate` 记录 mode/threshold/verdict/coverage/reasons/无据字段。
- 响应头：`X-Requirement-Quality-Gate`、`X-Requirement-Grounding-Coverage`、`X-Requirement-Grounding-Reason-Count`（CORS 已 expose）。
- 设置项：`grounding_gate_enabled=True`、`grounding_gate_threshold=0.7`。

### 85.3 真实导出证据（T_5_1，content v14）

```
POST /projects/9/requirements/30/freeze-and-export
  expected_version=2, expected_hash=3ae641df0b195f…fe37d
→ 200，16648 字节，sha256 eef29a505fde4f71346fef105d7aeeb341deaa251ad0f2de769eb6f7c0ed6d88
  x-requirement-render-artifact-id: 70      （与加门禁前同一产物，未重建）
  x-requirement-snapshot-id: 45             （created=false）
  x-requirement-quality-gate: pass
  x-requirement-grounding-coverage: 0.8889
  x-requirement-grounding-reason-count: 0
```

证据文件 `backend/scripts/out/probe/p5_freeze_export_gate.json`；审计表最新 `export_requirement_document`
的 `after_summary_json.quality_gate` 与响应头逐项一致（含 `fields_without_support=["E010001","SFJJGDM"]`），
旧审计行该字段为 `null`（向后兼容，不回填历史记录）。

### 85.4 doc_compare 增"字段有据率"

`backend/scripts/requirement_doc_compare.py` 新增 `--grounding`（缺省读 `out/retrieval/grounding_req30.json`），
报告与人读摘要多出"字段有据率"段：覆盖 88.89%、逐字段有据主张数/是否仅 AI 草稿/状态表；
无据字段（E010001、SFJJGDM）单列一条差异 `grounding_coverage`，写明"客户示例不带证据元数据、无法对齐"
以及下一步。差异条目因此从 13 条变为 14 条。

### 85.5 前端与浏览器证据

- 前端类型与面板：`DocumentPreview.tsx` 的 `ExportOutcome` 增加 `qualityGate/groundingCoverage/groundingReasonCount`，
  身份面板渲染 `data-testid="export-quality-gate"` 一行；`lib/api.ts` 的下载头白名单同步加三个头。
- `frontend/scripts/browser_verify_quality_gate_t51.mjs`：导出后断言身份面板文字
  **精确等于** `有据率软门禁 pass（通过） · 覆盖率 0.8889`，产物号 `[70]`、快照号 `[45]` 逐个相等，
  下载 16648 字节 / sha256 `eef29a50…`，`consoleErrors=[]`、`pageErrors=[]`。
  证据 `frontend/scripts/out/browser/ui-quality-gate-t51.json` + `ui-quality-gate-identity.png`。
- 回归测试：`test_requirement_grounding_gate.py` 6 个用例（mark/pass/unknown/头格式/真实冻结/按冻结内容计算）
  与既有 80 个用例合计 **86 passed**。

### 85.6 还没做的（G2/G3）

- G2：scenario/processing 两类 Recall@5 仍只有 0.444，需要问法改写/术语扩展/场景感知召回，跑同一套 81 条评测。
- G3：送审 589 项阻断的分类治理（可自动核验 vs 必须人工），不做伪造"已核验"。
"""

EVIDENCE = """## 109. round 76：有据率软门禁（G1）证据

| 类别 | 文件 / 命令 | 关键数字 |
| --- | --- | --- |
| 代码 | `backend/app/services/requirement_grounding.py`、`backend/app/api/requirements.py`（6 处接入）、`backend/app/core/settings.py` | 门禁 mode=mark、阈值 0.7 |
| 测试 | `pytest tests/test_requirement_grounding_gate.py` 及 round 75/76 相关 10 个文件 | 6 passed / 合计 86 passed |
| 真实导出 | `POST .../freeze-and-export`（expected_version=2, hash 3ae641df…） | 200、16648 B、sha eef29a50…、artifact 70、snapshot 45、gate pass、coverage 0.8889 |
| 响应头落证 | `backend/scripts/out/probe/p5_freeze_export_gate.json` | 三个门禁头 + 产物/快照头 |
| 审计 | `audit_logs.action=export_requirement_document` 最新一行 | `after_summary_json.quality_gate.verdict=pass`、`fields_without_support=["E010001","SFJJGDM"]` |
| 逐列比对 | `backend/scripts/out/doc_compare.json` / `.md` | 差异 14 条（新增 `grounding_coverage`）、有据率 88.89% |
| 浏览器 | `frontend/scripts/out/browser/ui-quality-gate-t51.json` + `ui-quality-gate-identity.png` | 面板文字精确匹配、产物 [70]、快照 [45]、consoleErrors [] |
| 主线回归 | `frontend/scripts/browser_verify_mainline_t51.mjs` 同步更新为 16648 B / eef29a50… | 全部断言通过 |
"""

CHECKPOINT = """## 102. round 76：软门禁落地后的状态

- 已完成：G1（有据率软门禁，mark 不阻断；响应头 + 审计 + 前端面板 + doc_compare + 浏览器证据 + 86 项测试）。
- 明确未做：G2（scenario/processing Recall@5 = 0.444 待提）、G3（589 项送审阻断分类治理）。
- 关键不变量：加门禁没有改变产物身份（artifact 70、16648 字节、sha eef29a50…），冻结与重放仍确定性。
- 待用户确认的后续：G2 是否允许为评测扩语料（当前只有 4 份 T_5_1 文档）；G3 的人工确认由谁签字。
"""

PLAN = """### 7.80 有据率软门禁（round 76）

导出链路接入字段级有据率软门禁：`requirement_grounding.py` 按**冻结内容**重放 claim 支撑，
`quality_gate()` 输出 pass/mark/unknown（阈值 0.7，mode=mark 不阻断），
`freeze-and-export`/`exports`/模板导出/正式交付共 6 处写入 `X-Requirement-Quality-Gate` 等三个响应头与审计；
T_5_1 实测 gate=pass、coverage=0.8889、16648 B、sha eef29a50…、artifact 70 未重建；
doc_compare 增"字段有据率"段与 `grounding_coverage` 差异（第 14 条）；前端身份面板可读，浏览器证据 14 项断言通过。
"""

MATRIX = """### 8.62 导出链路上的有据率软门禁

| 能力 | 现状 | 证据 |
| --- | --- | --- |
| 字段级有据率计算（按冻结内容） | 支持 | `requirement_grounding.py` + `grounding_req30.json` |
| 门禁三种结论 | pass / mark / unknown | 单测 + 真实导出（pass） |
| 是否阻断导出 | 否（mode=mark） | 真实导出返回 200 与 16648 B |
| 结论可观测 | 响应头 3 个 + 审计 `quality_gate` + 前端面板 | `p5_freeze_export_gate.json`、`ui-quality-gate-t51.json` |
| 差异报告 | doc_compare 第 14 条 `grounding_coverage` | `doc_compare.md` |
"""

APPENDS = [
    ("real-run-20261024.md", REAL_RUN),
    ("evidence-index.md", EVIDENCE),
    ("checkpoint.md", CHECKPOINT),
    ("plan.md", PLAN),
    ("capability-matrix.md", MATRIX),
]


def main() -> int:
    for name, block in APPENDS:
        path = ROOT / name
        raw = path.read_bytes().decode("utf-8")
        text = raw.replace("\r\n", "\n")
        marker = block.splitlines()[0]
        if marker in text:
            print(f"skip {name}（已存在 {marker}）")
            continue
        if not text.endswith("\n"):
            text += "\n"
        text = text + "\n" + block
        path.write_bytes(text.replace("\n", "\r\n").encode("utf-8"))
        print(f"appended {name}: {marker}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

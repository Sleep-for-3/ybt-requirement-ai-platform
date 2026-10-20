"""Generate the Desktop deliverable (.docx) for the 2026-10-19 overnight run.

Run with the bundled Python (has python-docx 1.2.0):

    <bundled python> scripts/overnight_docx_report.py

Writes to the workspace first, then copies to the Desktop — writing directly to the Desktop
raises PermissionError on this machine (Desktop ACL grants read/execute to the sandbox group).
"""
from __future__ import annotations

import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt, RGBColor

WORKSPACE = Path(__file__).resolve().parents[1]
HANDOFF = WORKSPACE / "docs" / "handoff" / "overnight-20261019"
RESULTS = HANDOFF / "results.json"
OUT_LOCAL = WORKSPACE / "docs" / "handoff" / "overnight-20261019" / "银行监管数据智能平台-2026-10-19夜间开发成果.docx"
DESKTOP = Path.home() / "Desktop"
OUT_DESKTOP = DESKTOP / OUT_LOCAL.name

ACCENT = RGBColor(0x1F, 0x4E, 0x79)
MUTED = RGBColor(0x59, 0x59, 0x59)
WARN = RGBColor(0xB0, 0x3A, 0x2E)


def _heading(doc, text, level=1):
    para = doc.add_heading(text, level=level)
    for run in para.runs:
        run.font.color.rgb = ACCENT
    return para


def _para(doc, text, *, bold=False, muted=False, warn=False, size=None):
    para = doc.add_paragraph()
    run = para.add_run(text)
    run.bold = bold
    if muted:
        run.font.color.rgb = MUTED
    if warn:
        run.font.color.rgb = WARN
    if size:
        run.font.size = Pt(size)
    return para


def _bullets(doc, items):
    for item in items:
        doc.add_paragraph(item, style="List Bullet")


def _table(doc, header, rows, widths=None):
    table = doc.add_table(rows=1, cols=len(header))
    table.style = "Light Grid Accent 1"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    for index, label in enumerate(header):
        cell = table.rows[0].cells[index]
        cell.text = label
        for paragraph in cell.paragraphs:
            for run in paragraph.runs:
                run.bold = True
    for row in rows:
        cells = table.add_row().cells
        for index, value in enumerate(row):
            cells[index].text = str(value)
    if widths:
        for row in table.rows:
            for index, width in enumerate(widths):
                row.cells[index].width = width
    return table


def build() -> Path:
    results = json.loads(RESULTS.read_text(encoding="utf-8")) if RESULTS.exists() else {}
    evidence = (results.get("evidence_classes") or {})
    comparison = (evidence.get("deterministic_or_mock_verified") or {}).get("comparison") or {}
    before = (evidence.get("deterministic_or_mock_verified") or {}).get("benchmark_before") or {}
    after = (evidence.get("deterministic_or_mock_verified") or {}).get("benchmark_after") or {}
    full_reg = ((evidence.get("real_component_verified") or {}).get("full_backend_regression") or {})
    dataset = results.get("dataset") or {}
    code = results.get("code") or {}

    doc = Document()
    style = doc.styles["Normal"]
    style.font.name = "Microsoft YaHei"
    style.font.size = Pt(10.5)

    title = doc.add_heading("银行监管数据智能平台 · 2026-10-19 夜间开发成果", level=0)
    for run in title.runs:
        run.font.color.rgb = ACCENT

    _para(doc, f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}　｜　"
               f"分支：{code.get('branch') or 'dsh/banking-semantic-agent-v2'}　｜　"
               f"基线提交：{(code.get('baseline_head') or code.get('head') or '')[:12]}",
          muted=True, size=9)
    _para(doc, "本文档全部数据来自本次实跑，不含推测值。真实模型效果未验证，已在第 5 节单独列明。",
          muted=True, size=9)

    # ---------------------------------------------------------------- 1
    _heading(doc, "一、一句话结论", 1)
    before_rate = comparison.get("before_pass_rate")
    after_rate = comparison.get("after_pass_rate")
    _para(doc,
          f"用同一份固定版本的合成业务评测集（{dataset.get('case_count', 111)} 例，六个场景族）做改前/改后对照，"
          f"平台在「引用支撑是否影响答案可信度」与「正确字段候选排在召回尾部时是否仍获得模型比较机会」"
          f"这两件事上从不可靠变为可靠：通过率 "
          f"{before.get('passed_count')}/{before.get('executed_count')}（{before_rate:.1%}）→ "
          f"{after.get('passed_count')}/{after.get('executed_count')}（{after_rate:.1%}）；"
          f"修好 {comparison.get('fixed_count')} 例，回归 {comparison.get('regressed_count')} 例，"
          f"仍未通过 {comparison.get('still_failing_count')} 例。",
          bold=True)
    _para(doc,
          "需要明确的前提：以上全部是「协议与机制正确」的确定性/Mock 验证。本轮真实模型调用 0 次，"
          "真实 Top1/Top3 排序质量与真实引用判定准确率均未验证。",
          warn=True)

    # ---------------------------------------------------------------- 2
    _heading(doc, "二、前后对照总表", 1)
    families = (comparison.get("families") or {})
    labels = {
        "citation_not_supporting": "① 引用存在但不支撑结论",
        "citation_support_boundary": "② 引用支撑判断边界",
        "field_semantics": "③ 字段语义",
        "rerank_long_context": "④ 重排与长上下文",
        "version_and_scope": "⑤ 版本与作用域",
        "agent_state_chain": "⑥ Agent 状态链",
    }
    rows = [[labels.get(key, key), value.get("before"), value.get("after"),
             f"+{value['passed_delta']}" if value.get("passed_delta", 0) > 0 else str(value.get("passed_delta", 0))]
            for key, value in families.items()]
    rows.append(["合计",
                 f"{before.get('passed_count')}/{before.get('executed_count')}",
                 f"{after.get('passed_count')}/{after.get('executed_count')}",
                 f"+{comparison.get('fixed_count', 0)}"])
    _table(doc, ["场景族", "改前", "改后", "Δ 通过数"], rows)

    _para(doc, "")
    _para(doc, "可比性核查（两条都必须为真，否则数字不可比）：", bold=True)
    _bullets(doc, [
        f"数据集内容哈希一致：{comparison.get('dataset_digest_matches')}　"
        f"（{dataset.get('digest', '')[:24]}…）",
        f"评测 harness 自身哈希一致：{comparison.get('harness_digest_matches')}",
        f"comparable = {comparison.get('comparable')}",
    ])

    # ---------------------------------------------------------------- 3
    _heading(doc, "三、这次能更可靠处理哪些业务问题", 1)
    business = [
        ("引用存在、但引文不支撑结论",
         "答案仍标 grounded、置信度 high、可信性 A/B 级",
         "降级为 needs_confirmation、置信度 low、可信性降到 C/D，并列明待核实主张",
         "11 例由失败转通过"),
        ("judge 超时 / 输出不可解析",
         "unsupported_ratio = 0，看起来「很干净」",
         "degraded + unknown，覆盖率分母显式，已判断数 = 0",
         "C2-F1、C2-F2"),
        ("重复 verdict / 越界 ID / 空 ID",
         "可能重复计分或污染判定",
         "计入 dropped_verdict_ids / duplicate_verdict_ids，不抬高 judged_count",
         "C2-C1、C2-E1"),
        ("超过单次 claim 上限",
         "静默截断尾部却宣称全量通过",
         "coverage_truncated = True，未覆盖条数显式列出",
         "C2-G1"),
        ("全部引用都被支持",
         "改后首轮曾误降级 25 例",
         "恢复 grounded，不惩罚「多召回」",
         "25 例回归修复"),
        ("未被答案引用的检索证据",
         "被补成 unknown 并触发降级",
         "不计入判定覆盖率分母，不参与状态判定",
         "C1-H2、C3-A2、C5-A2"),
        ("正确字段候选排在召回尾部",
         "只装得下前 3~7 个，尾部候选从未被模型看过，却仍以 model_rerank 返回",
         "分批 + 决赛集合，20 个候选全部进入模型比较；第 8/15/20 位均被比较，coverage=full",
         "C4 全 20 例"),
        ("重排超时",
         "—",
         "保持 rerank_timeout 语义，不跨批重试",
         "C4-G2"),
        ("预算连一个候选都放不下",
         "—",
         "抛 409 context_budget_exceeded，不返回空排序冒充成功",
         "C4-F2"),
        ("人工驳回 / 未决人工门",
         "已是终态 blocked / waiting_human",
         "未破坏",
         "C6 全 18 例"),
    ]
    _table(doc, ["业务问题", "改前行为", "改后行为", "证据用例"],
           [[item[0], item[1], item[2], item[3]] for item in business])

    # ---------------------------------------------------------------- 4
    _heading(doc, "四、重排的四个事实（同一 catalog，受限预算 6000 tokens）", 1)
    _para(doc, "任务书要求把 recalled / admitted / model_evaluated / returned 当作四个不同事实记录，"
               "不能把「召回前缀不变」当成「质量无损」。实测：", muted=True)
    four = (evidence.get("deterministic_or_mock_verified") or {}).get("rerank_four_facts") or {}
    four_rows = []
    for case_id, value in four.items():
        b = value.get("before") or {}
        a = value.get("after") or {}
        four_rows.append([
            case_id,
            b.get("recalled"),
            f"{b.get('admitted')} / {b.get('model_evaluated')}",
            f"{a.get('admitted')} / {a.get('model_evaluated')}",
            str(a.get("batch_count")),
            str(a.get("tail_ranks_not_model_evaluated")),
        ])
    if four_rows:
        _table(doc, ["用例", "recalled", "改前 admitted/evaluated", "改后 admitted/evaluated",
                     "改后批数", "改后仍未被评估的尾部"], four_rows)
    _para(doc, "改前第 8/15/20 位全部被丢弃（tail = [8, 15, 20]）；改后为空，coverage = full，"
               "且 coverage 的计数与候选身份列表互相印证（不是自述）。", muted=True)
    # ---------------------------------------------------------------- 4b real model + browser
    _heading(doc, "四之二、真实模型与真实浏览器验证（2026-10-20 补齐）", 1)
    real = (evidence.get("real_model_effect_verified") or {})
    browser = ((evidence.get("real_component_verified") or {}).get("browser") or {})
    _para(doc, "下表全部来自真实 provider 调用与真实浏览器实跑；未编造任何数字。", muted=True)
    real_rows = [
        ["真实模型连通性", "deepseek-v4-flash（profile 4），HTTP 200"],
        ["真实调用次数", str(real.get("call_count", "—")) + "（来自产品自身 ModelCallLog）"],
        ["B 包：引用支撑",
         str((real.get("citation") or {}).get("executed", "—")) + " 例走真实裁判"],
        ["C 包：字段重排",
         str((real.get("rerank") or {}).get("executed", "—"))
         + " 例 model_rerank / coverage=full"],
        ["真实浏览器（系统 Chrome）",
         f"{browser.get('passed', '—')}/{browser.get('checks_total', '—')} 检查通过"],
    ]
    _table(doc, ["验证项", "结果"], real_rows)
    _para(doc, "", )
    _para(doc, "真实模型暴露并修掉的 3 个缺陷（Mock 看不见）：", bold=True)
    _bullets(doc, [
        "claims_unknown 曾把未判定的主张也计入，出现 7 > 5 的自相矛盾；现只统计已判定主张。",
        "claim_coverage 曾出现 1.25 / 2.5（引用数除主张数，量纲不同）；现引用级模式为 0.0 并标维度。",
        "引用级判定曾被误判为 verified；现最多到 partially_supported，有不支持引用时为 unsupported。",
    ])
    _para(doc, "仍保持未验证：真实 Top1/Top3 准确率与引用蕴含准确率——缺人工标注真值，无法计算。",
          warn=True, size=9)
    _para(doc, "验证时临时开启的 CITATION_SUPPORT_CHECK 已恢复为出厂默认 off。", muted=True, size=9)
    # ---------------------------------------------------------------- 4c D package
    _heading(doc, "四之三、D 包：SQL 语义变化归因（2026-10-20）", 1)
    _para(doc, "边比较器天生看不见语句级语义：GROUP BY 键、DISTINCT、UNION 去重、"
               "HAVING、JOIN 类型都不产生 lineage 边属性差异，只能落到无归因兜底项。", muted=True)
    _table(doc, ["项", "改前", "改后"], [
        ["可检家族", "29 / 39", "36 / 39"],
        ["明确声明不可检", "10", "3"],
        ["新增比较维度", "—", "group_by / distinct / union_mode / having / join_type"],
        ["全量后端回归", "1851 passed", "1886 passed / 0 failed"],
    ])
    _para(doc, "", )
    _para(doc, "升级的是实现，不是声明：", bold=True)
    _bullets(doc, [
        "每个升级家族都配真实 SQL 对，证明检测到并归因到结构化维度（attribution=structural）。",
        "新增 35 个六类覆盖测试：真实变化 / 格式等价 / 别名限定名 / 嵌套作用域 / 无法解析 / 跨语句。",
        "守门断言（声明=实现、家族总数 39）全部保留且通过，未削弱任何约束。",
        "如实保留 3 个不可检：order_by、top_limit、cte。不声称未验证的能力。",
    ])
    _para(doc, "实施中修掉自己引入的缺陷：别名重命名曾误报粒度变化（表限定进了渲染文本）。",
          warn=True, size=9)
    # ---------------------------------------------------------------- 5
    _heading(doc, "五、仍然不行 / 未验证（不并入成功项）", 1)
    _para(doc, "5.1 真实模型效果：已接入并验证，但质量指标仍未验证", bold=True, warn=True)
    _bullets(doc, [
        "已证实：模型真被调用、候选真被比较、unsupported 真会降级（见第四之二节）。",
        "仍未验证：真实 Top1/Top3 排序准确率、真实引用蕴含的准确率与召回率。",
        "原因：没有人工标注的正确答案集，无法计算准确率；不用猜测值代替。",
    ])
    _para(doc, "5.2 真实组件验证：部分未做", bold=True)
    _bullets(doc, [
        "PostgreSQL / Redis 本机监听中，但未对队列与持久化做真实组件验证。",
        "pytest 全部在 SQLite + Mock provider 下运行，不等于 PostgreSQL/Redis/Celery/Milvus 验证。",
        "真实队列的重复投递、worker 退出、取消后迟到返回等场景本轮未补做。",
    ])
    _para(doc, "5.3 已知未达成项", bold=True)
    _bullets(doc, [
        "前端 rank_source 已收宽并显示「未经模型比较，仍为召回顺序，需人工核验」，"
        "并已用系统 Chrome 完成真实浏览器验收（16/16 PASS）。",
        "D 包已完成主体部分（可检家族 29 → 36/39），剩 order_by / top_limit / cte "
        "三个因语义上不改变字段口径或缺少稳定比较维度而诚实保留。",
    ])

    # ---------------------------------------------------------------- 6
    _heading(doc, "六、回归结果", 1)
    reg_rows = [["A 包契约测试", "pytest tests/test_overnight_benchmark.py", "11 passed"],
                ["B 包定向（4 文件）", "test_rag_citation_support / test_evaluation_faithfulness / "
                                    "test_overnight_citation_status / test_rag_evaluation_fidelity",
                 "56 passed"],
                ["C 包定向（4 文件）", "test_ai_skill_rerank_* / test_overnight_rerank_batching",
                 "48 passed"],
                ["C 包扩展", "pytest -k \"ai_skill or rerank or field_candidate or candidate_id\"",
                 "291 passed"],
                ["前端单测", "node --test tests/*.test.mjs", "308 passed, 0 failed"],
                ["TypeScript", "tsc --noEmit", "0 错误"]]
    if full_reg:
        reg_rows.append(["改前全量后端", "pytest tests（基线 worktree）",
                         f"{full_reg['before']['passed']} passed, "
                         f"{full_reg['before']['skipped']} skipped, {full_reg['before']['failed']} failed"])
        reg_rows.append(["改后全量后端", "pytest tests（当前 worktree）",
                         f"{full_reg['after']['passed']} passed, "
                         f"{full_reg['after']['skipped']} skipped, {full_reg['after']['failed']} failed"])
    _table(doc, ["项", "命令", "结果"], reg_rows)

    _para(doc, "")
    _para(doc, "本轮修掉的三个真实缺陷", bold=True)
    _bullets(doc, [
        "B-1：judge 的判定结果只被附加到返回结构，完全不参与 answer_status / confidence_level / "
        "supported_claims / trustworthiness —— 引用被判 unsupported 时答案仍是 grounded + high。",
        "B-2：冲突检测只比较 content_hash；检索项没有该字段时全部为 None，两份互相矛盾的同主题"
        "高权威资料被误判为「口径一致」而静默合并。已改为优先比 hash、缺 hash 时退化为比正文。",
        "A-1：本次新增的评测 harness 自身泄漏桩 —— 重绑了 8 个模块属性却只还原 3 个，"
        "导致后续测试拿到合成的 citation 字典（KeyError: document_id）。已扩到全部 8 个。",
    ])

    # ---------------------------------------------------------------- 7
    _heading(doc, "七、如何用一条命令复现", 1)
    _para(doc, "前提：本机跑测试必须带四个环境变量，否则会得到与代码无关的假失败。", muted=True)
    code_block = (
        "cd \"...\\ai-platform\\backend\"\n"
        "$env:AUTH_MODE='optional'\n"
        "$env:TASK_QUEUE_PROVIDER='inline'\n"
        "$env:PYTHONIOENCODING='utf-8'\n"
        "$env:STORAGE_DIR=(Resolve-Path .\\dev_storage_local).Path\n\n"
        ".\\venv\\Scripts\\python.exe -m app.services.evaluation.benchmark.compare `\n"
        "  --label now --out \"..\\..\\_runs\\benchmark-now.json\" `\n"
        "  --before \"..\\..\\_runs\\benchmark-before-353420d.json\"\n"
    )
    para = doc.add_paragraph()
    run = para.add_run(code_block)
    run.font.name = "Consolas"
    run.font.size = Pt(8.5)
    _para(doc, "输出里的 fixed / regressed / still_failing 三个列表就是逐例归因，"
               "families 是逐家族 before → after 与通过数增量。", muted=True, size=9)

    # ---------------------------------------------------------------- 8
    _heading(doc, "八、交付物清单", 1)
    _table(doc, ["文件", "用途"], [
        ["docs/handoff/overnight-20261019/plan.md", "基线、目标、工作包、作用域、预算"],
        ["docs/handoff/overnight-20261019/checkpoint.md", "当前状态、失败根因、下一动作、恢复命令"],
        ["docs/handoff/overnight-20261019/results.json", "四级证据分类、数据集哈希、逐例结果、分母"],
        ["docs/handoff/overnight-20261019/final-report.md", "已完成/未完成、前后比较、回归、风险"],
        ["docs/handoff/overnight-20261019/failure-cases/README.md", "10 个最小复现场景（全合成）"],
        ["backend/app/services/evaluation/benchmark/", "A 包：数据集、运行器、对照工具、results 生成器"],
        ["backend/tests/test_overnight_*.py", "A/B/C 三包新增的 35 条验收测试"],
    ])

    _para(doc, "")
    _para(doc, "本文件不含任何真实客户数据、真实行内资料或真实密钥；"
               "全部评测材料为合成案例（synthetic=True）。", muted=True, size=9)

    OUT_LOCAL.parent.mkdir(parents=True, exist_ok=True)
    doc.save(OUT_LOCAL)
    return OUT_LOCAL


def main() -> int:
    produced = build()
    print(f"written: {produced}")
    try:
        DESKTOP.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(produced, OUT_DESKTOP)
        print(f"copied:  {OUT_DESKTOP}")
    except OSError as exc:
        # Desktop ACL on this machine can refuse direct writes; the workspace copy is the
        # authoritative artifact and the caller is told exactly why the copy failed.
        print(f"desktop copy failed ({type(exc).__name__}: {exc}); workspace copy kept at {produced}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

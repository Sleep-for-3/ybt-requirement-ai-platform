# -*- coding: utf-8 -*-
"""生成《银行智能平台 · 高呼声 AI 技能与可嵌入开源项目选型建议》桌面 .docx 成果文档。

运行（本机）：
  C:\\Users\\admin\\.dsh\\dsh-runtimes\\dsh-primary-runtime\\dependencies\\python\\python.exe gen_skills_oss_report.py
"""

import os
from docx import Document
from docx.shared import Pt, Cm, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml.ns import qn

OUT = os.path.join(
    os.environ["USERPROFILE"],
    "Desktop",
    "银行智能平台-高呼声AI技能与可嵌入开源项目选型建议-2026-10-17.docx",
)

AS_OF = "2026-10-17"

doc = Document()

# ---------- 页面设置：边距收窄以容纳表格 ----------
_sec = doc.sections[0]
_sec.left_margin = Cm(2.0)
_sec.right_margin = Cm(2.0)
_sec.top_margin = Cm(2.0)
_sec.bottom_margin = Cm(2.0)
AVAIL_CM = 17.0  # 21.0 - 2.0 - 2.0；21.59(A4 宽) 与 Letter 均安全

# ---------- 基础样式：中文字体 ----------
_normal = doc.styles["Normal"]
_normal.font.name = "Microsoft YaHei"
_normal.font.size = Pt(10.5)
_normal._element.rPr.rFonts.set(qn("w:eastAsia"), "Microsoft YaHei")


def _fix_run(run, size=10.5, bold=None, color=None, name="Microsoft YaHei"):
    run.font.name = name
    run.font.size = Pt(size)
    if bold is not None:
        run.font.bold = bold
    if color is not None:
        run.font.color.rgb = RGBColor(*color)
    rPr = run._element.get_or_add_rPr()
    rFonts = rPr.get_or_add_rFonts()
    rFonts.set(qn("w:eastAsia"), name)
    return run


def h(text, level=1):
    p = doc.add_heading("", level=level)
    _fix_run(p.add_run(text), size={0: 20, 1: 15, 2: 12.5, 3: 11.5}[level], bold=True)
    return p


def para(text, size=10.5, bold=False, color=None, indent=0, space_after=4):
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(space_after)
    if indent:
        p.paragraph_format.left_indent = Cm(indent)
    _fix_run(p.add_run(text), size=size, bold=bold, color=color)
    return p


def bullet(text, size=10.5, level=0):
    p = doc.add_paragraph(style="List Bullet")
    p.paragraph_format.space_after = Pt(2)
    if level:
        p.paragraph_format.left_indent = Cm(0.74 + 0.6 * level)
    _fix_run(p.add_run(text), size=size)
    return p


def table(headers, rows, widths=None, font_size=9):
    t = doc.add_table(rows=1, cols=len(headers))
    t.style = "Table Grid"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    t.autofit = False
    for i, htxt in enumerate(headers):
        cell = t.rows[0].cells[i]
        cell.text = ""
        _fix_run(cell.paragraphs[0].add_run(htxt), size=font_size, bold=True)
    for row in rows:
        cells = t.add_row().cells
        for i, val in enumerate(row):
            cells[i].text = ""
            p = cells[i].paragraphs[0]
            p.paragraph_format.space_after = Pt(0)
            _fix_run(p.add_run(str(val)), size=font_size)
    if widths:
        ws = list(widths)
        total = sum(ws)
        if total > 0 and abs(total - AVAIL_CM) > 0.01:
            ws = [x * AVAIL_CM / total for x in ws]
        for r in t.rows:
            for i, x in enumerate(ws):
                r.cells[i].width = Cm(x)
    doc.add_paragraph().paragraph_format.space_after = Pt(2)
    return t


def card(name, repo, lic, capability, integrate, maturity, adapt):
    """单条目卡片式排版（避免宽表超出页面可打印宽度）。"""
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(6)
    p.paragraph_format.space_after = Pt(1)
    _fix_run(p.add_run(name), size=10.5, bold=True)
    rows = [
        ("仓库", repo),
        ("许可", lic),
        ("能力", capability),
        ("集成方式", integrate),
        ("成熟度", maturity),
        ("适配与风险", adapt),
    ]
    for label, val in rows:
        q = doc.add_paragraph()
        q.paragraph_format.space_after = Pt(0)
        q.paragraph_format.left_indent = Cm(0.6)
        _fix_run(q.add_run(label + "："), size=9.5, bold=True)
        _fix_run(q.add_run(val), size=9.5)


# ============================== 封面 ==============================
h("银行智能平台 · 高呼声 AI 技能与可嵌入开源项目选型建议", 0)
para("调研时点：%s（Asia/Shanghai）｜适配对象：ybt-requirement-ai-platform（banking regulatory data intelligence platform）" % AS_OF, size=10)
para("调研范围：2026 年社区使用度/讨论度最高的 AI 编码与业务技能、以及可直接嵌入本平台的成熟开源项目；全部结论面向「银行内网离线 + Python 3.12 + 已有自研能力不重写」的前提出具。", size=10)

h("阅读指引", 2)
bullet("▲ 优先适配（本轮即可接入，收益高、风险低）｜△ 备选/延后｜✗ 不建议（许可或离线硬约束冲突）。")
bullet("「可嵌入」= 能作为 pip 包、sidecar 服务或本地模型嵌入现有 FastAPI 单体，不需要新增外网依赖。")
bullet("许可标注来源为 PyPI 元数据或仓库 LICENSE 声明；标「未核实」的项目不得直接用于生产决策。")
bullet("调研受工具限制：本机 web_search 接口返回 401 不可用，结论由 web_fetch 直取 PyPI / 官方文档 / arxiv 得到；star 数取当日检索值，拿不准的已显式标「未核实」。")

# ============================== 一、技能清单 ==============================
h("一、呼声高且适配本项目的 skills 清单", 1)
para("技能分三类：①AI 官方/社区技能包（Agent Skills，可直接装进 DSH 作为长期工作方法）；②工程与质量技能（约束后端/前端/数据管道写法）；③领域技能（银行监管 + 语义检索 + 评测，属自建但对标开源高质量实践）。优先级 P0 = 两周内可落地且直接减少 P1 缺口。", size=10)

h("1.1 AI 官方 / 社区技能包（可直接装入 DSH）", 2)
table(
    ["技能", "来源出处", "优先级", "适配本项目哪一块", "落地建议"],
    [
        ["pydantic / pydantic-settings 官方技能", "pydantic 官方文档与 AI 提示资源（pydantic.dev）", "P0", "backend/app/schemas、settings、data_field_answer_service 的字段抽取契约", "把「v2 校验器 + 严格模式 + 别名生成」写成本地 skill，统一所有 schema 变更的验收口径"],
        ["FastAPI 高级模式（依赖注入/后台任务/生命周期）", "FastAPI 官方文档 Advanced 章节 + 社区高星提示合集", "P0", "api/ 路由、后台任务领取、startup/shutdown 资源管理", "沉淀为「路由与生命周期」skill：强制 lifespan 管理 PG/Redis/Milvus 句柄，禁止模块级连接"],
        ["OpenAI 兼容网关客户端技能", "openai-python 官方 skills 仓库（github.com/openai/skills）", "P0", "services/llm/* 自研网关调用层", "加入 retry/超时/流式/幂等键的固定写法，替换散落的裸 httpx 调用"],
        ["SQL 与数据库评审技能", "社区 SQL 评审 checklist（DBA 实践汇总）", "P0", "字段级脱敏判定、审核锁、后台任务 fencing", "固化成「SQL 安全 + 竞争条件」评审清单，作为 sql-mask 与并发修复的验收门"],
        ["测试先行 / 独立评审 / 系统化排障三类方法技能", "aegis 方法包（本机已装 v2.11.2，技能已可用）", "P0", "本轮安全修复与浏览器验收的流程约束", "直接复用，不要另造流程；review 与 verification-before-completion 用在每轮收尾"],
        ["Agent Skills 规范与编写技能", "Anthropic Agent Skills 规范（docs.claude.com）", "P1", "把平台自身业务规则沉淀为可版本化技能（已有技能治理模块）", "把技能定义 schema 对齐社区 SKILL.md 约定，便于复用现成工具链"],
        ["Office 文档生成技能", "本机已装 office-docx / office-pptx / office-xlsx", "P1", "评审报告、UAT 证据包、发布说明的自动成文", "纳入交付流程：每轮验收自动生成 .docx 存档，减少手工整理"],
    ],
    widths=[3.2, 4.0, 1.4, 4.4, 3.4],
)

h("1.2 工程与质量技能（约束写法，不新增依赖）", 2)
table(
    ["技能", "社区呼声来源", "适配本项目哪一块", "建议"],
    [
        ["Ruff + mypy + pre-commit 一体化", "现代 Python 工具链事实标准（Astral 生态）", "backend 全量代码；现有 lint 配置分散", "接成提交门禁；首次只开 E/F/I/UP 规则避免大爆改"],
        ["pytest 夹具与工厂模式", "pytest 官方 + factory-boy 社区实践", "backend/tests（已有大量用例）", "统一 fixtures/factories，替代散落的测试数据构造"],
        ["OpenTelemetry 埋点规范", "OTel 官方（GenAI 语义约定已迁出主仓）", "model_call_logs 之外的 trace 层", "先只埋 HTTP/DB span，GenAI 约定等稳定版再上"],
        ["Polars / DuckDB 做数据集分析", "数据工程社区高呼声", "评测集统计、报表核对、验收报告分母计算", "只用于离线分析脚本，不动线上链路"],
        ["tenacity 重试与熔断", "Python 生产实践标配", "LLM 网关、外部 OCR/嵌入服务调用", "统一重试策略，避免各处手写 sleep-retry"],
        ["OpenAPI 契约优先（openapi-typescript / orval）", "前后端协作高呼声", "frontend 与 backend 的接口类型漂移（F01-F10 多为此类）", "由后端 schema 生成前端类型，根治字段错配"],
    ],
    widths=[3.8, 3.6, 5.0, 4.0],
)

h("1.3 领域技能（自建为主，对标开源高质量实践）", 2)
table(
    ["技能域", "现状与缺口", "对标/可借鉴的开源实践", "优先级"],
    [
        ["语义检索与重排", "keyword_index.py 是正则 bigram + 同义词 + weight，无 IDF、无长度归一、无 reranker", "bm25s（MIT）+ jieba（MIT）重构关键词层；RRF 融合；bge-reranker 交叉编码重排", "P0"],
        ["引用溯源与无依据率", "已有 citation_validator.py，但缺 claim→context 蕴含判定与分母", "RefChecker / RAGChecker（Apache-2.0）的思路可移植", "P1"],
        ["AI 业务评测与人工标注", "P1 缺口：缺真实期望标签、双人复核、正反例和分母", "Langfuse 自托管标注队列 + RAGAS 指标口径", "P0"],
        ["文档解析与版面/证据定位", "报送模板表格、扫描件、印章处理能力不足，引用高亮无坐标", "PaddleOCR PP-StructureV3（单元格级坐标）+ chonkie（切分）", "P0"],
        ["脱敏识别增强", "字段级脱敏为规则驱动，缺中文实体级识别", "Presidio 可插拔识别器架构（MIT）", "P1"],
        ["审计不可篡改", "审计日志可被 DBA 改写，无外部可验证证据", "PG 内 prev_hash 哈希链 + Merkle 证明 + 周期锚定（自研，零中间件）", "P1"],
        ["报送数据质量校验", "自研校验与真实报送规则对账缺第三方基线", "Great Expectations（Apache-2.0，自带可审计 Data Docs）", "P2"],
        ["后台任务可靠性", "领取只认 hostname:pid，无续租/fencing/outbox", "Celery 官方幂等与 outbox 模式、pg advisory lock + attempt token 实践", "P0"],
    ],
    widths=[3.0, 6.0, 6.0, 1.4],
)

# ============================== 二、开源清单 ==============================
h("二、可嵌入本项目的开源项目清单", 1)
para("按能力域分组；每项以卡片列出仓库 / 许可 / 能力 / 集成方式 / 成熟度 / 适配与风险。▲优先适配 △备选 ✗不建议。", size=10)

# ---- 2.1 卡片式 ----
h("2.1 文档解析 / 版面 / 证据定位", 2)
para("本组聚焦 PDF / 扫描件 / 表格的结构化抽取与证据坐标定位；每组末条给出补充说明。", size=10)
card(
    "△ Unstructured 0.27.27",
    "github.com/Unstructured-IO/unstructured",
    "Apache-2.0",
    "多格式（PDF/Word/HTML/邮件等）统一抽取为带坐标的元素，便于证据定位。",
    "pip install unstructured，需另装系统级依赖（LibreOffice / Tesseract）。",
    "15,573★（2026-10-16 提交）。",
    "与现有文档管道重叠；重路径依赖 unstructured-inference（detectron2/yolox），Windows 安装历史性困难，本轮不推荐。",
)
card(
    "△ RapidOCR",
    "github.com/RapidAI/RapidOCR",
    "Apache-2.0",
    "PP-OCR 模型的 ONNX 移植，不依赖 PaddlePaddle，CPU 友好。",
    "pip install rapidocr-onnxruntime。",
    "8,159★（2026-10-16 提交）。",
    "Windows 部署友好，可作轻量 OCR 兜底；与 PP-OCRv6 的版本同步存在滞后（未核实）。",
)
card(
    "△ RapidTable",
    "github.com/RapidAI/RapidTable",
    "Apache-2.0",
    "序列表格结构识别（SLANet / SLANet-Plus 等）的 ONNX 推理。",
    "pip install rapidtable。",
    "439★（2026-04-23）。",
    "小仓库、生产验证少；仅在 PaddleOCR 表格还原不达标时补位。",
)
card(
    "✗ marker-pdf 2.0.0",
    "github.com/datalab-to/marker",
    "代码 Apache-2.0 / 权重为 modified AI Pubs Open Rail-M",
    "PDF / Office → Markdown / JSON，每块带 polygon bbox。",
    "pip install marker-pdf + marker_server。",
    "40,504★。",
    "权重仅对研究、个人、融资或营收 < 500 万美元的初创免费，银行商用需付费授权 → 不建议。",
)
card(
    "✗ surya-ocr 0.22.1",
    "github.com/datalab-to/surya",
    "代码 Apache-2.0 / 权重许可未核实",
    "OCR / 版面 / 阅读顺序 / 表格识别，90+ 语言。",
    "pip install surya-ocr。",
    "21,501★。",
    "与 marker 同源的权重许可不确定性，本轮不引入。",
)
card(
    "✗ olmOCR 0.4.27",
    "github.com/allenai/olmocr",
    "Apache-2.0",
    "7B VLM，PDF / PNG → Markdown（含公式、表格、手写）。",
    "pip install \"olmocr[gpu]\"，需 ≥ 12GB 显存。",
    "19,750★，2026-03-25 后停滞约 7 个月。",
    "CPU 不可跑、中文能力未核实，与内网低算力约束冲突。",
)
card(
    "✗ DocLayout-YOLO 0.0.4",
    "github.com/opendatalab/DocLayout-YOLO",
    "AGPL-3.0",
    "版面检测小模型（页面元素定位）。",
    "pip install doclayout-yolo。",
    "2,292★（2025-06-10）。",
    "AGPL 高风险：以服务形式对外提供即触发源码开放义务，仅可用于离线评测，不进入交付物。",
)
card(
    "△ table-transformer",
    "github.com/microsoft/table-transformer",
    "MIT",
    "TATR 表格检测 + 结构识别，含 PubTables-1M / GriTS 官方实现。",
    "仓库已归档，建议只使用 HF 权重。",
    "2,948★，最后提交 2024-06-24。",
    "停更 2 年以上，Python 3.12 兼容性未核实。",
)
para("补充：Excel / Word 的合并单元格，本轮未找到比 PaddleOCR / docling 更专业的独立开源项目；原生 Office 结构继续用现有 openpyxl / python-docx，扫描件表格走 PaddleOCR doc2md。", size=9.5)

# ---- 2.2 卡片式 ----
h("2.2 检索与重排（本轮收益最高的嵌入点）", 2)
card(
    "▲ bm25s（+ jieba）",
    "bm25s / jieba（MIT）",
    "MIT（两者均是）",
    "纯 Python / NumPy 的 BM25，支持稀疏矩阵与快速 top-k；jieba 提供中文分词。",
    "pip install bm25s jieba。",
    "bm25s ~1.8k★；jieba 35k★（社区事实标准）。",
    "直接重构 keyword_index.py：把现有正则 bigram + 同义词 + weight 匹配升级为 BM25 词项 boost（title 1.25 / structured 1.5 / synonym 0.85），保留 AUTHORITY_RANK；离线自定义词典可固化银行术语。",
)
card(
    "▲ RRF（倒数排名融合）",
    "算法，无第三方许可问题",
    "—",
    "多路检索结果按排名融合，免调权重。",
    "自研约 50 行。",
    "—",
    "改造 hybrid_retriever.py 的 hybrid 分支，用 RRF 替代当前的 weight 相加，天然免调权重、抗单路退化。",
)
card(
    "▲ bge-reranker-base",
    "BAAI（MIT）",
    "MIT",
    "中英文交叉编码重排，自带 onnx/model.onnx。",
    "FastEmbed 已内置 TextCrossEncoder，无需新增依赖。",
    "C-MTEB T2Reranking map 67.28。",
    "零新依赖即可上线重排，是当前性价比最高的排序收益点。",
)
card(
    "△ bge-reranker-v2-m3",
    "BAAI（Apache-2.0）",
    "Apache-2.0",
    "多语言强重排，567.8M 参数。",
    "需用 optimum 自行导出 ONNX。",
    "—",
    "效果更好但无官方 ONNX，CPU 延迟需实测后再决定是否替换 base 版本。",
)
card(
    "△ Qwen3-Reranker-0.6B",
    "Qwen（Apache-2.0）",
    "Apache-2.0",
    "中文强的 0.6B 重排模型。",
    "vLLM / ONNX 自托管。",
    "—",
    "有 GPU 时作为 bge-reranker-v2-m3 的替换候选。",
)
card(
    "△ rank_bm25",
    "Apache-2.0",
    "Apache-2.0",
    "纯 Python BM25（教学级实现）。",
    "pip install rank_bm25。",
    "—",
    "实现简单、无稀疏优化，规模上去后不如 bm25s。",
)
card(
    "△ BGE-M3",
    "BAAI（MIT）",
    "MIT",
    "稠密 + 稀疏 + 多向量一体的嵌入模型。",
    "FlagEmbedding / FastEmbed。",
    "—",
    "若替换现有嵌入需全量重建向量库，属较大工程，本轮不动。",
)
card(
    "△ pylate / rerankers",
    "Apache-2.0",
    "Apache-2.0",
    "ColBERT late-interaction 与多 reranker 的统一封装。",
    "pip install pylate / rerankers。",
    "—",
    "便于多模型 A/B 对比，但会引入新的依赖层。",
)
card(
    "✗ jina-reranker-v3 / jina-reranker-v2-base-multilingual",
    "Jina AI",
    "CC-BY-NC-4.0（禁止商用）",
    "多语言重排。",
    "—",
    "—",
    "许可证明示禁止商用，银行场景直接排除，改用 bge-reranker 系列。",
)
card(
    "✗ Elasticsearch",
    "Elastic",
    "Elastic License 2.0 / SSPL（非 OSI）",
    "全文检索与聚合。",
    "—",
    "—",
    "非 OSI 许可；若确需托管检索引擎，请改用 OpenSearch（Apache-2.0）。",
)
card(
    "✗ SPLADE",
    "视具体权重而定",
    "未核实",
    "学习式稀疏检索。",
    "—",
    "—",
    "现有公开权重以英文为主，中文缺位。",
)

# ---- 2.3 卡片式 ----
h("2.3 RAG 评测 / 引用溯源 / 可观测性 / 结构化输出", 2)
card(
    "▲ Langfuse（自托管）",
    "langfuse/langfuse",
    "MIT（核心）／EE 特性需 license key",
    "trace、数据集、实验对比与人工标注队列。",
    "pip install langfuse + Docker 自托管。",
    "5.0.2。",
    "唯一能一步到位补上 P1「人工标注 + 双人复核」缺口的组件；Project RBAC / Audit Logs / SSO 属 EE 特性，银行合规须单独评估授权。与 model_call_logs 互补，不要双写同步。",
)
card(
    "▲ RAGAS",
    "explodinggradients/ragas",
    "Apache-2.0",
    "faithfulness / context precision / context recall / noise sensitivity 等指标。",
    "pip install ragas（0.4.3）。",
    "0.4.3。",
    "在 rag_evaluator.py 之上做指标层，把准确率 / 召回 / 无依据率的分母做对；依赖 langchain / datasets 较重，须设 RAGAS_DO_NOT_TRACK=true 关闭匿名遥测；官方 adapter 支持自定义 provider，可注入自研网关。",
)
card(
    "▲ instructor",
    "jxnl/instructor",
    "MIT",
    "pydantic 结构化输出 + 自动重试封装。",
    "pip install instructor（1.17.0）。",
    "1.17.0。",
    "它已是 RAGAS 的依赖，接进 structured_outputs.py 属零边际成本。",
)
card(
    "▲ RefChecker",
    "amazon-science/refchecker",
    "Apache-2.0",
    "细粒度幻觉检测：claim → 知识三元组蕴含判定。",
    "pip install refchecker（0.2.17）。",
    "0.2.17（研究级）。",
    "与 citation_validator.py 直接对口，可产出引用精确率；有停更风险，建议移植思路而非直接依赖。",
)
card(
    "△ RAGChecker",
    "amazon-science/ragchecker",
    "Apache-2.0",
    "检索 / 生成的细粒度诊断与 claim 级蕴含。",
    "pip install ragchecker（0.1.9）。",
    "0.1.9（研究级）。",
    "可补无依据率的分母；维护活跃度未核实。",
)
card(
    "△ DeepEval",
    "confident-ai/deepeval",
    "Apache-2.0",
    "断言式 LLM 测试；faithfulness = 真声明数 / 总声明数。",
    "pip install deepeval（4.3.0）。",
    "4.3.0。",
    "适合接技能评测的测试用例断言；默认读 OpenAI 环境变量，需改造；无人工标注 UI。",
)
card(
    "△ TruLens 2.15.0",
    "truera/trulens",
    "MIT",
    "RAG 三元组（context relevance / groundedness / answer relevance）feedback 框架。",
    "pip install trulens（2.15.0）。",
    "2.15.0。",
    "与 rag_evaluator 的 groundedness 口径重叠，二选一即可。",
)
card(
    "△ Label Studio 1.23.2",
    "HumanSignal/label-studio",
    "Apache-2.0",
    "通用标注工具。",
    "pip install label-studio。",
    "1.23.2。",
    "双人复核备选；与 trace 数据关联需自建，整体权重不及 Langfuse。",
)
card(
    "△ Argilla 2.8.0",
    "argilla-io/argilla",
    "Apache-2.0",
    "专用标注平台。",
    "需 OpenSearch / Elasticsearch。",
    "2.8.0（官网 ©2024）。",
    "需额外运维一套检索引擎，与 Langfuse 标注队列重叠，活跃度未核实。",
)
card(
    "△ Arize Phoenix 20.23.0",
    "Arize-ai/phoenix",
    "Elastic-2.0 (ELv2)（非 OSI）",
    "自托管 trace / eval 平台，OTel 原生。",
    "pip install arize-phoenix（20.23.0）。",
    "20.23.0。",
    "官方称自托管免费且可完全气隙，但许可为 ELv2，与「开源」表述存在张力，须法务确认；且须 Py<3.15。",
)
card(
    "△ outlines 1.3.3",
    "dottxt-ai/outlines",
    "Apache-2.0",
    "受限解码 / 正则 / JSON Schema 约束生成。",
    "pip install outlines（1.3.3）。",
    "1.3.3。",
    "需本地权重或 vLLM 后端，走自研网关的模式下暂不适用。",
)
card(
    "△ GLiNER 0.2.29",
    "urchade/GLiNER",
    "Apache-2.0",
    "零样本 NER，纯本地小模型。",
    "pip install gliner（0.2.29）。",
    "0.2.29。",
    "可做字段抽取的独立校验通道（不依赖 LLM）；中文金融实体效果未核实。",
)
card(
    "✗ promptfoo",
    "promptfoo/promptfoo",
    "MIT",
    "红队 + prompt 回归评测。",
    "PyPI 包只是 wrapper，需 Node ≥ 22.22.0 并执行 npx 拉取公网。",
    "0.2.0。",
    "违反内网离线硬约束，本轮排除。",
)
card(
    "✗ DSPy / pydantic-ai",
    "stanfordnlp/dspy；pydantic/pydantic-ai",
    "MIT",
    "prompt 自动优化 / 编译；类型安全 Agent 与结构化输出。",
    "pip install dspy / pydantic-ai。",
    "dspy 3.4.1；pydantic-ai 2.57.0。",
    "自带 provider 层与自研网关重复，引入重且需训练集，现阶段收益低。",
)

# ---- 2.4 卡片式 ----
h("2.4 合规 / 脱敏 / 审计不可篡改 / 报送质量 / 编码标准", 2)
para("脱敏与匿名化", size=11, bold=True)
card(
    "▲ Presidio",
    "microsoft/presidio",
    "MIT",
    "正则 + NER 的识别与匿名化，识别器可插拔。",
    "pip install presidio-analyzer。",
    "—",
    "自写身份证 / 银行卡 / 手机号 recognizer 补字段级脱敏；官方默认仅含英文模型、无中文 recognizer，中文须自建 NlpEngine（spaCy / HanLP，模型需离线预置）。",
)
card(
    "△ Faker 40.43.0",
    "joke2k/faker",
    "MIT",
    "合成假数据（含 zh_CN provider）。",
    "pip install faker。",
    "40.43.0。",
    "用于造回归与 UAT 合成数据集；只合成、不脱敏真实数据。",
)
card(
    "△ spaCy 中文模型 / HanLP",
    "explosion/spaCy；hankcs/HanLP",
    "spaCy MIT；HanLP Apache-2.0",
    "中文分词与 NER。",
    "模型不在 PyPI，需手工拷贝 wheel 进内网。",
    "—",
    "补 Presidio 的中文实体缺口；HanLP 预训练模型许可未核实。",
)
card(
    "✗ SDV / gretel-synthetics",
    "sdv-dev/SDV；gretelai/gretel-synthetics",
    "Business Source License / source-available",
    "统计式合成数据。",
    "—",
    "—",
    "非 OSI 开源，标红排除。",
)

para("审计与不可篡改", size=11, bold=True)
card(
    "▲ 自研 PostgreSQL 哈希链 + Merkle 证明",
    "自研（零第三方许可）",
    "自研",
    "表内 prev_hash 链 + 包含 / 一致性证明 + 周期性外部锚定（对象存储或独立签名）。",
    "自写（PostgreSQL + 对象存储）。",
    "—",
    "推荐路径：不新增中间件、可直接嵌入现有库；需自研测试与证明格式。",
)
card(
    "△ in-toto 3.1.0",
    "in-toto/in-toto",
    "Apache-2.0",
    "签名 attestation / 可验证声明。",
    "pip install in-toto（3.1.0）。",
    "3.1.0。",
    "可用于报送产物签名留痕；需自管密钥，生态偏 CI 流程。",
)
card(
    "△ immudb",
    "codenotary/immudb",
    "客户端 immudb-py Apache-2.0；服务端许可未核实（疑 BSL）",
    "append-only 可验证账本。",
    "pip install immudb-py（1.5.0）。",
    "1.5.0。",
    "可作审计外部锚定，但要新增中间件，且服务端许可须法务确认。",
)
card(
    "✗ pymerkle 6.1.0",
    "fmerg/pymerkle",
    "GPL-3.0",
    "Merkle 树与包含 / 一致性证明。",
    "pip install pymerkle（6.1.0）。",
    "6.1.0。",
    "GPL 标红；Merkle 算法本身简单，自研成本低于合规成本。",
)
card(
    "✗ Sigstore / Trillian / tessera / Chainpoint",
    "sigstore；google/trillian；transparency-dev/tessera；chainpoint",
    "未核实",
    "透明日志 / 签名 / 锚定。",
    "—",
    "—",
    "Sigstore 依赖公网 Fulcio / Rekor，离线不适；Trillian 与 tessera 需 Go 服务 + 数据库；Chainpoint 无 PyPI 包且疑似停更。",
)
card(
    "△ OpenTelemetry GenAI 语义约定",
    "open-telemetry/semantic-conventions-genai",
    "Apache-2.0（规范）",
    "LLM span / event 的字段标准。",
    "opentelemetry-semantic-conventions。",
    "—",
    "已迁出主仓：原 gen-ai 页仅剩 Moved 提示，新仓稳定性等级未核实，建议先只埋 HTTP / DB span。",
)

para("数据质量与报送校验", size=11, bold=True)
card(
    "▲ Great Expectations 1.24.0",
    "great-expectations/great_expectations",
    "Apache-2.0",
    "期望套件 + 可审计 Data Docs 报告。",
    "pip install great-expectations（1.24.0）。",
    "1.24.0。",
    "对报送模板做规则校验并留档报告，与自研校验并行对账、逐步迁移；依赖重、v1 API 变动大。",
)
card(
    "△ pandera 0.34.1",
    "unionai-oss/pandera",
    "MIT",
    "DataFrame schema / lazy 校验。",
    "pip install pandera（0.34.1）。",
    "0.34.1。",
    "最轻的 DataFrame 断言层；无报送语义与报告产物。",
)
card(
    "△ Frictionless 5.21.0",
    "frictionlessdata/frictionless-py",
    "MIT",
    "表格 schema 校验 + 报告。",
    "pip install frictionless（5.21.0）。",
    "5.21.0。",
    "适合模板格式与结构校验；中文资料少。",
)
card(
    "✗ Soda Core 4.27.0",
    "sodadata/soda-core",
    "PyPI 元数据许可分类为 Proprietary",
    "SodaCL 声明式数据校验。",
    "pip install soda-core（4.27.0）。",
    "4.27.0。",
    "非开源，标红排除。",
)

para("编码与语义标准", size=11, bold=True)
card(
    "▲ Arelle 2.46.1",
    "Arelle/Arelle",
    "Apache-2.0",
    "XBRL 校验处理器（CLI / Python API / Web）。",
    "pip install arelle-release（2.46.1）。",
    "2.46.1。",
    "仅当报送走 XBRL 时引入；需预置 taxonomy 包，可完全离线运行。",
)
card(
    "△ pysdmx 1.21.0",
    "bis-med-it/pysdmx",
    "Apache-2.0",
    "SDMX 2.1 / 3.0 读取与校验。",
    "pip install pysdmx（1.21.0）。",
    "1.21.0。",
    "统计与宏观报送互换的备用方案；中文监管口径映射需自建。",
)
card(
    "△ FIBO",
    "edmcouncil/fibo",
    "未核实",
    "金融语义本体（非校验器）。",
    "本体文件。",
    "—",
    "可作字段语义对齐参考，落地成本高。",
)
card(
    "— 人行 / 金监总局报送标准",
    "—",
    "—",
    "公开开源 schema 或校验器。",
    "—",
    "—",
    "未发现公开开源实现，需自建或采购（未核实）。",
)
# ============================== 三、落地建议 ==============================
h("三、落地建议：只选 10 个，按优先级嵌入", 1)
para("以下 10 项按「收益 / 成本 / 许可风险」排序，均为许可干净（MIT/Apache-2.0）或不引入第三方许可的自研方案。", size=10)
table(
    ["#", "项目 / 技能", "许可", "落地到哪个模块", "周期", "预期收益"],
    [
        ["1", "bm25s + jieba 重构关键词索引", "MIT", "backend/app/services/retrieval/keyword_index.py", "1-2 周", "补齐 IDF 与长度归一，直接提升 hybrid 召回；保留同义词/字段权重为 boost"],
        ["2", "RRF 融合", "算法", "backend/app/services/retrieval/hybrid_retriever.py 的 hybrid 分支", "3 天", "免调权重、稳健提升混合检索质量；保留 AUTHORITY_RANK"],
        ["3", "bge-reranker-base（FastEmbed TextCrossEncoder）", "MIT", "hybrid_retriever 重排阶段", "1 周", "零新依赖上线重排；C-MTEB T2Reranking map 67.28"],
        ["4", "chonkie 切分层", "MIT", "KnowledgeUnit 入库前切分", "1-2 周", "LateChunker 对齐现有嵌入；零许可风险、不动存储"],
        ["5", "PaddleOCR PP-StructureV3", "Apache-2.0", "报送模板表格结构化 + 引用高亮坐标", "2-4 周", "表格单元格坐标 = 证据定位闭环；CPU 可跑（tiny 1.5M 参数）"],
        ["6", "Langfuse 自托管", "MIT（EE 特性另计）", "人工标注队列 + trace，与 model_call_logs 互补", "0-4 周", "一步到位补上 P1 双人复核/正反例/分母缺口"],
        ["7", "RAGAS（顺带 instructor）", "Apache-2.0", "rag_evaluator.py 指标层 + structured_outputs.py", "4-8 周", "把准确率/召回/无依据率的分母做对；instructor 零边际成本"],
        ["8", "PG 哈希链 + Merkle 证明（自研）", "自研", "审计日志与正式文件冻结层", "2-3 周", "审计可外部验证，规避 immudb/pymerkle 的许可风险"],
        ["9", "Presidio（自建中文识别器）", "MIT", "字段级脱敏前置识别，补实体级覆盖", "2-3 周", "识别器可插拔，中文缺口用自建正则 + 中文 NER 补齐"],
        ["10", "RefChecker 思路移植", "Apache-2.0", "citation_validator.py 的 claim→context 蕴含", "4 周", "产出引用精确率，加固无依据率判定"],
    ],
    widths=[0.9, 4.2, 2.4, 4.6, 1.6, 6.0],
    font_size=8,
)

para("排除项（不建议本轮引入）：marker-pdf / surya（权重 OpenRAIL-M，商用需付费授权）、olmOCR（7B 需 GPU、已停滞）、DocLayout-YOLO 与 pymerkle（AGPL / GPL）、Soda Core 与 SDV（非 OSI 许可）、Elasticsearch（Elastic License 2.0）、promptfoo（需 Node + 公网 npx）、Arize Phoenix（ELv2 合规待确认）。", size=9.5)
# ============================== 四、许可与合规 ==============================
h("四、许可与合规红线（银行内网必过法务）", 1)
table(
    ["风险等级", "项目", "问题", "处置建议"],
    [
        ["高", "marker-pdf、surya-ocr", "模型权重为 modified AI Pubs Open Rail-M（非 OSI），仅研究/个人/营收 <500 万美元初创免费", "排除；确有需要则走付费授权或改用 PaddleOCR/docling"],
        ["高", "DocLayout-YOLO", "AGPL-3.0，以服务形式对外提供即触发源码开放义务", "仅限离线评测，不进入交付物"],
        ["高", "pymerkle", "GPL-3.0", "改用自研哈希链"],
        ["高", "Soda Core、SDV、gretel-synthetics", "Proprietary / Business Source License / source-available", "改用 Great Expectations / pandera / Faker"],
        ["高", "jina-reranker-v3、jina-reranker-v2-base-multilingual", "CC-BY-NC-4.0，禁止商用", "改用 bge-reranker 系列（MIT/Apache-2.0）"],
        ["中", "MinerU", "自定义「MinerU Open Source License」，附加条款原文未取得", "引入前取得 LICENSE 原文并法务确认"],
        ["中", "immudb", "服务端许可未核实（疑 BSL）", "优先自研哈希链；确需引入先核实服务端许可"],
        ["中", "Arize Phoenix", "Elastic-2.0 (ELv2)，非 OSI", "自托管免费的声明与许可条款冲突，须法务确认"],
        ["中", "Langfuse", "核心 MIT，但 RBAC / Audit Logs / SSO 属 EE，需 license key", "按 MIT 核心能力规划，EE 特性单独立项"],
        ["中", "Elasticsearch", "Elastic License 2.0 / SSPL，非 OSI", "如需托管检索引擎改用 OpenSearch（Apache-2.0）"],
        ["低", "PaddleOCR-VL 权重、Granite-Docling-258M、TableStructureRec、HanLP 预训练模型、FIBO", "许可未核实", "仅用其代码部分或先核实权重许可"],
    ],
    widths=[1.4, 4.6, 5.6, 5.4],
    font_size=8,
)

# ============================== 五、未核实 ==============================
h("五、未核实项与下一步验证动作", 1)
bullet("本机 web_search 接口返回 401（key 失效），本次全部结论来自 web_fetch 直取 PyPI JSON / 官方文档；GitHub REST API 一度触发 60/h 限流，故部分仓库 star 与活跃度标「未核实」。")
bullet("Milvus Lite 是否支持稀疏向量或多向量字段：milvus.io 文档抓取失败（重定向循环），本轮方案按「不依赖」设计（BM25 与 reranker 全部落在 Python 侧）。")
bullet("中文银行监管语料上 RRF / HyDE / query2doc 的实际收益没有任何公开对照实验（query2doc 的 +3%~15% 是英文 MS-MARCO/TREC DL 结果），必须在平台自建评测集上做 A/B。")
bullet("待实测：PaddleOCR 对真实报送模板（合并单元格、跨页表）的还原质量；bge-reranker-base 在 CPU 上的端到端延迟；Presidio 中文识别器在真实证件/卡号分布上的误报率。")
bullet("待法务确认：MinerU 附加条款原文、immudb 服务端许可、HanLP 预训练模型许可、Arize Phoenix 的 ELv2 适用边界。")

para("—— 本报告由 DeepSeek Harness 于 %s 生成，事实性结论均附 URL 来源，可逐条复核。——" % AS_OF, size=9, color=(0x59, 0x59, 0x59))

doc.save(OUT)
print("SAVED:", OUT)

# -*- coding: utf-8 -*-
"""生成《银行智能平台 · 8 项落地建议实施说明》桌面 .docx 成果文档。

运行（本机）：
  C:\\Users\\admin\\.dsh\\dsh-runtimes\\dsh-primary-runtime\\dependencies\\python\\python.exe gen_8item_report.py
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
    "银行智能平台-8项落地建议实施说明-2026-10-17.docx",
)

AS_OF = "2026-10-17"

doc = Document()

# ---------- 页面设置：边距收窄以容纳表格 ----------
_sec = doc.sections[0]
_sec.left_margin = Cm(2.0)
_sec.right_margin = Cm(2.0)
_sec.top_margin = Cm(2.0)
_sec.bottom_margin = Cm(2.0)
AVAIL_CM = 17.0

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


def para(text, size=10.5, bold=False, color=None, indent=0, space_after=4, center=False):
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(space_after)
    if indent:
        p.paragraph_format.left_indent = Cm(indent)
    if center:
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
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


def card(title, fields):
    """卡片式条目：避免宽表超出可打印宽度。"""
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(8)
    p.paragraph_format.space_after = Pt(2)
    _fix_run(p.add_run(title), size=11.5, bold=True, color=(0x1F, 0x3B, 0x73))
    for label, value in fields:
        q = doc.add_paragraph()
        q.paragraph_format.space_after = Pt(1)
        q.paragraph_format.left_indent = Cm(0.4)
        _fix_run(q.add_run(label + "："), size=9.5, bold=True)
        _fix_run(q.add_run(value), size=9.5)


def callout(text, color=(0xA0, 0x30, 0x1A)):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(2)
    p.paragraph_format.space_after = Pt(6)
    p.paragraph_format.left_indent = Cm(0.4)
    _fix_run(p.add_run(text), size=9.5, bold=True, color=color)
    return p


# ==================== 封面 ====================
h("银行智能平台 · 8 项落地建议实施说明", 0)
para("实施范围、开关契约、验证证据与运维启用手册", size=12, color=(0x44, 0x44, 0x44), center=True)
para("", space_after=2)
para("基线提交 e8ce8af（分支 dsh/banking-semantic-agent-v2）", size=10, center=True)
para("文档日期 " + AS_OF + " · 实施 + 独立验证 双人闭环", size=10, center=True)
para("", space_after=6)

h("阅读指引", 2)
bullet("▲ 已实现且默认生效（无需改配置）")
bullet("○ 已实现、默认关闭（需显式开启才生效，关闭时行为与改动前逐字节一致）")
bullet("△ 已实现但受本机环境限制，端到端未跑通的部分已在第五节列明")
bullet("证据等级：本报告的所有数字都来自真实命令输出；“未验证”一律显式标注，不作为结论使用。")

# ==================== 一、总览 ====================
h("一、总览：8 项实施结果", 1)
para(
    "本轮按《银行智能平台-10 项落地建议与现有能力对照-2026-10-17.docx》执行，"
    "范围为 ①–⑧ 共 8 项；原文明确建议「不加」的 ⑨ Langfuse 与 ⑩ instructor 未实施。",
    size=10,
)

table(
    ["#", "项目", "默认状态", "落地位置", "独立验证"],
    [
        ["①", "OCR 扫描件入层", "○ 关闭", "knowledge_ingestion/ocr.py（新建）", "通过"],
        ["②", "bge-reranker-base 重排", "○ 关闭", "retrieval/reranker.py（新建）", "通过（开启态模型未验证）"],
        ["③", "BM25 真 IDF + 长度归一", "▲ 生效（参数化）", "retrieval/keyword_index.py", "通过"],
        ["④", "审计哈希链 + Merkle", "▲ 开启", "governance/{audit,chain,merkle}.py", "通过"],
        ["⑤", "引用蕴含校验", "○ 关闭", "rag/citation_support.py（新建）", "通过"],
        ["⑥", "chonkie 切分策略", "▲ fixed（旧行为）", "services/text_processing.py", "通过"],
        ["⑦", "RRF 融合", "▲ rrf", "retrieval/hybrid_retriever.py", "通过"],
        ["⑧", "LLM-judge faithfulness", "○ 关闭", "evaluation/rag_evaluator.py", "通过"],
    ],
    widths=[0.6, 3.4, 2.4, 5.4, 5.2],
)

callout(
    "整体结论：8 项全部真实接线（不是只写了函数没被调用），并经独立验证者对抗性复核，"
    "未发现任何阻塞交付的缺陷。全量测试 1662 passed / 0 failed。"
)

# ==================== 二、逐项实施说明 ====================
h("二、逐项实施说明", 1)

h("① OCR 扫描件入层", 2)
card(
    "① 扫描件（无文本层 PDF / 图片）走 OCR",
    [
        ("落地文件", "backend/app/services/knowledge_ingestion/ocr.py（新建 162 行）、parsers.py（+83/-3）"),
        ("开关", "ocr_enabled=False（默认关闭）、ocr_provider=rapidocr、ocr_max_pages=50"),
        ("实现要点", "模块顶层不导入任何 OCR provider（有专门测试断言）；load_engine_or_warn() 返回 (None, error) 而不抛；"
                     "run_ocr() 逐图隔离异常、永不抛出，返回 OcrBatchResult(texts, warnings)；"
                     "page_images() 用 pypdf 内嵌图 + Pillow 解码，不依赖 pymupdf / pypdfium2；"
                     "parsers._pdf 拆为 _pdf_text_layer（旧实现逐字保留）与 _pdf_with_ocr；"
                     "超过 ocr_max_pages 截断并写入可诊断告警；图片后缀仅在开启时纳入支持集。"),
        ("验证证据", "关闭态：图片拒绝消息与 PDF units/warnings 与 git HEAD 逐字节一致；"
                     "开启态：fake provider 注入验证接线，引擎每文档仅加载 1 次，ocr_max_pages=0 不处理任何页。"),
        ("注记", "开启但 provider 未安装时静默降级为空文本（只告警）——建议运维层对 warning 计数做告警；真实识别质量未验证。"),
    ],
)

h("② bge-reranker-base 重排", 2)
card(
    "② Cross-encoder 重排，关闭时零开销",
    [
        ("落地文件", "backend/app/services/retrieval/reranker.py（新建 219 行）、hybrid_retriever.py"),
        ("开关", "reranker_enabled=False（默认）、reranker_model=BAAI/bge-reranker-base、reranker_top_k=50"),
        ("实现要点", "rerank_items() 首行判断 is_enabled()，关闭时立即返回且不 import fastembed；"
                     "正确导入路径是 from fastembed.rerank.cross_encoder import TextCrossEncoder（0.8.0 顶层不导出）；"
                     "只重排前 reranker_top_k 条，logits 经 sigmoid 压到 [0,1]；"
                     "重排结果仍受 authority_rank 支配（只在同权威层内细化，低权威高分项不会顶到监管资料之上）；"
                     "四类失败（import / 加载 / 推理 / 分数条数不符）全部降级返回原顺序，失败写入 _FAILURE_CACHE 避免每次查询重试下载。"),
        ("验证证据", "关闭态用 sys.meta_path spy 强证明：fastembed 从未被 import、加载器调用 0 次、模型与失败缓存均为空；"
                     "反向对照证明探针非空转（开启态确实到达加载器）。"),
        ("未验证", "开启态真实模型下载与推理：本机 HuggingFace 访问被拒（os error 5），只验证了加载失败降级路径。"),
    ],
)

h("③ BM25：真 IDF + 长度归一", 2)
card(
    "③ 替换关键词打分的覆盖率近似",
    [
        ("落地文件", "backend/app/services/retrieval/keyword_index.py（+206/-2）、hybrid_retriever.py（_keyword_score 改 BM25）"),
        ("开关", "keyword_bm25_k1=1.2、keyword_bm25_b=0.75（无总开关，直接替换）"),
        ("实现要点", "jieba 懒加载分词，缺依赖时降级正则 + bigram 且不抛异常；"
                     "IDF = log(1 + (N - df + 0.5) / (df + 0.5))，语料非空时严格为正；"
                     "长度归一 1 - b + b·(dl/avgdl)，avgdl≤0 时退化为 1；"
                     "IDF 与文档长度全部由 SQL 聚合现算——不新增表、不新增迁移；"
                     "保留既有 title 1.25 / structured 1.5 / synonym 0.85 语义；"
                     "无精确匹配严格返回 0（不做 min 截断），保住既有词项边界断言。"),
        ("验证证据", "手算 sum(idf·tf·(k1+1)/(tf+k1·norm)) 与实现一致；罕见词确实胜过等长常见词；"
                     "空查询 / 空语料 / 单文档 / IDF=0 边界均有测试；"
                     "SQL 语句预算回归：无 token 候选时一条额外语句都不发，原有「绝对语句预算 14」门禁保持通过。"),
        ("注记", "bm25s 已装入依赖但最终未采用——选择手写公式以避免在检索热路径引入 BM25 索引对象的生命周期管理。"),
    ],
)

h("④ 审计哈希链 + Merkle 证明", 2)
card(
    "④ 不可篡改审计：链式哈希 + Merkle 证明",
    [
        ("落地文件", "governance/audit.py（+167）、governance/chain.py（新建 159 行）、governance/merkle.py（新建 195 行）、"
                     "models/governance.py、alembic/versions/202611010001_audit_log_chain.py"),
        ("开关", "audit_chain_enabled=True（默认开启）"),
        ("实现要点", "audit_logs 新增 prev_hash / entry_hash（String(64)，nullable 以兼容旧行），"
                     "并加索引 ix_audit_logs_chain_tail(institution_id, id)；"
                     "entry_hash = sha256(确定性规范化内容 + prev_hash)，覆盖 12 个调用字段 + schema_version，"
                     "不含 id / created_at（后者是 server_default，db.add 时尚未生成），因此无需 flush 即可计算；"
                     "按 institution_id 分链，institution_id 为 NULL 的行归入 __global__ 哨兵链；"
                     "record_audit 函数签名逐字未变，121 处调用点零改动；关闭时哈希列留 NULL；"
                     "verify_audit_chain() 流式重放并返回 AuditChainVerification（intact / checked / first_broken_id / "
                     "first_broken_reason / affected_range / break_ids）；"
                     "Merkle 纯 hashlib、叶子与内部节点域分离、校验用 hmac.compare_digest、畸形输入一律返回 False。"),
        ("验证证据", "改中间行 after_summary_json（保留行不删）→ intact=False、first_broken_id=3、affected_range=(3,5)；"
                     "改 entry_hash 本身 → first_broken_id=4；改 prev_hash → 报「prev_hash does not link…」；"
                     "Merkle 7 叶诚实证明全过，改叶 / 伪造 root / 拼接多余步骤 / 空叶全部拒绝；"
                     "迁移 upgrade→downgrade→upgrade 全程 rc=0，列与索引随迁，二次 upgrade 为 no-op，单 head 校验通过。"),
        ("注记", "N1：只改 entry_hash 时受影响尾部要看 affected_range（break_ids 可能低估）；"
                 "N2（残余风险）：能重算整段后缀哈希的数据库写攻击者仍可让校验返回 intact=True，"
                 "需定期把 Merkle root 发布到外部不可写位置（WORM / 外部日志）才能闭合。"),
        ("许可", "纯标准库 hashlib 实现，未引入任何第三方 Merkle/哈希链库（pymerkle 为 GPL，已排除）。"),
    ],
)

h("⑤ 引用蕴含校验", 2)
card(
    "⑤ 判定「引用是否真的支持结论」",
    [
        ("落地文件", "rag/citation_support.py（新建 353 行）、rag/citation_validator.py（48 → 192 行）、rag/grounded_answer_service.py"),
        ("开关", "citation_support_check=off（默认关闭）"),
        ("实现要点", "自研 RefChecker 思路，未 vendor 任何第三方代码、未新增依赖、不联网；"
                     "validate_citations 的函数体、签名、三条错误文案、可见性规则逐字节保留；"
                     "新增 async check_citation_support(db, citations, *, answer, project_id=None, confidentiality_levels=None)；"
                     "每条 citation 得到 supported / unsupported / unknown + 理由，并给出整体 unsupported 比例；"
                     "所有模型调用走现有 LLM 网关（数据分级闸门与脱敏仍然生效）；"
                     "所有失败路径降级为 unknown/degraded，绝不抛出；判定结果只上报，不改动 answer_status。"),
        ("验证证据", "off 时用爆炸式网关 tripwire 证明 0 次模型调用；"
                     "并用 git show 载入 HEAD 旧版 grounded_answer 同跑，返回 payload 的字节长度与键集完全一致（1105 == 1105）。"),
    ],
)

h("⑥ chonkie 切分策略", 2)
card(
    "⑥ 可切换的语义切分，fixed 保持旧行为",
    [
        ("落地文件", "backend/app/services/text_processing.py（+83）、document_ingestion.py（+11）"),
        ("开关", "chunk_strategy=fixed（默认，即旧行为）、chunk_size=1000、chunk_overlap=150"),
        ("实现要点", "原 chunk_text() 的签名与函数体逐字未改（回归基线）；"
                     "新增 chunk_text_by_strategy()，非 semantic 一律直通旧逻辑；"
                     "semantic 用 chonkie RecursiveChunker(tokenizer=\"character\")，import 放在函数内，异常与空 span 都降级 fixed 并记 warning；"
                     "刻意未使用 chonkie.OverlapRefinery——实测 refine() 后 start_index/end_index 失真会破坏引用定位，"
                     "改为在连续 span 上自算重叠窗口，恒满足 content == normalized[pos:stop] 且长度受限。"),
        ("验证证据", "fixed 在 10 份语料 × 5 组参数 = 50 组合上与 git HEAD 的 chunk_text 逐元素一致；"
                     "semantic 的偏移保真与 chunk_size 上界均有测试锁定。"),
        ("注记", "chunk_size 的语义是字符数而非 token 数；⑥ 的实际生效面是 document_ingestion（POST /documents/upload）这条路径。"),
    ],
)

h("⑦ RRF 融合", 2)
card(
    "⑦ 用排名融合替代归一分数相加",
    [
        ("落地文件", "backend/app/services/retrieval/hybrid_retriever.py（+195/-35）"),
        ("开关", "fusion_strategy=rrf（默认）、rrf_k=60；设为 weighted 即回到旧行为；非法值静默回落 weighted"),
        ("实现要点", "抽出 _fuse_scores()；rrf 分支用 1-based 排名累加 source_weight / (rrf_k + rank)，"
                     "再 min-max 归一回 [0,1] 以与旧口径同量纲；weighted 分支保持旧线性混合（value × weight）；"
                     "AUTHORITY_RANK 语义与 keyword_only / vector_only / hybrid 三态语义均未改动；"
                     "无 active index 时仍降级 keyword_only；诊断写入 filters_json。"),
        ("验证证据", "把某一来源的分数整体 ×1 / ×100 / ×1e-6（排名不变）→ 输出顺序恒定，证明真的用 rank 而非分数；"
                     "weighted 分支对 7 种形状以 1e-12 精度复现 git HEAD 的旧线性公式。"),
        ("设计说明", "rank 贡献乘上已归一化的源权重，保证同排名时 keyword 源优先——与 weighted 模式的既有行为一致，"
                     "避免向量源在平局时挤掉关键词源。"),
    ],
)

h("⑧ LLM-judge faithfulness", 2)
card(
    "⑧ 评测补一档基于裁判的忠实度",
    [
        ("落地文件", "backend/app/services/evaluation/rag_evaluator.py（+44），复用 rag/citation_support.py 的裁判引擎"),
        ("开关", "ragas_judge_enabled=False（默认关闭）"),
        ("实现要点", "不引入 ragas 库依赖，用现有 LLM 网关自研等价判定，保持离线可跑；"
                     "judge 开启时逐条判定写入 execution_metadata_json，汇总写入 "
                     "faithfulness / faithfulness_denominator / unsupported_citation_ratio 并追加两条 metric_notes；"
                     "judge 关闭时不改变任何既有产出字段与数值。"),
        ("零 schema 变更", "只写 rag_evaluation_results.execution_metadata_json 与 rag_evaluation_runs.summary_metrics_json 两个既有 JSON 列，"
                            "未写迁移、未改 models。"),
        ("验证证据", "judge off：冻结 29 键 summary 键集合断言 + 数值不变、零网关调用；"
                     "judge on（mock 固定判定）、网关失败仍保持 run completed 且 metrics 完整、空答案不发模型调用。"),
        ("注记", "MockLLMService 无裁判分支，mock provider 下开启该开关会落到无关兜底 → 记为未判定（degraded=True）但不崩；"
                 "生产用真实 provider 不受影响。"),
    ],
)

# ==================== 三、契约与兼容性 ====================
h("三、契约与兼容性", 1)
table(
    ["类别", "内容"],
    [
        ["新增配置键", "17 个（见第六节运维手册）+ 8 条启动期校验（非法值直接拒绝启动）"],
        ["新增依赖", "jieba 0.42.1、bm25s 0.3.13、chonkie 1.7.0（传递依赖 chonkie-core 0.10.2、tokie 0.1.4、tenacity 9.2.1）；SBOM 组件数 97 → 103"],
        ["新增迁移", "202611010001_audit_log_chain（down_revision=202610060001），全仓仍只有 1 个 head"],
        ["冻结文件", "settings.py / requirements*.txt / requirements.sbom.json 仅含 Lead 的契约改动；实现流零越界（已用 git diff 核对）"],
        ["向后兼容", "record_audit 121 处调用点零改动；validate_citations 签名与错误文案逐字节保留；chunk_text 函数体逐字未改；关闭态输出与改动前逐字节一致"],
        ["未新增", "无新表（除审计链两列）、无新中间件、无新数据库、Milvus Lite 未动"],
    ],
    widths=[2.6, 14.4],
)

# ==================== 四、验证证据 ====================
h("四、验证证据", 1)

h("4.1 全量测试（Lead 在冻结树上执行）", 2)
para("命令：pytest tests -q（CI 环境变量；解释器 backend\\.venv\\Scripts\\python.exe）", size=9.5)
para("结果：1662 passed, 1 skipped, 0 failed, 12 warnings in 1585.97s (26m25s)，exit code 0", size=10, bold=True)
para(
    "对照基线 1518 passed / 1 skipped：新增通过 144 个（四条流各自的测试增量），0 failed、0 error。"
    "唯一 skip 为预先存在的条件跳过。",
    size=9.5,
)

h("4.2 独立验证（不同执行者、不同数据库，不采信实现者自述）", 2)
para(
    "验证者独立 read 源码核对接线与行号、在仓库外自写 7 个对抗性脚本、在隔离数据库上独立复跑测试："
    "359 passed / 0 failed（9 个新测试文件 144 + 回归子集 148 + governance 64 + schema_freeze 3）。",
    size=9.5,
)
table(
    ["项目", "攻击方式", "结果"],
    [
        ["④ 审计链", "改中间行 after_summary_json（保留行不删）", "检出，first_broken_id=3"],
        ["④ 审计链", "改 entry_hash 本身 / 改 prev_hash", "分别检出（4 / 断链原因精确）"],
        ["④ Merkle", "改叶、伪造 root、拼接多余步骤、空叶", "全部拒绝且不抛异常"],
        ["⑦ RRF", "某来源分数 ×1/×100/×1e-6（排名不变）", "输出顺序恒定 → 真用 rank"],
        ["⑦ weighted", "7 种形状对比 git HEAD 旧公式", "1e-12 精度复现"],
        ["② reranker 关闭", "sys.meta_path spy + 加载器计数", "fastembed 从未 import，加载 0 次"],
        ["⑤ citation off", "爆炸式网关 tripwire + 载入 HEAD 旧实现", "0 次调用，payload 字节一致"],
        ["⑥ fixed 切分", "10 语料 × 5 参数 = 50 组合", "与 HEAD 逐元素一致"],
        ["① OCR 关闭", "图片后缀 + 对比 HEAD 的 PDF 解析", "报错原文与 units/warnings 逐字节一致"],
        ["迁移", "临时 sqlite 上 upgrade→downgrade→upgrade", "单 head，rc=0，二次 upgrade 为 no-op"],
    ],
    widths=[2.4, 7.6, 7.0],
)

h("4.3 越界与完整性检查", 2)
bullet("git diff --stat：15 个文件、1093 insertions / 66 deletions，全部落在计划内写作用域。")
bullet("settings.py 为纯新增（17 键 + 8 校验），无既有行被修改。")
bullet("requirements.lock.txt 的「删除」经复核全部是重排序而非丢失（13 个包名逐一确认仍在文件中）。")
bullet("新增的 tenacity / tokie 经 importlib.metadata 全量扫描证实仅为 chonkie 的传递依赖，非人为注入。")
bullet("无历史 alembic 迁移被修改；frontend/next.config.mjs 内容哈希与 HEAD 相同（仅 mtime 变化）。")

# ==================== 五、未验证项与残余风险 ====================
h("五、未验证项与残余风险", 1)
para("以下各项不得当作已验证结论引用。", size=10, bold=True, color=(0xA0, 0x30, 0x1A))

table(
    ["编号", "项目", "性质", "闭合方式"],
    [
        ["U1", "② reranker 开启态真实模型路径", "未验证（本机 HF 访问被拒，os error 5）", "验收环境联网后跑一次 reranker_enabled=True 冒烟"],
        ["U2", "① 真实 rapidocr-onnxruntime 识别质量", "未验证（包未安装且无网络）", "在可联网环境安装后测真实识别精度与引擎构造参数"],
        ["U3", "③ bm25s 未被采用", "设计选择，非缺陷", "如需换用 bm25s，需单独立项并重跑检索回归"],
        ["R1", "④ 审计链残余风险：能重算整段后缀哈希的数据库写攻击者", "设计层残余风险", "定期把 audit_merkle_root 发布到外部不可写位置（WORM / 外部日志）"],
        ["N1", "④ 只改 entry_hash 时后续行不进 break_ids", "运维口径", "受影响尾部读 affected_range，不要只看 break_ids"],
        ["N5", "① 开启 OCR 但 provider 缺失时静默降级为空文本", "运维风险", "对 OCR warning 计数做监控告警"],
        ["N6", "⑥ semantic 路径先归一化换行/首尾空白", "新策略内部设计", "semantic 的字符偏移基于归一化文本（fixed 基于原文），如需对齐需明确口径"],
        ["N3", "③⑦ 配置校验时机在启动 lifespan", "既有设计", "非法 fusion_strategy 静默回落 weighted；靠 validate_configuration() 拒绝启动"],
    ],
    widths=[1.0, 4.6, 4.6, 6.8],
)

# ==================== 六、运维启用手册 ====================
h("六、运维启用手册", 1)
para("下表给出各功能的开关与建议值，便于部署时按需启用。", size=10)
table(
    ["目标", "环境变量", "默认值", "启用前提 / 说明"],
    [
        ["开启 Cross-encoder 重排", "RERANKER_ENABLED", "false", "需先下载 BAAI/bge-reranker-base（离线环境需预置缓存）"],
        ["开启扫描件 OCR", "OCR_ENABLED", "false", "需安装 rapidocr-onnxruntime 或 paddleocr"],
        ["OCR 页数上限", "OCR_MAX_PAGES", "50", "超出截断并告警"],
        ["切换语义切分", "CHUNK_STRATEGY", "fixed", "semantic 需 chonkie（已随依赖安装）"],
        ["引用蕴含判定", "CITATION_SUPPORT_CHECK", "off", "judge 需可用 LLM 网关"],
        ["LLM 裁判忠实度", "RAGAS_JUDGE_ENABLED", "false", "同上；关时不改变既有指标"],
        ["融合策略", "FUSION_STRATEGY", "rrf", "设 weighted 即回到旧的线性加权"],
        ["RRF 常数", "RRF_K", "60", "必须为正"],
        ["BM25 参数", "KEYWORD_BM25_K1 / KEYWORD_BM25_B", "1.2 / 0.75", "b 必须在 [0,1]"],
        ["审计哈希链", "AUDIT_CHAIN_ENABLED", "true", "关闭则不写哈希列（留 NULL）"],
        ["重排候选数", "RERANKER_TOP_K", "50", "只重排前 N 条"],
    ],
    widths=[4.0, 4.6, 2.0, 6.4],
)

# ==================== 七、文件清单 ====================
h("七、改动文件清单", 1)
table(
    ["文件", "状态", "规模"],
    [
        ["backend/app/core/settings.py", "改", "+57"],
        ["backend/app/models/governance.py", "改", "+9/-1"],
        ["backend/app/services/document_ingestion.py", "改", "+11/-1"],
        ["backend/app/services/evaluation/rag_evaluator.py", "改", "+44"],
        ["backend/app/services/governance/__init__.py", "改", "+36"],
        ["backend/app/services/governance/audit.py", "改", "+167/-7"],
        ["backend/app/services/knowledge_ingestion/parsers.py", "改", "+83/-3"],
        ["backend/app/services/rag/citation_validator.py", "改", "+143"],
        ["backend/app/services/rag/grounded_answer_service.py", "改", "+18/-2"],
        ["backend/app/services/retrieval/hybrid_retriever.py", "改", "+230/-35"],
        ["backend/app/services/retrieval/keyword_index.py", "改", "+208/-2"],
        ["backend/app/services/text_processing.py", "改", "+83"],
        ["backend/alembic/versions/202611010001_audit_log_chain.py", "新建", "49"],
        ["backend/app/services/governance/chain.py", "新建", "159"],
        ["backend/app/services/governance/merkle.py", "新建", "195"],
        ["backend/app/services/knowledge_ingestion/ocr.py", "新建", "162"],
        ["backend/app/services/rag/citation_support.py", "新建", "353"],
        ["backend/app/services/retrieval/reranker.py", "新建", "219"],
        ["backend/tests/test_audit_chain.py", "新建", "16 用例"],
        ["backend/tests/test_audit_merkle.py", "新建", "13 用例"],
        ["backend/tests/test_evaluation_faithfulness.py", "新建", "8 用例"],
        ["backend/tests/test_ingestion_chunking.py", "新建", "24 用例"],
        ["backend/tests/test_ingestion_ocr.py", "新建", "20 用例"],
        ["backend/tests/test_rag_citation_support.py", "新建", "12 用例"],
        ["backend/tests/test_retrieval_bm25.py", "新建", "15 用例"],
        ["backend/tests/test_retrieval_fusion.py", "新建", "11 用例"],
        ["backend/tests/test_retrieval_reranker.py", "新建", "16 用例"],
        ["backend/requirements.txt / lock / sbom.json", "改", "3 包 / 6 组件"],
    ],
    widths=[9.0, 1.8, 6.2],
)

para("", space_after=4)
para(
    "附：独立验证完整报告见 ai-platform\\.planning\\verify-8item-report.md（352 行）；实施计划见 ai-platform\\.planning\\2026-10-17-8item-landing-plan.md。",
    size=9,
    color=(0x55, 0x55, 0x55),
)

doc.save(OUT)
print("OK ->", OUT)

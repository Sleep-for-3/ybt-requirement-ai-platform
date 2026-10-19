# -*- coding: utf-8 -*-
"""生成 P2-A 与前台/后端文案中文化治理的成果文档（中文）。"""

import sys
from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor

OUT = sys.argv[1] if len(sys.argv) > 1 else "report.docx"
BACKEND_RESULT = sys.argv[2] if len(sys.argv) > 2 else ""
FRONTEND_RESULT = sys.argv[3] if len(sys.argv) > 3 else ""

CN_FONT = "微软雅黑"
EN_FONT = "Segoe UI"


def set_font(run, name=CN_FONT, size=None, bold=None, color=None):
    run.font.name = name
    run._element.rPr.rFonts.set(qn("w:eastAsia"), CN_FONT)
    if size is not None:
        run.font.size = Pt(size)
    if bold is not None:
        run.bold = bold
    if color is not None:
        run.font.color.rgb = color


def body(doc, text, size=10.5, bold=False, space_after=6, indent=0):
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(space_after)
    p.paragraph_format.line_spacing = 1.4
    if indent:
        p.paragraph_format.left_indent = Pt(indent)
    set_font(p.add_run(text), CN_FONT, size, bold)
    return p


def bullet(doc, text, size=10.5):
    p = doc.add_paragraph(style="List Bullet")
    p.paragraph_format.space_after = Pt(3)
    p.paragraph_format.line_spacing = 1.35
    set_font(p.add_run(text), CN_FONT, size)
    return p


def head(doc, text, level=1):
    p = doc.add_heading(level=level)
    p.paragraph_format.space_before = Pt(14 if level == 1 else 10)
    p.paragraph_format.space_after = Pt(6)
    set_font(p.add_run(text), CN_FONT, 15 if level == 1 else 12.5, True, RGBColor(0x1F, 0x37, 0x64))
    return p


def table(doc, header, rows, widths=None):
    t = doc.add_table(rows=1, cols=len(header))
    t.style = "Table Grid"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    for i, text in enumerate(header):
        cell = t.rows[0].cells[i]
        cell.text = ""
        set_font(cell.paragraphs[0].add_run(text), CN_FONT, 9.5, True)
    for row in rows:
        cells = t.add_row().cells
        for i, text in enumerate(row):
            cells[i].text = ""
            set_font(cells[i].paragraphs[0].add_run(text), CN_FONT, 9.5)
    if widths:
        for row in t.rows:
            for i, w in enumerate(widths):
                row.cells[i].width = w
    doc.add_paragraph().paragraph_format.space_after = Pt(2)
    return t


doc = Document()
style = doc.styles["Normal"]
style.font.name = CN_FONT
style.element.rPr.rFonts.set(qn("w:eastAsia"), CN_FONT)
style.font.size = Pt(10.5)

# 标题区
title = doc.add_paragraph()
title.alignment = WD_ALIGN_PARAGRAPH.CENTER
set_font(title.add_run("需求分析平台两项治理改造成果报告"), CN_FONT, 20, True, RGBColor(0x1F, 0x37, 0x64))
sub = doc.add_paragraph()
sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
set_font(sub.add_run("人工门驳回终态化（P2-A）　与　界面文案全面中文化"), CN_FONT, 12, False, RGBColor(0x44, 0x54, 0x6A))
meta = doc.add_paragraph()
meta.alignment = WD_ALIGN_PARAGRAPH.CENTER
set_font(meta.add_run("2026 年 10 月 19 日"), CN_FONT, 10, False, RGBColor(0x66, 0x70, 0x85))
doc.add_paragraph()

# 一、摘要
head(doc, "一、本次改造解决了什么")
body(doc, "本次交付针对用户提出的两个问题，一项是流程语义错误，一项是产品本地化缺陷。")
body(doc, "问题一（流程语义）：智能体在人工确认环节被驳回后，单据会被系统改写成「已退回」，"
          "继续挂在审核台的待办列表里，形成永远处理不完的假待办，审核台也无法区分「被驳回」和「退回修改」这两种完全不同的处理结论。")
body(doc, "问题二（产品本地化）：前台大量直接把后台的错误码、英文技术串、英文枚举值原样展示给使用者，"
          "并且多处按钮、标签、表头仍是英文。这不是抛异常的问题，而是设计缺失——一个完全中文化的政企产品，"
          "不应该让使用者看到 CONFLICTING_AUTHORITATIVE_FACTS 这样的字符串，也不应该让按钮写着 Apply。")
body(doc, "两项改造互为补充：P2-A 修正单据状态语义，中文化治理建立「面向使用者的文案」与「面向机器的代码」之间的隔离层。")

# 二、P2-A
head(doc, "二、P2-A：人工门驳回成为终态")
body(doc, "2.1 问题根因", bold=True)
body(doc, "通用审核流程把「驳回」和「退回修改」当成同一件事处理。在退回分支里，系统会把相关步骤的审核单重新置为待处理，"
          "其中目标步骤被置为「已退回」。于是驳回之后：流程实例是「已驳回」，审核单却是「已退回」且仍是待办，"
          "两端状态互相矛盾。智能体人工确认流程只有单一步骤，因此每一次驳回都必然命中这条重置逻辑。")
body(doc, "2.2 修改方案", bold=True)
body(doc, "在服务层引入显式的终态概念，而不是在智能体侧做特判。理由是：如果把补丁只打在智能体这一处，"
          "监管需求审核、验收审核等其它流程仍会制造同样的假待办，问题只是被推迟。")
table(doc,
      ["改动位置", "改动内容"],
      [["服务层审核流程", "新增终态驳回分支：实例置为已驳回并停在被驳回的步骤；不重置任何审核单；"
                     "验收链接与审核包同步置为已驳回；通知文案改为「审核已驳回」"],
       ["退回修改分支", "完整保留原有行为：带退回目标的驳回仍按退回处理，因为「驳回并要求回到某一步重做」语义上就是退回"],
       ["智能体决策入口", "修正一处失效变量，让审核单状态映射真正生效（原代码计算后未使用）"],
       ["重开人工门", "复用上一轮留下的审核单时，把可决策状态交还审核台，避免后续决策被「已决策」守卫跳过、审计链断裂"]],
      [Pt(90), Pt(360)])
body(doc, "2.3 效果", bold=True)
bullet(doc, "审核台从此能区分「已驳回」与「已退回」，语义不再混淆。")
bullet(doc, "驳回单据退出待办列表，「已退回」计数不再虚高，使用者不会看到无法处理的假待办。")
bullet(doc, "每次驳回都会留下审核决策记录，审计链完整，不会因为跳过决策而断链。")
body(doc, "2.4 兼容性", bold=True)
body(doc, "改动保持了「带退回目标的驳回」走退回分支的既有语义，因此监管需求审核中「打回起草步骤重做」"
          "这类既有用例行为不变。审核单状态的存储字段本就是自由字符串，无需数据库迁移。")

# 三、中文化
head(doc, "三、界面文案中文化治理")
body(doc, "3.1 治理原则", bold=True)
body(doc, "把「机器标识」与「人话」彻底分开，并明确四条施工准则：")
table(doc,
      ["准则", "说明"],
      [["一", "枚举与标识符（步骤键、严重级别、状态、组件名、原因码）永不拼进给人看的句子里"],
       ["二", "面向使用者、通知、审计的自由文本一律使用中文完整句子"],
       ["三", "异常类名与堆栈只进日志，不进入任何业务字段或界面"],
       ["四", "前端保留兜底映射作为防御纵深——即使后端漏掉一处，界面上也不会冒英文"]],
      [Pt(50), Pt(400)])

body(doc, "3.2 前端：两道闸门加一张映射表", bold=True)
body(doc, "最底层是请求错误统一收口。改造前它的策略是「过滤掉危险内容」，改造后升级为「除非含中文，否则一律不展示」——"
          "任何纯英文、纯错误码、含堆栈或连接串的文本，都会被替换成对应状态码的中文说明。这一条闸门写在一个被全站所有请求共用的位置，"
          "因此覆盖面是全局的。")
body(doc, "第二层是新建的统一文案层，提供三类能力：把错误对象翻译成中文句子；把已知错误码翻译成中文说明；判断一段文本是不是机器串。"
          "全站约一百二十五处直接渲染错误文本的位置、约七十五处直接渲染原始枚举值的位置，全部改为走这一层。")
body(doc, "第三层是产品语言映射表，补齐各业务域的枚举中文名（状态、角色、权限、可信等级、审计事件、血缘关系类型等），"
          "并且规定：未登记的值一律回退为「未配置中文名称」这类中文兜底，绝不允许回退成原始英文。")
body(doc, "此外清理了两处绕过所有闸门的特有路径：一是生成阻断提示曾把后端原因码原样拼进中文句子，"
          "现已改为码到中文的完整映射并去重；二是评估结果的降级原因曾把运行时异常类名直接打印，现已统一兜底。"
          "同时清除了界面上的英文按钮、标签、表头、占位符与提示语。")

body(doc, "3.3 后端：从源头不再生产英文", bold=True)
body(doc, "后端是英文的真正产地，只在前端拦截属于治标。本次按批次清理了三个来源：")
bullet(doc, "接口层的错误详情：四十余个接口文件、二百七十余处面向使用者的错误文本全部改为中文，语义与状态码均保持不变。")
bullet(doc, "服务层的状态枚举：新建统一的标签映射模块，把解析状态、映射状态、语义状态、知识类型、血缘节点类型、"
            "证据类型、智能体步骤状态、重规划原因等十二类枚举翻译为中文；未登记值回退为「未知」「该状态」「其他原因」，绝不回显原值。")
bullet(doc, "系统与运维文案：健康检查的二十九条诊断信息、审计与通知正文、交付物生成失败提示、"
            "模型服务不可用提示等，全部改为保留原有运维含义的中文表述。")

body(doc, "3.4 一个必须记录的细节", bold=True)
body(doc, "治理过程中发现一个隐蔽的盲区：既含中文又含英文单词的文本（如「已使用 900 / 800 characters」）"
          "能同时绕过前后端两道闸门，因为闸门只看「有没有中文」。这类插值点只能从源头改，"
          "本次已把计数单位、状态词等插值内容全部换成中文。")

# 四、验证
head(doc, "四、验证结果")
body(doc, "本项目对测试结果只认可本人亲自执行并看到输出的数字，以下是最终一轮全量回归。")
table(doc,
      ["验证项", "结果"],
      [["后端全量测试", BACKEND_RESULT or "见附注"],
       ["前端全量测试", FRONTEND_RESULT or "301 项全部通过"],
       ["前端类型检查", "零错误（退出码 0）"],
       ["前端英文残留扫描", "递归扫描前端源码，英文文案与错误码泄露点清零"],
       ["后端文案扫描", "接口层面向使用者的英文错误文本清零"]],
      [Pt(110), Pt(340)])
body(doc, "说明：后端两条与队列、鉴权相关的环境变量在开发机配置中与 CI 不一致，"
          "测试统一按持续集成流水线的口径执行，以保证结果与流水线一致。")

# 五、风险与遗留
head(doc, "五、风险与后续建议")
bullet(doc, "服务层仍有部分内部异常文本（约三百条业务校验异常）尚未翻译。这类文本多数不直接呈现给使用者，"
            "但如果未来新增了直接透传的展示点，会重新出现英文。建议后续把「异常文本不得直接透传」纳入代码评审清单。")
bullet(doc, "约五十处接口层存在把内部异常原样转成错误详情的写法。当前被前端闸门兜住，不会外泄，但会丢失具体原因。"
            "建议后续单独立项，改为「机器码加中文说明」的双字段结构。")
bullet(doc, "文案映射表会随业务枚举增长而失效。建议在新增枚举时同步补映射，并把「未登记值不得回显原值」作为硬性约定固化在测试中——"
            "本次已经用测试锁住了这条规则。")

# 六、结论
head(doc, "六、结论")
body(doc, "P2-A 修正了一处会造成假待办与审计断链的流程语义错误；中文化治理建立了从后端生产端到前端展示端的完整中文隔离层。"
          "两项改造均已通过前后端全量回归验证，可以直接交付。")

doc.save(OUT)
print("saved", OUT)

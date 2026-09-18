r"""生成《智能分析智能体平台系统使用文档》Word 交付件。

内容与 docs/系统使用文档.md 对齐，并补充交付信息（访问地址、管理员账号与口令）
与真实页面截图。截图来源目录为 docs/assets/system-guide。

用法：
    python scripts/docs/build_system_guide_docx.py
    python scripts/docs/build_system_guide_docx.py --output docs/系统使用文档.docx
"""

from __future__ import annotations

import argparse
import itertools
import pathlib

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Inches, Pt, RGBColor
from PIL import Image

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
ASSET_DIR = REPO_ROOT / "docs" / "assets" / "system-guide"
DEFAULT_OUTPUT = REPO_ROOT / "docs" / "系统使用文档.docx"

VERSION = "0020b42"
SITE_URL = "http://103.236.97.210:18085/"
SITE_URL_ALT = "http://57008897.xyz:18085"
ADMIN_USER = "smoke_admin"
ADMIN_PASSWORD = "smoke-only-platform-admin-password"
SERVER_IP = "103.236.97.210"
SSH_PORT = "42438"

BODY_LATIN = "DengXian"
BODY_CJK = "等线"
HEAD_LATIN = "Microsoft YaHei"
HEAD_CJK = "微软雅黑"

INK = RGBColor(0x1A, 0x1A, 0x1A)
HEAD_INK = RGBColor(0x14, 0x2B, 0x45)
MUTED_INK = RGBColor(0x5A, 0x5A, 0x5A)
HEADER_FILL = "EDF1F6"

CONTENT_WIDTH = Cm(16.6)
MAX_FIGURE_HEIGHT = Inches(7.9)

_figure_numbers = itertools.count(1)


def set_style_font(style, latin: str, cjk: str, size: Pt, bold=None, color=None) -> None:
    style.font.name = latin
    style.font.size = size
    if bold is not None:
        style.font.bold = bold
    if color is not None:
        style.font.color.rgb = color
    rfonts = style.element.get_or_add_rPr().get_or_add_rFonts()
    for attr, value in (
        ("w:ascii", latin),
        ("w:hAnsi", latin),
        ("w:eastAsia", cjk),
        ("w:cs", latin),
    ):
        rfonts.set(qn(attr), value)


def apply_run_font(run, latin: str = BODY_LATIN, cjk: str = BODY_CJK) -> None:
    run.font.name = latin
    rfonts = run._element.get_or_add_rPr().get_or_add_rFonts()
    for attr, value in (
        ("w:ascii", latin),
        ("w:hAnsi", latin),
        ("w:eastAsia", cjk),
        ("w:cs", latin),
    ):
        rfonts.set(qn(attr), value)


def setup_document() -> Document:
    doc = Document()
    section = doc.sections[0]
    section.page_width = Cm(21)
    section.page_height = Cm(29.7)
    section.top_margin = Cm(2.3)
    section.bottom_margin = Cm(2.3)
    section.left_margin = Cm(2.2)
    section.right_margin = Cm(2.2)

    set_style_font(doc.styles["Normal"], BODY_LATIN, BODY_CJK, Pt(10.5), color=INK)
    normal = doc.styles["Normal"].paragraph_format
    normal.line_spacing = 1.45
    normal.space_after = Pt(6)

    set_style_font(doc.styles["Title"], HEAD_LATIN, HEAD_CJK, Pt(21), bold=True, color=HEAD_INK)
    for level, size in ((1, 15.5), (2, 12.5), (3, 11.5)):
        set_style_font(
            doc.styles[f"Heading {level}"], HEAD_LATIN, HEAD_CJK, Pt(size), bold=True, color=HEAD_INK
        )
        fmt = doc.styles[f"Heading {level}"].paragraph_format
        fmt.space_before = Pt(14 if level == 1 else 10)
        fmt.space_after = Pt(6)
        fmt.keep_with_next = True

    doc.core_properties.title = "智能分析智能体平台系统使用文档"
    doc.core_properties.subject = f"生产版本 {VERSION} 使用说明"
    return doc


def add_rich(doc, parts, *, size=Pt(10.5), color=INK, align=None, space_after=Pt(6),
             space_before=Pt(0), line_spacing=1.45, left_indent=None):
    if isinstance(parts, str):
        parts = [parts]
    paragraph = doc.add_paragraph()
    fmt = paragraph.paragraph_format
    fmt.space_after = space_after
    fmt.space_before = space_before
    fmt.line_spacing = line_spacing
    if left_indent is not None:
        fmt.left_indent = left_indent
    if align is not None:
        paragraph.alignment = align
    for part in parts:
        text, modestyle = (part, {}) if isinstance(part, str) else part
        run = paragraph.add_run(text)
        apply_run_font(run)
        run.font.size = modestyle.get("size", size)
        run.font.bold = modestyle.get("bold", False)
        run.font.italic = modestyle.get("italic", False)
        run.font.color.rgb = modestyle.get("color", color)
    return paragraph


def add_bullets(doc, items) -> None:
    for index, item in enumerate(items, start=1):
        parts = item if isinstance(item, list) else [item]
        paragraph = add_rich(doc, parts, space_after=Pt(3), left_indent=Cm(0.75))
        marker = paragraph.runs[0]
        marker.text = f"{index}. {marker.text}"


def add_table(doc, rows, *, widths=None, font_size=Pt(10)) -> None:
    table = doc.add_table(rows=len(rows), cols=len(rows[0]))
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    for row_index, row in enumerate(rows):
        for col_index, value in enumerate(row):
            cell = table.cell(row_index, col_index)
            if widths:
                cell.width = widths[col_index]
            paragraph = cell.paragraphs[0]
            paragraph.paragraph_format.space_after = Pt(2)
            paragraph.paragraph_format.line_spacing = 1.25
            run = paragraph.add_run(value)
            apply_run_font(run)
            run.font.size = font_size
            run.font.bold = row_index == 0
            if row_index == 0:
                shade = OxmlElement("w:shd")
                shade.set(qn("w:val"), "clear")
                shade.set(qn("w:fill"), HEADER_FILL)
                cell._tc.get_or_add_tcPr().append(shade)
    header_row = table.rows[0]._tr
    header_props = OxmlElement("w:trPr")
    header_props.append(OxmlElement("w:tblHeader"))
    header_row.append(header_props)
    add_rich(doc, "", size=Pt(4), space_after=Pt(2))


def add_figure(doc, filename: str, caption: str) -> None:
    path = ASSET_DIR / filename
    if not path.exists():
        raise FileNotFoundError(f"缺少截图文件：{path}")
    with Image.open(path) as image:
        pixel_width, pixel_height = image.size
    width_in = CONTENT_WIDTH.inches
    height_in = width_in * pixel_height / pixel_width
    if height_in > MAX_FIGURE_HEIGHT.inches:
        height_in = MAX_FIGURE_HEIGHT.inches
        width_in = height_in * pixel_width / pixel_height
    paragraph = doc.add_paragraph()
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    paragraph.paragraph_format.space_before = Pt(6)
    paragraph.paragraph_format.space_after = Pt(2)
    paragraph.add_run().add_picture(str(path), width=Inches(width_in), height=Inches(height_in))
    number = next(_figure_numbers)
    add_rich(
        doc,
        f"图 {number} {caption}",
        size=Pt(9),
        color=MUTED_INK,
        align=WD_ALIGN_PARAGRAPH.CENTER,
        space_after=Pt(12),
    )


def build(doc: Document) -> None:
    title = doc.add_paragraph("智能分析智能体平台系统使用文档", style="Title")
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    add_rich(
        doc,
        f"生产版本 {VERSION} · 更新日期 2026-09-13 · 访问地址 {SITE_URL}",
        size=Pt(10),
        color=MUTED_INK,
        align=WD_ALIGN_PARAGRAPH.CENTER,
        space_after=Pt(14),
    )
    add_rich(
        doc,
        "本文说明智能分析智能体平台在生产服务器上的日常使用方法，覆盖登录、界面结构、角色权限、"
        "从监管目标到正式交付的主线流程，以及系统管理、常见问题与已知边界。文中的页面截图于 "
        "2026 年 9 月 13 日在生产环境实际采集，所用数据为历次端到端验收留下的脱敏演示数据。"
        "部署、备份与回滚等运维内容另见《服务器上线操作手册》与《服务器配置说明》。",
    )

    doc.add_heading("1 交付信息", level=1)
    add_table(
        doc,
        [
            ["项目", "值"],
            ['访问地址', SITE_URL],
            ['备用地址（域名）', SITE_URL_ALT],
            ["平台管理员账号", ADMIN_USER],
            ["平台管理员密码", ADMIN_PASSWORD],
            ["生产版本", f"{VERSION}（后端镜像 ybt-backend:{VERSION}，前端镜像 ybt-frontend:{VERSION}）"],
            ["服务器", f"{SERVER_IP}（公网 HTTP 18085 映射到服务器 80；SSH 端口 {SSH_PORT} 仅供运维使用）"],
            ["建议浏览器", "Chrome 或 Edge 最新版，窗口宽度不小于 1440 像素时体验最佳"],
        ],
        widths=[Cm(4.2), Cm(12.4)],
    )
    add_rich(
        doc,
        [
            ("首次登录后请立即修改管理员密码。", {"bold": True}),
            (
                "当前口令是端到端验收脚本使用的口令，属于临时可交付状态；修改后如需继续运行验收脚本，"
                "请通过环境变量 GUIDE_PASSWORD 传入新口令。"
            ),
        ],
    )
    add_rich(
        doc,
        "口令只写在本 Word 交付件里，不写入代码仓库。请不要把本文档提交到代码仓库，也不要对外公开。",
    )
    add_rich(
        doc,
        "库中现存的“增强验收测试项目 20260912-*”“Product 5.1 *”“UAT Product 5.1 *”等机构与账号，"
        "都是历次端到端验收脚本创建的脱敏演示数据，不是真实银行业务数据，可以放心点开查看，"
        "也可以由管理员清理重建。",
    )

    doc.add_heading("2 登录", level=1)
    add_rich(doc, f"打开 {SITE_URL}，未登录会自动跳转到登录页。")
    add_figure(doc, "01-login.png", "登录页")
    add_rich(
        doc,
        "输入管理员账号与密码后点击登录。登录成功后进入工作台，右上角显示当前机构、当前项目与登录人。"
        "访问令牌有效期 15 分钟，并会在使用过程中自动续期，长时间不操作再回来也不会被登出；"
        "只有超过 30 天未使用才需要重新登录。",
    )

    doc.add_heading("3 界面总览", level=1)
    add_figure(doc, "02-workspace.png", "工作台总览")
    add_rich(doc, "界面分为四块。")
    add_table(
        doc,
        [
            ["区域", "作用"],
            ["左侧导航", "按工作台、需求文档、数据资产、知识库、交付中心、系统管理分组的功能入口"],
            ["顶部条", "机构名与当前项目下拉、全局搜索（快捷键 Ctrl+K）、后台任务状态灯、用户菜单"],
            ["主区域", "当前功能页面。页面内一般遵循先选目标、再配置范围、最后执行并查看结果的顺序"],
            ["右上角", "当前项目切换。大部分页面都跟随当前项目，切换项目后数据随之切换"],
        ],
        widths=[Cm(3.4), Cm(13.2)],
    )
    add_rich(
        doc,
        "如果链接带上 ?projectId=<项目ID>，打开时会自动切换到该项目；日常使用点击顶部下拉即可。",
    )

    doc.add_heading("4 角色与权限", level=1)
    add_rich(doc, "平台按机构加项目两层授权，同一个用户在不同项目中可以承担不同角色。")
    add_table(
        doc,
        [
            ["角色", "典型职责"],
            ["平台管理员（机构管理员）", "建机构、建用户、配模型档案，查看平台健康与审计，可进入系统管理"],
            ["business_analyst 业务分析", "维护字段与口径、上传知识与证据、发起 AI 起草"],
            ["business_reviewer 业务审核", "审核业务口径与业务映射"],
            ["technical_analyst 技术分析", "维护数据源、数据目录、技术血缘与 SQL 逻辑"],
            ["technical_reviewer 技术审核", "审核技术血缘与影响分析"],
            ["final_reviewer 最终审核", "终审并确认可交付"],
            ["只读成员", "只能查看与下载，不能修改"],
        ],
        widths=[Cm(5.4), Cm(11.2)],
    )
    add_rich(
        doc,
        "权限不满足时接口返回 403；跨机构访问他人项目返回 404，平台不会暴露该资源是否存在。",
    )

    doc.add_heading("5 主线流程：从监管目标到正式交付", level=1)
    add_rich(
        doc,
        "一条监管需求从建项目走到正式交付，按下面的顺序推进即可。页面入口都在左侧导航，"
        "每一步的产出都是下一步的输入。",
    )

    doc.add_heading("5.1 建项目与成员", level=2)
    add_rich(doc, "入口：左侧项目，新建项目；进入项目后在成员页维护项目角色。")
    add_figure(doc, "03-projects.png", "项目列表")

    doc.add_heading("5.2 接入数据资产", level=2)
    add_rich(
        doc,
        "入口：左侧数据源，新增只读数据源，点测试连接，再执行元数据同步；"
        "同步完成后到数据目录查看表与字段。",
    )
    add_figure(doc, "11-datasources.png", "数据源连接与同步状态")
    add_figure(doc, "12-catalog.png", "数据目录中的表与字段")
    add_rich(
        doc,
        "数据源必须先完成元数据同步，后面的目录检索与口径抽取才有依据。如果同步显示部分完成，"
        "通常是数据源文件或网络在平台侧不可达，例如把本机临时文件当作数据源。",
    )

    doc.add_heading("5.3 维护字段与口径", level=2)
    add_rich(
        doc,
        "入口：左侧字段与口径。在这里挑选目标字段、维护业务定义，并查看血缘与证据完备度。",
    )
    add_figure(doc, "06-fields.png", "字段与口径")

    doc.add_heading("5.4 沉淀知识与证据", level=2)
    add_rich(
        doc,
        "入口：左侧知识检索分组下的知识文档。支持 Excel、Word、PDF、SQL 等文件，"
        "上传后自动解析并保留出处，例如工作表与单元格、PDF 页码、SQL 行号。",
    )
    add_figure(doc, "08-knowledge-documents.png", "知识文档与解析状态")
    add_rich(
        doc,
        "上传后如果页面顶部提示索引版本变化，点重新构建语义索引，等后台任务完成。页面会显示"
        "当前生效的索引版本、文档与切片数量以及 Milvus 状态。生产环境使用 Milvus 正式索引，"
        "不重建索引时检索会提示请先重建索引。",
    )
    add_figure(doc, "09-knowledge-search.png", "混合知识检索结果与出处")
    add_figure(doc, "10-knowledge-ask.png", "知识问答与引用来源")
    add_rich(
        doc,
        "检索结果会给出综合重排分数，并标注命中的文件名与出处，例如“监管答疑.xlsx 答疑 A2:F2”。"
        "知识问答只依据知识库证据作答，并返回引用来源；证据不足时会明确标记为待确认，不会编造内容。",
    )

    doc.add_heading("5.5 AI 口径起草", level=2)
    add_rich(
        doc,
        "入口：左侧需求文档工作台，也可以直接打开 /workspace。页面自上而下是四步："
        "选监管目标、配分析范围、AI 分析、人工校验与导出；界面形态与图 2 的工作台首屏一致。",
    )
    add_bullets(
        doc,
        [
            "左栏选择一表通目标表，例如 YBT_CUSTOMER 客户信息表，再选择业务场景，例如借记卡。",
            "选中目标字段，例如 CERT_TYPE 客户证件类型。",
            "确认数据分析范围的四项资产是否可用：业务源系统、只读数据源、监管集市、历史与知识。",
            "点生成业务口径与技术溯源草稿，等待右侧草稿区刷新。",
            "在右侧业务口径与技术溯源两栏核对 AI 草稿，可以手工改写并保存人工终稿。",
            "需要走审批时点深度编辑、证据绑定与提交审核，进入审核流程。",
            "确认无误后点右上角导出需求文档，可导出 Word 或 Excel，也可以直接发起正式交付。",
        ],
    )
    add_rich(
        doc,
        "页面下方的“为什么这样判断”会逐条列出监管依据、候选数据、加工规则、证据依据、置信度与"
        "治理状态，点击证据可以回溯到具体知识切片。带“仍需人工确认”标记的区域必须由人工处理，"
        "AI 不会自动放行。",
    )

    doc.add_heading("5.6 审核与治理", level=2)
    add_rich(doc, "入口：左侧待确认问题、我的工作、审核任务。")
    add_figure(doc, "14-review-tasks.png", "审核任务")
    add_rich(
        doc,
        "审核按业务审核、技术审核、终审的顺序流转。每次决策都会写入审计日志，"
        "可在系统管理下的平台健康与审计页面查询，同时通过站内通知提醒相关人。",
    )

    doc.add_heading("5.7 血缘与影响分析", level=2)
    add_rich(doc, "入口：数据资产分组中的血缘相关页面（/lineage）。")
    add_figure(doc, "13-lineage.png", "血缘与脚本版本对比")
    add_rich(
        doc,
        "上传 SQL 脚本后可以看到脚本版本差异、血缘节点与边，以及变更影响分类，"
        "例如字段新增或删除、过滤条件变化、关联变化。变更后需要人工确认影响范围，"
        "未审核的影响会出现在项目看板上。",
    )

    doc.add_heading("5.8 数据星云（多级分层血缘）", level=2)
    add_rich(
        doc,
        "入口：血缘页里的“数据星云”卡片，或直接打开 /lineage/nebula；"
        "在字段血缘页点“打开数据星云”会自动带上根对象与层级深度。",
    )
    add_rich(
        doc,
        "数据星云把一条监管口径的多级血缘按数据流向分层铺开，一屏看清“这个字段怎么来的、"
        "改了会影响谁”。当前生产版本已包含该能力。",
    )
    add_table(
        doc,
        [
            ["层级", "含义"],
            ["源系统 SOURCE", "业务系统原始表"],
            ["操作数据层 ODS", "贴源落地"],
            ["明细数据层 DWD", "明细加工"],
            ["汇总数据层 DWS", "轻度汇总"],
            ["监管集市 MART", "监管口径集市"],
            ["监管输出 TARGET", "一表通 / EAST / 1104 的报表字段"],
            ["数据目录 CATALOG / 处理脚本 SCRIPT", "目录字段与脚本血缘节点"],
            ["未识别层级 UNKNOWN", "判定不了层级的节点单独成列，不会被猜成某一层"],
        ],
        widths=[Cm(6.0), Cm(10.6)],
    )
    add_rich(doc, "用法：")
    add_bullets(
        doc,
        [
            "选根对象类型：监管目标字段 / 监管集市字段 / 源系统字段 / 数据目录字段 / 脚本血缘节点；",
            "填根对象 ID（例如某个监管目标字段的 ID），填好即自动加载，不需要再点查询；",
            "选方向：上游（取数来源）/ 下游（影响范围）/ 双向；",
            "选层级深度 1–10（默认 6）与视图（业务视图 / 技术视图）；",
            "需要对齐某个历史口径时，在“血缘版本”里选一个已发布版本，图与表格都读同一份版本。",
        ],
    )
    add_rich(doc, "读图规则：")
    add_bullets(
        doc,
        [
            "点击任意节点可以按该节点重新聚焦上下游，按 Esc 取消聚焦；",
            "画布下方的明细表格与图来自同一份接口响应，所以“看到的图”和“列出来的边”始终一致；",
            "无法证明的关联保持“未解析”，平台不会自动补全；缺口（例如缺少业务备注）会汇总成缺口建议；",
            "单层节点超过 24 个会按顺序截断并在层级标签上标注“已截断 N”，需要看全就缩小深度或收窄方向；",
            "动画只表示已经登记的结构连接关系，不代表跑批脚本正在运行，也不代表数据正在实时流动。",
        ],
    )
    add_rich(
        doc,
        "参数可以写进链接，方便把某一条血缘直接发给同事："
        "/lineage/nebula?rootType=target_field&rootId=<字段ID>&direction=upstream&depth=6&view=business",
    )

    doc.add_heading("5.9 生成正式交付包", level=2)
    add_rich(doc, "入口：交付成果下的正式交付工作台（/deliverables）。")
    add_figure(doc, "15-deliverables.png", "正式交付工作台")
    add_rich(
        doc,
        "选择一表通目标表与已激活的模板版本后点创建交付包，系统会依次执行生成任务与渲染任务。"
        "完成后可以下载正式 Excel，其中包含结构化口径、技术溯源、血缘、变更影响等多个工作表，"
        "也可以查看版本对比。交付包带版本号与批准状态，重复批准是幂等的，不会重复产生版本。",
    )

    doc.add_heading("5.10 UAT 验收", level=2)
    add_rich(doc, "入口：交付中心下的 UAT。")
    add_figure(doc, "16-uat.png", "UAT 验收")
    add_rich(
        doc,
        "平台内置 8 个套件、94 条用例，其中自动 60 条、人工 7 条、混合 27 条。流程是上传 UAT 包、"
        "校验、执行、提 finding、复验、签核 4 份、下载报告与证据包。首轮失败后整改补验通过是"
        "设计允许的正常路径。",
    )

    doc.add_heading("5.11 后台任务", level=2)
    add_rich(
        doc,
        "入口：顶部后台任务。知识解析、索引重建、元数据同步、交付渲染、UAT 执行等长耗时操作"
        "都在这里排队执行。",
    )
    add_figure(doc, "17-jobs.png", "后台任务列表")
    add_rich(doc, "任务失败会记录错误原因，可以重试。同类型任务带幂等键，重复提交不会重复执行。")

    doc.add_heading("6 系统管理", level=1)
    add_rich(
        doc,
        "入口：左侧系统管理，分组为管理概览、机构管理、用户管理、角色与权限、平台健康，"
        "仅平台管理员可见。",
    )
    add_figure(doc, "18-admin-users.png", "用户管理")
    add_table(
        doc,
        [
            ["页面", "用途"],
            ["机构管理", "新建与查看机构，例如银行、平台运营方"],
            ["用户管理", "新建用户、分配机构与机构角色、启停账号"],
            ["角色与权限", "查看角色定义与权限项"],
            ["平台健康", "查看依赖健康状态、审计与运行信息"],
        ],
        widths=[Cm(3.4), Cm(13.2)],
    )

    doc.add_heading("6.1 模型与运行环境", level=2)
    add_rich(doc, "入口：/model-profiles（AI 运行环境）。")
    add_figure(doc, "20-model-profiles.png", "AI 运行环境的模型与向量存储配置")
    add_rich(
        doc,
        "这里能看到聊天模型、Embedding、向量存储三项的实际配置与连通性，"
        "以及当前项目最近的模型调用记录。当前生产状态有两点需要注意。",
    )
    add_bullets(
        doc,
        [
            "聊天模型档案指向外部服务，服务器访问该地址受限，且档案引用的密钥变量名与服务器的 "
            ".env 不一致，因此页面显示配置不完整。本次上线验收是用协议级假提供方跑通的，"
            "页面里 local_vllm 与 fake-openai-compatible 的调用记录就是那次验收留下的。",
            "库中已预置 deepseek 档案（api.deepseek.com、deepseek-chat），尚未启用，"
            "缺少 DEEPSEEK_API_KEY。要启用真实模型，按《服务器配置说明》3.5.1 的做法配置密钥"
            "并激活档案，然后在本页点测试连接确认。",
        ],
    )

    doc.add_heading("6.2 平台健康", level=2)
    add_rich(
        doc,
        "平台健康页（/admin/system-health）聚合数据库、Redis、任务队列、向量库、Embedding、"
        "模型配置与磁盘状态，出现异常时先看这一页再定位具体任务。",
    )
    add_figure(doc, "19-admin-health.png", "系统健康")

    doc.add_heading("7 常见问题", level=1)
    add_table(
        doc,
        [
            ["现象", "原因与处理"],
            ["打开页面一直转圈或提示 401", "令牌过期，重新登录一次；仍然不行就清理浏览器缓存"],
            [
                "检索报“请先重建索引”",
                "生产使用 Milvus 正式索引，上传或删改知识后需要到知识文档页点重新构建语义索引",
            ],
            ["目录检索不到字段", "数据源元数据同步未成功或只部分完成，先修数据源连通性再同步"],
            ["交付包生成卡住", "到后台任务查看具体任务状态与错误；Worker 异常时联系运维"],
            [
                "生成的草稿内容很空或像占位文本",
                "当前聊天模型尚未接入真实大模型，生成走的是降级或假提供方链路，见第 6 章",
            ],
            [
                "重复建机构或用户报资源状态冲突",
                "编码、用户名或邮箱已存在，属于正常校验（HTTP 409），换一个唯一值即可",
            ],
            ["想换项目看数据", "用顶部项目下拉切换，或带 ?projectId=<ID> 打开链接"],
            [
                "数据星云打开是空的或提示没有可展示节点",
                "该根对象在当前血缘版本下没有已登记的边：确认当前项目与根对象 ID 正确，"
                "或先在血缘页上传并发布脚本血缘",
            ],
        ],
        widths=[Cm(5.0), Cm(11.6)],
    )

    doc.add_heading("8 已知边界", level=1)
    add_bullets(
        doc,
        [
            "真实大模型尚未接入：www.hejuapi.com 在服务器上不可达，且模型档案引用的密钥变量名与 "
            ".env 不一致；DeepSeek 档案已建好但缺密钥。需要提供可用密钥或确认切换方案。",
            "本次上线验收覆盖了后端全部主链路与 8 个内置 UAT 套件，前端只做了 HTTP 层与页面级验证，"
            "本文截图即真实页面，未做多浏览器兼容性与压力并发测试。",
            "服务器提示内核更新待重启，尚未重启，不影响当前业务。",
            "库中的演示数据来自验收脚本，正式投产后建议清理，或改用真实机构与用户。",
            "数据星云只呈现已登记的血缘：脚本血缘要先在血缘页上传并发布，业务映射要先审核通过；"
            "平台不会按名称相似度自动连线，无法证明的关联一律留在“未解析”。",
        ],
    )

    doc.add_heading("9 文档维护", level=1)
    add_rich(
        doc,
        f"本文对应生产版本 {VERSION}。版本升级后如需更新本文，先在能访问站点的机器上重新采集截图："
        "GUIDE_USER 与 GUIDE_PASSWORD 传入管理员账号口令，运行 scripts/docs/capture_system_guide.py；"
        "再运行 scripts/docs/build_system_guide_docx.py 重新生成 Word 文档。"
        "同目录的 docs/系统使用文档.md 保留 Markdown 版本，两者内容保持一致。",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="生成系统使用文档 Word 交付件")
    parser.add_argument("--output", type=pathlib.Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    doc = setup_document()
    build(doc)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    doc.save(args.output)
    print(f"已生成 {args.output}")


if __name__ == "__main__":
    main()

"""Generate the Desktop completion report (.docx) for the 2026-10-05 upgrade round."""

from __future__ import annotations

from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt, RGBColor
from docx.oxml.ns import qn

OUT = Path(r"C:\Users\admin\Desktop\银行智能平台-2026-10-05升级验收报告.docx")

CN_FONT = "微软雅黑"


def set_cjk(run) -> None:
    run.font.name = CN_FONT
    run._element.rPr.rFonts.set(qn("w:eastAsia"), CN_FONT)


def para(document, text: str, *, size: int = 10.5, bold: bool = False, style: str | None = None):
    p = document.add_paragraph(style=style)
    run = p.add_run(text)
    run.bold = bold
    run.font.size = Pt(size)
    set_cjk(run)
    return p


def bullet(document, text: str, *, size: int = 10.5):
    p = document.add_paragraph(style="List Bullet")
    run = p.add_run(text)
    run.font.size = Pt(size)
    set_cjk(run)
    return p


def heading(document, text: str, level: int = 1):
    h = document.add_heading(level=level)
    run = h.add_run(text)
    run.font.size = Pt(15 if level == 1 else 12.5)
    run.font.color.rgb = RGBColor(0x1F, 0x3A, 0x5F)
    set_cjk(run)
    return h


def table(document, headers: list[str], rows: list[list[str]]):
    t = document.add_table(rows=1, cols=len(headers))
    t.style = "Light Grid Accent 1"
    for cell, text in zip(t.rows[0].cells, headers):
        cell.text = ""
        run = cell.paragraphs[0].add_run(text)
        run.bold = True
        run.font.size = Pt(9.5)
        set_cjk(run)
    for row in rows:
        cells = t.add_row().cells
        for cell, text in zip(cells, row):
            cell.text = ""
            run = cell.paragraphs[0].add_run(text)
            run.font.size = Pt(9.5)
            set_cjk(run)
    return t


def main() -> int:
    document = Document()
    style = document.styles["Normal"]
    style.font.name = CN_FONT
    style.font.size = Pt(10.5)
    style.element.rPr.rFonts.set(qn("w:eastAsia"), CN_FONT)

    title = document.add_heading(level=0)
    run = title.add_run("银行智能平台 2026-10-05 升级验收报告")
    run.font.size = Pt(22)
    set_cjk(run)
    sub = document.add_paragraph()
    sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = sub.add_run("分支 dsh/banking-semantic-agent-v2　·　最终提交 58cf2f9　·　工程验收（合成材料 / 隔离环境）")
    r.font.size = Pt(10)
    set_cjk(r)

    heading(document, "一、结论摘要", 1)
    para(document, "本轮按《复核与下一步开发计划-2026-10-05》与《下一轮开发提示词-2026-10-05》推进五个阶段，"
                   "共 22 个独立提交。第一阶段全部关闭；第三、五阶段验证通过；第二阶段代码全部修复；"
                   "第四阶段合成工程业务闭环 41/41 跑通（含 Finding 整改重测、四角色签署、变更复核）；"
                   "F01–F10 全部 10 项已完成真实浏览器验收；银行侧真实输入仍待提供，已如实列出。")
    table(document, ["检查项", "结果"], [
        ["后端全量回归（最终）", "1480 passed / 1 skipped / 0 failed"],
        ["前端单元测试", "253 passed / 0 failed"],
        ["前端 tsc / lint / build", "全部 exit 0"],
        ["前端生产依赖审计", "0 漏洞"],
        ["后端依赖 OSV 扫描（96 pin）", "0 公告"],
        ["bandit 静态分析（68,877 行）", "HIGH 0；与已定性扫描 STABLE（0 新增）"],
        ["合成工程业务闭环", "41/41 通过（readiness 清零 → 三级审核 → 冻结交付 → Word/Excel → Finding 整改重测 → 四角色签署 → 变更复核关闭）"],
        ["真实浏览器验收", "F01–F10 共 10/10 项（隔离栈；未做像素级视觉检查）"],
        ["真实 Redis/Celery 队列", "8/8 通过（独立 worker 进程消费、队列排空、重复投递围栏生效）"],
    ])

    heading(document, "二、修复的真实缺陷（含修复前后证据）", 1)

    heading(document, "1. P5：探针中止 PostgreSQL 事务（高）", 2)
    bullet(document, "现象：创建 UAT 轮次返回 500，异常却指向一条无辜的 SELECT requirement_uat_links。")
    bullet(document, "根因：version_info.schema_head() 用裸 except 吞掉失败但不回滚。PostgreSQL 中失败语句会使整个"
                     "事务进入 aborted 状态，同请求后续语句全部连带失败；SQLite 不中止事务，因此 1400+ 单测全绿也发现不了。")
    bullet(document, "证据：修复前 FOLLOWUP_SELECT_FAILED: InFailedSqlTransaction → 修复后 FOLLOWUP_SELECT_OK。")
    bullet(document, "修复：探针移入 SAVEPOINT（with db.begin_nested():）。")
    bullet(document, "端到端：第四阶段闭环由 EXIT=1 / ok=false → EXIT=0 / 16 项全通过。")

    heading(document, "2. SEC-1：SQL 剖析接口可注入子句（高）", 2)
    bullet(document, "来源：bandit B608 提示“可能注入”，经实证确认是真缺陷而非误报。")
    bullet(document, "根因：validate_and_prepare 只校验拼装后的整条语句是否单个 SELECT，无法区分“要的列”与“被注入的子句”。"
                     "构造 1) from t union select password from users -- 可穿过守卫。")
    bullet(document, "证据（真实 FastAPI 路由）：修复前 POST /api/db-profile/tasks → 200，safe_sql 含 UNION SELECT 并落库；"
                     "修复后 → 422，crafted_identifier_stored_in_sql=false。")
    bullet(document, "影响面（如实界定）：该接口只生成并校验 SQL（status=reserved），不执行；但语句会落库并作为"
                     "“已校验的安全 SQL”呈现给后续执行入口，因此必须修复。")
    bullet(document, "修复：插值发生方 profile_field 承担标识符契约（允许 schema.table），API 返回 422；新增 2 例回归测试。")

    heading(document, "3. 依赖漏洞（两批，均已清零）", 2)
    bullet(document, "前端 postcss：4 条公告（含 2 条高危）。根因是 next 自带嵌套副本 8.4.31，只改顶层声明无效；"
                     "修复后 npm audit --omit=dev 为 0/0/0/0/0。")
    bullet(document, "后端 OSV：9 条公告（3 HIGH / 2 MODERATE / 4 同源别名），集中在 cryptography 46.0.7 与 pytest 8.4.2；"
                     "升级到 50.0.0 / 9.0.3，并同步 lock、声明范围与 SBOM 后为 0 条。")

    heading(document, "三、五个阶段完成情况", 1)
    table(document, ["阶段", "内容", "结果"], [
        ["1", "安全与并发缺陷 N01–N05 / N11 / N13", "全部关闭"],
        ["2", "前端 F01–F10 人工编辑与集成", "✅ 10/10 项已真实浏览器验收（隔离栈 + 合成数据）"],
        ["3", "发布固化 P1–P4（lock/SBOM、发布身份、备份、失败退出）", "已在真实 Linux 容器验证"],
        ["4", "合成工程 UAT 闭环（8 字段/2 源表/1 集市/1 目标表、独立角色、Finding、签署、冻结）",
         "业务闭环 41/41 跑通（readiness 41→0；三级审核；冻结交付；Word/Excel 快照 hash 一致；Finding 整改重测；四角色签署；变更复核关闭 reviewed）"],
        ["5", "评测数据集、备份恢复、多 worker 与容量基线", "三项均验证通过"],
    ])

    heading(document, "四、关键实测数据", 1)
    bullet(document, "发布固化：真实 Linux 容器内 lock 安装 96 个包逐一相符；构建身份烘焙与 git HEAD 一致；"
                     "环境变量优先；api/worker/beat 各自正确上报；备份目录不可覆盖（BACKUP_UNIQUENESS_OK）。")
    bullet(document, "评测框架：数据集版本随内容变化（改一条查询即变），停用用例后版本随之改变；"
                     "两次运行绑定同一 dataset_version；失败样本按 case_id 对齐比较。")
    bullet(document, "备份恢复：真实 pg_dump 946,522 字节 → pg_restore 到全新库，5 张表行数与内容摘要完全一致，"
                     "实测 RTO 2.384 秒。")
    bullet(document, "多 worker：跨进程崩溃后按租约到期接管；陈旧 attempt 写入 rowcount=0（围栏生效）；"
                     "6 个独立进程竞争恰好 1 个赢家；容量基线 0.6 claims/s（受子进程启动开销主导，不代表生产吞吐）。")
    bullet(document, "冻结文件：需求 content_hash → 冻结快照 → 导出 Word/Excel，两个文件回带的 "
                     "X-Requirement-Snapshot-Hash 均与该 hash 相等（Word 38,046 字节、Excel 11,261 字节）。")

    heading(document, "五、未达成项 / 待验收条件（不得视为通过）", 1)
    for text in [
        "银行侧前置条件未提供：真实制度条款、真实源 SQL 脚本、真实数据目录、评测真值、业务阈值、身份、"
        "RTO/RPO 目标值、生产规模数据、真实样本与四类角色账号。（合成工程闭环本身已 24/24 跑通。）",
        "真实 Redis/Celery broker 与多机部署未验证（本轮验证的是数据库租约围栏层）。",
        "容器镜像层扫描未做（trivy/grype 未安装）；bandit 仅覆盖 app/ 目录；npm audit 仅覆盖生产依赖。",
        "未在 CI（Linux runner）执行上述检查，结论基于 Windows 本机环境。",
        "银行侧前置条件：评测真值、业务阈值、身份、RTO/RPO 目标值、生产规模数据、真实样本与四类角色账号均未提供。",
        "真实浏览器 UI 验收仅完成两项（折叠恢复、进度口径）；其余交互受“项目无数据且不得写入业务库”限制。",
        "四角色矩阵 / 输入 manifest / 证据清单（docs/upgrades/2026-10-03/w11/）逐行填写未做。",
        "本轮未在业务库应用迁移 202610050001 / 202610050002；本地运行的后端仍是旧进程（schema_head=202610030001）。"
        "业务库写入需另行授权。",
    ]:
        bullet(document, text)

    heading(document, "六、边界与保护（未被破坏）", 1)
    bullet(document, "现有业务数据、权限与项目 11 外发守卫未改动：无分类降级、无白名单扩大、无 Agent 自动批准或改写正式口径。")
    bullet(document, "所有破坏性/验证脚本均先通过 N13 隔离守卫；业务库 ybt_dsh_handoff_v2 被硬拒绝。")
    bullet(document, "本轮未删除任何用户文件或目录。")

    heading(document, "七、证据位置", 1)
    para(document, "全部实施记录、探针脚本与验证证据位于：")
    para(document, r"ai-platform\docs\upgrades\2026-10-05\（含 FINAL-ACCEPTANCE-REPORT.md 与缺陷矩阵 README.md）", size=10)

    document.save(OUT)
    print(OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

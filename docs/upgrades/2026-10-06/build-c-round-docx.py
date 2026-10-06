"""Generate the Desktop completion report (.docx) for the 2026-10-06 C01-C11 round."""

from __future__ import annotations

from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor

OUT = Path(r"C:\Users\admin\Desktop\银行智能平台-2026-10-06代码修复交付说明.docx")
CN_FONT = "微软雅黑"


def set_cjk(run) -> None:
    run.font.name = CN_FONT
    run._element.rPr.rFonts.set(qn("w:eastAsia"), CN_FONT)


def para(document, text: str, *, size: int = 10.5, bold: bool = False):
    p = document.add_paragraph()
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
            run.font.size = Pt(9)
            set_cjk(run)
    return t


def main() -> int:
    document = Document()
    style = document.styles["Normal"]
    style.font.name = CN_FONT
    style.font.size = Pt(10.5)
    style.element.rPr.rFonts.set(qn("w:eastAsia"), CN_FONT)

    title = document.add_heading(level=0)
    run = title.add_run("银行智能平台 2026-10-06 代码修复交付说明")
    run.font.size = Pt(21)
    set_cjk(run)
    sub = document.add_paragraph()
    sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = sub.add_run("分支 dsh/banking-semantic-agent-v2　·　基线 fd7a532 → 最终提交 3b1e262　·　任务书 C01–C11")
    r.font.size = Pt(10)
    set_cjk(r)

    heading(document, "一、结论", 1)
    para(document, "《银行智能平台-当前代码复核与今晚修复任务书-2026-10-06》的 11 项（C01–C11）"
                   "已全部完成源码修复并逐项验证：先 P1（C01–C07、C09、C10），再 P2（C08、C11）。"
                   "每项独立提交，均给出修复前证据、修改文件、commit、修复后结果与验证边界。")
    para(document, "本轮共 11 个提交（fd7a532 → 3b1e262）。最终在最新源码提交上重跑全量验证，"
                   "获得真实计数与退出码；失败项已处理，未验证项明确保留。", bold=True)

    heading(document, "二、最终验证结果（不复用历史计数）", 1)
    table(document, ["检查", "结果"], [
        ["后端全量回归（最终）", "1507 passed / 0 failed / 0 skipped（19:45，退出码 0）"],
        ["前端单元测试", "267 passed / 0 failed"],
        ["前端 tsc / lint / build", "全部退出码 0"],
        ["npm audit（生产依赖）", "0 漏洞"],
    ])
    para(document, "说明：后端基线为 1480 passed / 1 skipped；本轮新增 27 条用例，"
                   "且原 1 例 skipped 在设置验证库连接后执行并通过，故 skipped 归零。")

    heading(document, "三、逐项交付", 1)
    table(document, ["编号", "优先级", "主题", "Commit", "修复前 → 修复后"], [
        ["C01", "P1", "会话切换与退出", "bad980e", "1 passed/6 failed → 7/7"],
        ["C02", "P1", "草稿账号隔离", "8f0a43c", "9 passed/3 failed → 12/12"],
        ["C03", "P1", "重试后补偿派发失效", "8e780bb", "见下三项合计"],
        ["C04", "P1", "重复消费改写历史终态", "8e780bb", "6 failed/3 passed → 9/9"],
        ["C05", "P1", "心跳异常静默停止", "8e780bb", "同上"],
        ["C06", "P1", "评测模型与实际错配", "9fbf0e5", "见下三项合计"],
        ["C07", "P1", "降级回答被算满分", "9fbf0e5", "14 failed/3 passed → 17/17"],
        ["C08", "P2", "数据集版本不完整", "9fbf0e5", "同上"],
        ["C09", "P1", "连续发布身份与回滚", "7329f8b", "4 failed/8 passed → 12/12"],
        ["C10", "P1", "Redis 验收隔离", "1ea7440", "无守卫 → 12/12 + 负例拒绝"],
        ["C11", "P2", "轮询故障恢复", "639166e", "8 passed/2 failed → 10/10"],
    ])
    para(document, "「修复前」一列均由 git stash 临时还原产品源码后重跑同一份回归测得，"
                   "不是引用历史通过报告。", size=10)

    heading(document, "四、各修复的实质", 1)
    bullet(document, "C01：为会话引入代次（epoch）。续期开始时固定代次与刷新令牌，只有仍属当前会话的结果才能写回；"
                     "退出/重新登录/失效都会作废旧请求与旧续期。前端退出改为真正调用服务端 logout 吊销刷新令牌"
                     "（本地同步生效，网络异常不阻塞）。")
    bullet(document, "C02：本地草稿按可信登录用户 ID 隔离（键内含 actor，载荷记 owner 并在读取时严格校验）；"
                     "未取得身份时不读写草稿，无 owner 的历史草稿不被自动归属。")
    bullet(document, "C03：新增 background_jobs.queued_at（含迁移与回填），重试时在同一事务内清除上一 attempt 的"
                     "投递标记并写入本次队列时间；补偿派发按“本次 attempt”计时，broker 恢复后能补投。")
    bullet(document, "C04：任务一旦进入终态即为纯无操作；handler 缺失与机构停用两个分支改为“先原子领取再写终态”，"
                     "并用带 lease_owner 条件的受限 UPDATE 落库，重复消费不再改写成功历史。")
    bullet(document, "C05：心跳对瞬时数据库异常在租约窗口内有界重试；重试用尽则显式标记失租，"
                     "不再静默退出线程。")
    bullet(document, "C06：调用方显式选定的模型档案现在真正到达 runtime；指定不存在的档案直接拒绝，"
                     "不再静默回退到默认档案。")
    bullet(document, "C07：区分“检索质量”“生成可用性”“回答质量”三类指标。降级回答不再计入成功数与正确率，"
                     "并在每条结果中持久化执行元数据（answer_status、降级原因）。")
    bullet(document, "C08：数据集版本纳入全部评分相关输入（来源/表/字段/关键词/目标字段/场景等），"
                     "并按稳定键排序，行顺序不再影响版本号。")
    bullet(document, "C09：发布身份只来自显式构建清单或本次 git HEAD；发布标签在备份后立即写回（否则 compose 仍拉起旧镜像）；"
                     "新增镜像层身份核对；新增回滚脚本，同时恢复镜像与上报身份。")
    bullet(document, "C10：验收改用每次运行的 UUID 队列与专用 Redis 逻辑库，出现非空外部队列即拒绝运行；"
                     "重复投递改走真实 broker 与第二个真实 worker 进程；只清理自己的队列。")
    bullet(document, "C11：轮询连续失败后只停轮询、保留订阅，网络恢复（online）或可见性恢复会自动重拉；"
                     "新增可见提示与“立即重试”入口。")

    heading(document, "五、本轮我自己发现并修正的问题（如实记录）", 1)
    bullet(document, "全量回归暴露了我自己引入的 C06 回归（3 例）：为让评测选中的模型到达 runtime，"
                     "我改成总是传 model_profile_id，与一处测试替身签名不符。已改为“只有确实选中时才传”，"
                     "保持未指定时的原调用形状；定向复验 44 passed，全量 1507 passed。")
    bullet(document, "两处回归最初假通过：C04 的用例因模块级 handler 注册表残留而没走到“无 handler”分支；"
                     "C09 的假 curl 用快照读 .env，掩盖了“标签未写回即拉起旧镜像”的时序。两处均已改成真实触发。")
    bullet(document, "C11 有一条既有用例断言的正是缺陷本身（条目被删除）；已替换为更新的正确契约，"
                     "未删除或跳过任何断言。")
    bullet(document, "依赖扫描发现新公布的高危公告 source-map-js（GHSA-68fv-2mgg-jv7q）。"
                     "经核对不是本轮改动引入（本轮未触碰该依赖），但仍按实际影响修复到 1.2.2，审计回到 0。")

    heading(document, "六、未验证 / 待验收（不得当作通过）", 1)
    for text in [
        "真实银行资料与签署人仍缺失，W11 银行验收未完成（属既有待验收条件，未因此推迟本轮代码修复）。",
        "未操作业务库、未执行其迁移；本轮新增迁移 202610060001 只在全新隔离库验证到迁移头。",
        "未改动原有 3000/8000 服务；未清共享 Redis（DB0 的哨兵消息在验收前后完全未变）。",
        "未调用未批准的真实模型：C06/C07 的模型边界为 spy，C10 子进程强制 mock。",
        "未在 CI（Linux runner）执行以上检查；未做容器镜像层扫描；npm audit 仅覆盖生产依赖。",
        "C09 未在真实 Docker/Compose 上执行（用假工具链驱动真实脚本验证）。",
        "未做多机部署、broker/数据库高可用与容量压测。",
        "未做真实浏览器断网逐项验证 C11 的提示条与重试按钮；仅主状态页接入了可见提示。",
    ]:
        bullet(document, text)

    heading(document, "七、交付物位置", 1)
    para(document, r"ai-platform\docs\upgrades\2026-10-06\：逐项台账 README.md、C01–C11 实施记录、"
                   r"最终验收记录 final-acceptance-verification.md、依赖安全记录。", size=10)

    document.save(OUT)
    print(OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

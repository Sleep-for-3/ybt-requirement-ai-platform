# -*- coding: utf-8 -*-
"""对 gen_skills_oss_report.py 做收尾修补：
1) 恢复 2.1 卡片区注释；
2) 页面边距改为 2.0cm 并关闭表格 autofit（保证列宽不被 Word 收缩、也不溢出）；
3) 表格列宽按可用宽度等比缩放到恰好铺满；
4) 补回丢失的「三、落地建议」整节（含 10 行表与排除项说明）。
"""
import io
import os

DIR = r"C:\Users\admin\Downloads\ai-platform-dsh-20260930-150943\ai-platform\docs\research"
TARGET = os.path.join(DIR, "gen_skills_oss_report.py")
ORIG = os.path.join(DIR, "gen_skills_oss_report.orig.py")

lines = io.open(TARGET, encoding="utf-8").read().split("\n")

# ---------- 1. 2.1 注释 ----------
i = lines.index('h("2.1 文档解析 / 版面 / 证据定位", 2)')
assert not lines[i - 1].startswith("# ----"), lines[i - 1]
lines[i:i] = ["# ---- 2.1 卡片式 ----"]

# ---------- 2. 页面设置 ----------
j = lines.index("doc = Document()")
assert not any("page_width" in l for l in lines), "page setup already applied"
lines[j + 1:j + 1] = [
    "",
    "# ---------- 页面设置：边距收窄以容纳表格 ----------",
    "_sec = doc.sections[0]",
    "_sec.left_margin = Cm(2.0)",
    "_sec.right_margin = Cm(2.0)",
    "_sec.top_margin = Cm(2.0)",
    "_sec.bottom_margin = Cm(2.0)",
    "AVAIL_CM = 17.0  # 21.0 - 2.0 - 2.0；21.59(A4 宽) 与 Letter 均安全",
]

# ---------- 2b/3. 表格函数：关闭 autofit + 列宽归一化 ----------
k = lines.index("    t.autofit = True")
lines[k] = "    t.autofit = False"
w = lines.index("    if widths:")
block = [
    "    if widths:",
    "        ws = list(widths)",
    "        total = sum(ws)",
    "        if total > 0 and abs(total - AVAIL_CM) > 0.01:",
    "            ws = [x * AVAIL_CM / total for x in ws]",
    "        for r in t.rows:",
    "            for i, x in enumerate(ws):",
    "                r.cells[i].width = Cm(x)",
]
assert lines[w:w + 5] == [
    "    if widths:",
    "        for r in t.rows:",
    "            for i, w in enumerate(widths):",
    "                r.cells[i].width = Cm(w)",
    "    doc.add_paragraph().paragraph_format.space_after = Pt(2)",
], lines[w:w + 5]
lines[w:w + 4] = block

# ---------- 4. 补回「三、落地建议」 ----------
orig = io.open(ORIG, encoding="utf-8").read().split("\n")
a = orig.index("# ============================== 三、落地建议 ==============================")
b = orig.index("# ============================== 四、许可与合规 ==============================")
section3 = orig[a:b]
while section3 and section3[-1].strip() == "":
    section3.pop()

d = lines.index("# ============================== 四、许可与合规 ==============================")
lines[d:d] = section3

io.open(TARGET, "w", encoding="utf-8", newline="\n").write("\n".join(lines))
print("PATCHED ->", len(lines), "lines; inserted section three:", len(section3), "lines")

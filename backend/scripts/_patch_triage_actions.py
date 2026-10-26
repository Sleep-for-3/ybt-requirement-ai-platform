from pathlib import Path

p = Path("scripts/review_blockers_triage.py")
t = p.read_text(encoding="utf-8")

old_patterns = '''# 可以靠平台自身流程消解（再生成 + 证据接地 + 人工确认），不需要外部数据治理动作。
AUTO_PATTERNS = (
    "缺少业务定义",
    "缺少完整加工规则",
    "缺少字段依据",
    "缺少依据",
)

# 需要外部动作（上游元数据登记、制度条款入库、模板/脚本配置、业务确认）才能消解。
MANUAL_PATTERNS = (
    "未核验上游元数据",
    "缺少可定位的来源表或字段",
    "缺少来源到集市字段的加工映射",
    "模板变量",
)
'''
new_patterns = '''# 分类口径（写进报告，不夸大）：
#   auto_verifiable —— 平台已能自动核验或可再生成并经接地复核（文本级），最终仍需人工点确认；
#   needs_evidence  —— 必须先补上游元数据/制度条款/映射等外部证据，平台无法凭空产生；
#   manual_confirm  —— 只能由业务或技术责任人确认（脚本/模板配置同样归此类）。
AUTO_PATTERNS = (
    "缺少业务定义",
    "缺少完整加工规则",
    "缺少字段依据",
)

NEEDS_EVIDENCE_PATTERNS = (
    "未核验上游元数据",
    "缺少可定位的来源表或字段",
    "缺少来源到集市字段的加工映射",
    "缺少监管集市到目标字段映射",
    "未提供当前有效制度条款证据",
    "未核验",
)

MANUAL_PATTERNS = (
    "模板变量",
    "未经人工确认",
)
'''
assert t.count(old_patterns) == 1
t = t.replace(old_patterns, new_patterns)

old_classify = '''    action = "manual"
    cause = "其他"
    for pattern in AUTO_PATTERNS:
        if pattern in message:
            action = "auto"
            cause = pattern
            break
    else:
        for pattern in MANUAL_PATTERNS:
            if pattern in message:
                cause = pattern
                break

    if kind == "candidate":
        cause = "候选主张未被固定证据支撑"
        action = "auto"
    if kind == "scope" and action != "auto":
        action = "manual"
'''
new_classify = '''    action = "manual_confirm"
    cause = "其他"
    matched = False
    for label, patterns in (
        ("auto_verifiable", AUTO_PATTERNS),
        ("needs_evidence", NEEDS_EVIDENCE_PATTERNS),
        ("manual_confirm", MANUAL_PATTERNS),
    ):
        for pattern in patterns:
            if pattern in message:
                action = label
                cause = pattern
                matched = True
                break
        if matched:
            break

    if kind == "candidate" and not matched:
        cause = "候选主张未被固定证据支撑"
        action = "needs_evidence"
    if kind == "scope" and not matched:
        cause = "脚本/模板或上游事实未核验"
        action = "needs_evidence"
    if kind == "field" and not matched:
        cause = "字段正文缺依据"
        action = "auto_verifiable"
'''
assert t.count(old_classify) == 1
t = t.replace(old_classify, new_classify)

t = t.replace(
    '"auto_scope_note": "auto = 平台可再生成并经证据接地/人工确认后消解；manual = 需上游元数据登记、制度条款入库、脚本/模板配置或业务确认。"',
    '"action_note": "auto_verifiable=平台可自动核验或再生成（仍需人工点确认）；needs_evidence=必须先补上游元数据/制度条款/映射等外部证据；manual_confirm=业务或技术责任人确认（含脚本/模板配置）。"',
)
t = t.replace('> " + result["auto_scope_note"]', '> " + result["action_note"]')
p.write_text(t, encoding="utf-8")
print("triage updated")

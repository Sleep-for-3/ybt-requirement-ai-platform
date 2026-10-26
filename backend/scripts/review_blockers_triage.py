"""G3 送审阻断分诊：把 review-readiness 的 589 项按"能否自动化"分类（只读）。"""

from __future__ import annotations

import json
import re
import time
from collections import Counter, defaultdict
from pathlib import Path

import requests

BASE = "http://127.0.0.1:8011/api"
OUT = Path("scripts/out/retrieval")
OUT.mkdir(parents=True, exist_ok=True)
PROJECT_ID = 9
REQUIREMENT_ID = 30

FIELD_CODE_RE = re.compile(r"^(?P<field_id>\d+):(?P<aspect>[a-z_]+)")

# 分类口径（写进报告，不夸大）：
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


def login() -> str:
    response = requests.post(
        f"{BASE}/auth/login",
        json={"username": "ybt-lead", "password": "Ybt#20261024lead"},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()["access_token"]


def classify(reason: dict) -> dict:
    code = str(reason.get("code") or "")
    message = str(reason.get("message") or "")
    if code.startswith("scope:"):
        kind = "scope"
    elif code.startswith("candidate:"):
        kind = "candidate"
    elif FIELD_CODE_RE.match(code):
        kind = "field"
    else:
        kind = "other"

    field_id = reason.get("field_id")
    aspect = None
    match = FIELD_CODE_RE.match(code)
    if match:
        field_id = int(match.group("field_id"))
        aspect = match.group("aspect")

    action = "manual_confirm"
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

    return {
        "code": code,
        "kind": kind,
        "aspect": aspect,
        "field_id": field_id,
        "message": message,
        "cause": cause,
        "action": action,
    }


def main() -> int:
    token = login()
    headers = {"Authorization": f"Bearer {token}"}
    status = requests.get(f"{BASE}/projects/{PROJECT_ID}/requirements-status", headers=headers, timeout=60).json()
    item = next(row for row in status["items"] if row["requirement_id"] == REQUIREMENT_ID)
    content_version = item["content_version"]

    readiness = requests.get(
        f"{BASE}/projects/{PROJECT_ID}/requirements/{REQUIREMENT_ID}/review-readiness",
        headers=headers,
        params={"content_version": content_version},
        timeout=120,
    ).json()
    reasons = readiness.get("reasons") or []
    classified = [classify(reason) for reason in reasons]

    by_kind = Counter(row["kind"] for row in classified)
    by_cause = Counter(row["cause"] for row in classified)
    by_action = Counter(row["action"] for row in classified)
    by_field = defaultdict(Counter)
    for row in classified:
        if row["field_id"] is not None:
            by_field[str(row["field_id"])][row["aspect"] or row["kind"]] += 1

    sample = {}
    for row in classified:
        key = f"{row['kind']}:{row['cause']}"
        sample.setdefault(key, row["message"])

    result = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "project_id": PROJECT_ID,
        "requirement_id": REQUIREMENT_ID,
        "content_version": content_version,
        "eligible": readiness.get("eligible"),
        "blocking_count": readiness.get("blocking_count"),
        "by_kind": dict(by_kind),
        "by_cause": dict(by_cause.most_common()),
        "by_action": dict(by_action),
        "per_field": {field: dict(counter) for field, counter in sorted(by_field.items(), key=lambda kv: int(kv[0]))},
        "samples": sample,
        "action_note": "auto_verifiable=平台可自动核验或再生成（仍需人工点确认）；needs_evidence=必须先补上游元数据/制度条款/映射等外部证据；manual_confirm=业务或技术责任人确认（含脚本/模板配置）。",
    }
    (OUT / "g3_blockers_triage.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")

    lines = [
        "# 送审阻断分诊（G3）",
        "",
        f"- 项目 {PROJECT_ID} / 需求 {REQUIREMENT_ID} / 内容版本 {content_version}",
        f"- 阻断 {result['blocking_count']} 项，eligible={result['eligible']}",
        "",
        "| 类别 | 数量 |",
        "| --- | --- |",
    ]
    for kind, count in by_kind.most_common():
        lines.append(f"| {kind} | {count} |")
    lines += ["", "| 原因 | 数量 |", "| --- | --- |"]
    for cause, count in by_cause.most_common():
        lines.append(f"| {cause} | {count} |")
    lines += ["", "| 处置归属 | 数量 |", "| --- | --- |"]
    for action, count in by_action.most_common():
        lines.append(f"| {action} | {count} |")
    lines += ["", "## 每字段分布", "", "| 字段 | 缺项 |", "| --- | --- |"]
    for field, counter in result["per_field"].items():
        pairs = sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))
        lines.append(f"| {field} | " + "、".join(f"{name}×{count}" for name, count in pairs) + " |")
    lines += ["", "> " + result["action_note"], ""]
    (OUT / "g3_blockers_triage.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("blocking_count", "by_kind", "by_action")}, ensure_ascii=False))
    print(sorted(by_cause.items(), key=lambda kv: -kv[1])[:10])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

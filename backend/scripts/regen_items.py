"""对已建好的需求补跑个别字段章节，然后用最新内容冻结并重新导出。

真实场景（2026-10-24，项目 9）：批量验收跑完三张表后留下 3 个问题条目——
T_1_2 的 A020001 业务口径正文为空、T_10_1 的 K010001/K010002 因主张与脚本事实
冲突被阻断。这三条都需要"只补跑坏的那几条"，而不是重跑整张表（模型调用按时计费、
一张表要十几分钟）。

用法：
    python scripts/regen_items.py 13 T_1_2 487:business
    python scripts/regen_items.py 15 T_10_1 577:business 578:lineage

步骤：派发 generation-runs（只含指定字段章节）→ 轮询 → adopt（只采纳有差异的字段）
→ freeze（乐观锁用需求 version + 当前 content_hash）→ 导出 survey xlsx。
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND.parent / "scripts"))

from e2e_20261024 import Client  # noqa: E402

PROJECT_ID = 9
OUT = BACKEND / "scripts" / "out"
SECTION_FIELDS = {
    "business": ("business_definition", "final_content"),
    "lineage": ("processing_logic", "final_content"),
}


def _call(client: Client, method: str, path: str, **kwargs):
    for attempt in range(2):
        try:
            return client.request(method, path, **kwargs), None
        except Exception as exc:  # ApiError 与网络错误都按可重试处理
            status = getattr(exc, "status", None)
            if status == 401 and attempt == 0:
                client.login()
                continue
            return None, exc


def main(argv: list[str]) -> int:
    if len(argv) < 4:
        print(__doc__)
        return 64
    requirement_id = int(argv[1])
    table_code = argv[2]
    pairs = []
    for token in argv[3:]:
        field_part, _, section = token.partition(":")
        pairs.append((int(field_part), section or "business"))
    field_ids = [field for field, _ in pairs]
    sections = sorted({section for _, section in pairs})

    client = Client()
    client.login()
    base = f"/api/projects/{PROJECT_ID}/requirements/{requirement_id}"

    document, error = _call(client, "GET", f"{base}/document")
    if error:
        print("读取需求失败：", error)
        return 1
    content_version = document["revision"]["content_version"]

    started = _call(
        client, "POST", f"{base}/generation-runs",
        json_body={
            "expected_content_version": content_version,
            "field_ids": field_ids,
            "sections": sections,
            "idempotency_key": f"regen-{table_code}-{int(time.time())}",
        },
    )[0]
    if not started:
        print("派发生成失败")
        return 1
    input_id = started["input_id"]
    print(f"派发 input={input_id}，字段 {field_ids}，章节 {sections}")

    deadline = time.time() + 1800
    items = []
    while time.time() < deadline:
        time.sleep(20)
        runs, error = _call(client, "GET", f"{base}/generation-runs")
        if error:
            continue
        run = next((item for item in runs if item["id"] == input_id), None)
        if run is None or run.get("stale"):
            continue
        items = run.get("items") or []
        counts = run.get("counts") or {}
        print(f"  进度 {counts}（{sum(counts.values())}/{run.get('total')}）")
        if counts.get("pending", 0) == 0 and counts.get("running", 0) == 0:
            break

    selections = []
    for item in items:
        if item.get("status") != "completed":
            print(f"  条目 {item['id']} 未完成：{item.get('status')} {item.get('reason_code')}")
            continue
        detail, error = _call(client, "GET", f"{base}/generation-items/{item['id']}")
        if error:
            continue
        changed = [change["field"] for change in (detail.get("changes") or []) if change.get("changed")]
        selected = [name for name in changed if name in SECTION_FIELDS.get(item["section"], ())]
        if selected:
            selections.append({
                "item_id": item["id"],
                "candidate_hash": detail["candidate_hash"],
                "selected_fields": selected,
            })
    if not selections:
        print("没有可采纳的候选")
        return 1
    adopted = _call(client, "POST", f"{base}/generation-candidates/adopt",
                    json_body={"expected_content_version": content_version, "selections": selections})[0]
    print("采纳：", {key: adopted.get(key) for key in ("idempotent", "content_version")})

    document = _call(client, "GET", f"{base}/document")[0]
    snapshot = _call(client, "POST", f"{base}/snapshots",
                     json_body={"expected_version": document["requirement"]["version"],
                                "expected_hash": document["content_hash"]})[0]
    print("冻结快照：", snapshot)

    import requests
    response = requests.post(
        f"{Client.BASE if hasattr(Client, 'BASE') else 'http://127.0.0.1:8011'}{base}/exports",
        headers={"Authorization": f"Bearer {client.token}"},
        data={"format": "xlsx", "source_kind": "draft_snapshot", "source_id": str(snapshot["id"]),
              "layout": "survey"},
        timeout=300,
    )
    if response.status_code != 200:
        print("导出失败：", response.status_code, response.text[:300])
        return 1
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{table_code}-survey.xlsx"
    path.write_bytes(response.content)
    print("导出：", path.name, len(response.content), "B", response.headers.get("x-requirement-renderer-version"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

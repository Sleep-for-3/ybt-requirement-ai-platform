"""把一条已冻结需求按三种格式各导一次，并验证"跨秒重渲染字节一致"。

为什么需要这个脚本：`script` 级测试只能证明代码逻辑，冻结产物的真实性质只有在真实存储、
真实 PostgreSQL、真实 openpyxl/python-docx 上才能确认——2026-10-24 就在这里发现了
"xlsx 跨秒导出三个不同 sha"与"产物记录根本没落库"两个静默缺陷。

用法（在 `ai-platform/backend` 下）：

    $env:PYTHONPATH="."
    .\.venv\Scripts\python.exe scripts\export_all_formats.py 9 10 1

参数：project_id、requirement_id、snapshot_id（冻结快照 id）。
产物写到 `backend/scripts/out/`，每次先删掉该需求的产物记录，强制真实重渲染两次后比对。
"""

from __future__ import annotations

import hashlib
import sys
import time
from pathlib import Path

import requests

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND.parent / "scripts"))

from e2e_20261024 import BASE, Client  # noqa: E402

OUT = BACKEND / "scripts" / "out"
CASES = (
    ("docx", None, "requirement-docx.docx"),
    ("xlsx", None, "requirement-xlsx-standard.xlsx"),
    ("xlsx", "survey", "requirement-xlsx-survey.xlsx"),
)


def purge_artifacts(project_id: int, requirement_id: int) -> int:
    from app.core.database import SessionLocal
    from app.models import RequirementRenderArtifact

    db = SessionLocal()
    try:
        removed = (
            db.query(RequirementRenderArtifact)
            .filter(
                RequirementRenderArtifact.project_id == project_id,
                RequirementRenderArtifact.requirement_id == requirement_id,
            )
            .delete(synchronize_session=False)
        )
        db.commit()
        return int(removed)
    finally:
        db.close()


def export(client: Client, project_id: int, requirement_id: int, snapshot_id: int, fmt: str, layout: str | None):
    form = {
        "format": fmt,
        "source_kind": "draft_snapshot",
        "source_id": str(snapshot_id),
    }
    if layout:
        form["layout"] = layout
    response = requests.post(
        f"{BASE}/api/projects/{project_id}/requirements/{requirement_id}/exports",
        headers={"Authorization": f"Bearer {client.token}"},
        data=form,
        timeout=180,
    )
    response.raise_for_status()
    return response.content, response.headers


def main(project_id: int, requirement_id: int, snapshot_id: int) -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    client = Client()
    client.login()

    for fmt, layout, name in CASES:
        first, headers = export(client, project_id, requirement_id, snapshot_id, fmt, layout)
        purge_artifacts(project_id, requirement_id)
        time.sleep(1.4)
        second, second_headers = export(client, project_id, requirement_id, snapshot_id, fmt, layout)
        digest = hashlib.sha256(second).hexdigest()
        (OUT / name).write_bytes(second)
        print(
            f"{name}: bytes={len(second)} sha256={digest[:16]} identical={first == second} "
            f"renderer={second_headers.get('x-requirement-renderer-version')} "
            f"artifact={second_headers.get('x-requirement-render-artifact-id')}"
        )
        if first != second:
            print(f"  !! {name} 跨秒重渲染不一致：{headers.get('x-requirement-rendered-file-sha256')[:16]} vs {digest[:16]}")
            return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(int(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3])))

"""真实链路：上传一表通调研表 → 审核 → 激活 → Apply 到监管字段。

用法（在 backend 目录）：
    后端 .venv 里的 python 执行本脚本
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
E2E_DIR = BACKEND.parent / "scripts"
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(E2E_DIR))

from e2e_20261024 import BASE, PASSWORD, USER, Client  # noqa: E402

PROJECT_ID = 9
SURVEY = Path(r"C:\Users\李儒伟\Desktop\20261024\一表通报送口径需求调研表-一表通项目.xlsx")


def main(argv: list[str] | None = None) -> int:
    argv = argv or sys.argv[1:]
    reuse = {}
    for item in argv:
        if item.startswith("--template-id="):
            reuse["template_id"] = int(item.split("=", 1)[1])
        elif item.startswith("--version-id="):
            reuse["version_id"] = int(item.split("=", 1)[1])
    client = Client(BASE)
    client.login(USER, PASSWORD)
    if reuse.get("template_id") and reuse.get("version_id"):
        payload = {"template_id": reuse["template_id"], "version_id": reuse["version_id"]}
        print("reuse:", payload)
        _activate_and_apply(client, payload)
        return 0
    payload = client.upload(
        "/api/templates/upload",
        files={"file": SURVEY},
        fields={
            "project_id": str(PROJECT_ID),
            "template_code": "YBT_SURVEY_2022",
            "display_name": "一表通报送口径需求调研表",
            "regulatory_version": "R2022100101",
        },
    )
    assert isinstance(payload, dict)
    print("upload:", {k: payload.get(k) for k in ("template_id", "version_id", "version_no", "parse_status",
                                                  "sheet_count", "table_count", "field_count")})
    warnings = payload.get("warnings") or []
    print("warnings:", len(warnings))
    for item in warnings[:5]:
        print("  ", str(item)[:150])
    _activate_and_apply(client, payload)
    Path("_template_upload.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


def _activate_and_apply(client: Client, payload: dict) -> None:
    version_id = payload["version_id"]
    current = client.request("GET", f"/api/templates/versions/{version_id}")
    status = current.get("status")
    if status in {"pending_review", "draft"}:
        client.request("POST", f"/api/templates/versions/{version_id}/review", json_body={})
        status = "approved"
    if status == "approved":
        activated = client.request("POST", f"/api/templates/versions/{version_id}/activate", json_body={})
        print("activated:", activated.get("status"), activated.get("version_no"))
    else:
        print("version already active:", status, current.get("version_no"))
    applied = client.request("POST", f"/api/templates/{payload['template_id']}/apply", json_body={}, timeout=1800)
    print("apply:", json.dumps({k: applied.get(k) for k in (
        "created_tables", "updated_tables", "created_fields", "updated_fields",
        "created_mart_tables", "created_mart_fields", "created_mart_mappings", "skipped_rows")},
        ensure_ascii=False))
    print("apply warnings:", len(applied.get("warnings") or []))
    for item in (applied.get("warnings") or [])[:8]:
        print("  ", str(item)[:160])


if __name__ == "__main__":
    raise SystemExit(main())

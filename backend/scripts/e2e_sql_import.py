"""真实链路：把 88 个 GBase 跑批脚本 + 补录平台建表语句导入平台（预检 → 提交）。

用法（backend 目录）：
    .venv/Scripts/python.exe scripts/e2e_sql_import.py [--apply]
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND.parent / "scripts"))

from e2e_20261024 import BASE, PASSWORD, USER, Client  # noqa: E402

PROJECT_ID = 9
SOURCE_DIR = Path(r"C:\Users\李儒伟\Desktop\20261024")


def collect() -> tuple[list[Path], dict[str, str]]:
    files = sorted((SOURCE_DIR / "GBASE").glob("*.sql"))
    files.append(SOURCE_DIR / "补录平台表建表语句.sql")
    kinds = {}
    for path in files:
        if path.name == "补录平台表建表语句.sql":
            kinds[f"GBASE/{path.name}"] = "ddl"
        else:
            kinds[f"GBASE/{path.name}"] = "sql"
    return files, kinds


def main(argv: list[str]) -> int:
    files, _ = collect()
    total_bytes = sum(item.stat().st_size for item in files)
    print(f"files={len(files)} bytes={total_bytes/1024/1024:.2f}MB")
    client = Client(BASE)
    client.login(USER, PASSWORD)
    options = {
        "dialect": "gbase",
        "defaults": {"database_name": "INSTANCE_GB", "schema_name": "", "accept_incomplete": True},
    }
    started = time.time()
    payload = client.upload_many(
        f"/api/projects/{PROJECT_ID}/resource-imports",
        "files",
        files,
        fields={"idempotency_key": f"gbase-scripts-{int(started)}", "options": json.dumps(options, ensure_ascii=False)},
        timeout=3600,
    )
    print(f"uploaded in {time.time() - started:.1f}s")
    assert isinstance(payload, dict)
    print("batch:", {k: payload.get(k) for k in ("id", "status", "version", "file_count", "summary")})
    preview = payload.get("preview") or {}
    print("preview keys:", list(preview)[:12])
    items = preview.get("items") or []
    failures = [item for item in items if item.get("status") not in ("ready", "parsed", "ok", "preview_ready")]
    print("items:", len(items), "non-ready:", len(failures))
    for item in failures[:6]:
        print("  FAIL", item.get("file_name"), item.get("status"), str(item.get("reason") or item.get("warnings"))[:200])
    batch_id = payload["id"]
    Path("_sql_import_preview.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    if "--apply" in argv:
        version = payload.get("version") or preview.get("version") or 1
        started = time.time()
        applied = client.request("POST", f"/api/projects/{PROJECT_ID}/resource-imports/{batch_id}/apply",
                                 json_body={"expected_version": version}, timeout=7200)
        print(f"applied in {time.time() - started:.1f}s")
        print("apply:", json.dumps({k: applied.get(k) for k in ("status", "version", "summary")}, ensure_ascii=False)[:1500])
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

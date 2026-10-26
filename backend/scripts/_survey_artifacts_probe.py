"""一次性勘察：列出 T_8_1 需求的渲染产物并下载最新一个 survey xlsx 供 doc_compare 验证。"""
import json
from pathlib import Path

import requests

BASE = "http://127.0.0.1:8011/api"
OUT = Path("scripts/out/probe")
TOKEN = (OUT / "token.txt").read_text().strip()
HEADERS = {"Authorization": f"Bearer {TOKEN}"}


def main() -> None:
    for requirement_id in (8, 10, 24, 25, 30):
        response = requests.get(
            f"{BASE}/projects/9/requirements/{requirement_id}/render-artifacts",
            headers=HEADERS,
            timeout=60,
        )
        if response.status_code != 200:
            print(requirement_id, response.status_code, response.text[:120])
            continue
        artifacts = response.json()
        if isinstance(artifacts, dict):
            artifacts = artifacts.get("items") or artifacts.get("artifacts") or []
        xlsx = [a for a in artifacts if "xlsx" in json.dumps(a, ensure_ascii=False)]
        print(requirement_id, "artifacts", len(artifacts), "xlsx", len(xlsx))
        for item in xlsx[-2:]:
            print("   ", {k: item.get(k) for k in ("id", "artifact_id", "renderer_version", "created_at")})
            target = OUT / f"artifact_r{requirement_id}_{item.get('id')}.xlsx"
            download = requests.get(
                f"{BASE}/projects/9/render-artifacts/{item.get('id')}/download",
                headers=HEADERS,
                timeout=120,
            )
            if download.status_code == 200:
                target.write_bytes(download.content)
                print("    saved", target, len(download.content))
            else:
                print("    download", download.status_code, download.text[:120])


if __name__ == "__main__":
    main()

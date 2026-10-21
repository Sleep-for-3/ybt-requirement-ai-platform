"""检查真实冒烟项目中的知识文档/版本/知识单元状态（只读）。"""

import json
import urllib.request

BASE = "http://127.0.0.1:8011"


def call(path, payload=None, method="GET", token=None):
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {"Content-Type": "application/json"} if data else {}
    if token:
        headers["Authorization"] = "Bearer " + token
    request = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=180) as response:
        return json.loads(response.read().decode() or "null")


def main() -> None:
    token = call("/api/auth/login", {"username": "vnext-smoke", "password": "VnextSmoke#2026"}, "POST")["access_token"]
    docs = call("/api/projects/1/knowledge/documents", token=token)
    print("DOCS:", json.dumps(docs, ensure_ascii=False)[:1500])
    if docs:
        doc_id = docs[0]["id"]
        detail = call(f"/api/knowledge/documents/{doc_id}?project_id=1", token=token)
        print("DETAIL:", json.dumps(detail, ensure_ascii=False)[:1200])
        versions = call(f"/api/knowledge/documents/{doc_id}/versions?project_id=1", token=token)
        print("VERSIONS:", json.dumps(versions, ensure_ascii=False)[:1200])
    units = call("/api/projects/1/knowledge/units", token=token)
    print("UNIT_COUNT:", len(units))
    print("UNITS:", json.dumps(units[:3], ensure_ascii=False)[:1500])


if __name__ == "__main__":
    main()

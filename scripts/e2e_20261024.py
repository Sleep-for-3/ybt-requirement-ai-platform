"""Real end-to-end driver for the 2026-10-24 一表通 delivery.

Talks to a running backend (default http://127.0.0.1:8011) with a real
PostgreSQL/Redis/Milvus stack and the deployment .env. Every step prints what
the server returned so failures are evidence, not guesses.

Steps (run in order, each is idempotent where the API allows it):

    project    create the project (or reuse by name)
    template   upload the regulator survey workbook as a regulatory template
    template-check  report how the survey workbook was interpreted
    resources  import the GBASE scripts + 补录 DDL as project resources
    scripts    list parsed script versions and their lineage summary
    plan       what a script-preview would produce for one target table
    reqs       create requirements from scripts for one target table
    status     print project/requirement state
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

BASE = os.environ.get("E2E_BASE", "http://127.0.0.1:8011")
USER = os.environ.get("E2E_USER", "ybt-lead")
PASSWORD = os.environ.get("E2E_PASSWORD", "Ybt#20261024lead")
DATA_DIR = Path(os.environ.get("E2E_DATA", r"C:\Users\李儒伟\Desktop\20261024"))
SURVEY = DATA_DIR / "一表通报送口径需求调研表-一表通项目.xlsx"
DDL = DATA_DIR / "补录平台表建表语句.sql"
SAMPLE_OUTPUT = Path(r"C:\Users\李儒伟\Desktop\需求文档输出示例.xlsx")
PROJECT_NAME = os.environ.get("E2E_PROJECT", "一表通监管报送 20261024")


class ApiError(RuntimeError):
    def __init__(self, status: int, detail: object, url: str) -> None:
        self.status = status
        self.detail = detail
        super().__init__(f"{status} {url}: {detail}")


class Client:
    def __init__(self, base: str = BASE) -> None:
        self.base = base.rstrip("/")
        self.token: str | None = None

    # -- transport -------------------------------------------------
    def login(self, username: str = USER, password: str = PASSWORD) -> dict:
        payload = json.dumps({"username": username, "password": password}).encode()
        req = urllib.request.Request(
            f"{self.base}/api/auth/login",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as response:
            body = json.load(response)
        self.token = body["access_token"]
        return body

    def _headers(self, extra: dict | None = None) -> dict:
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        headers.update(extra or {})
        return headers

    def request(self, method: str, path: str, *, json_body=None, raw: bytes | None = None,
                content_type: str = "application/json", timeout: int = 180) -> object:
        url = f"{self.base}{path}"
        data = None
        headers = self._headers()
        if json_body is not None:
            data = json.dumps(json_body).encode()
            headers["Content-Type"] = content_type
        elif raw is not None:
            data = raw
            headers["Content-Type"] = content_type
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                payload = response.read()
                ctype = response.headers.get("content-type", "")
                if "application/json" in ctype:
                    return json.loads(payload.decode() or "null")
                return payload
        except urllib.error.HTTPError as exc:
            body = exc.read().decode(errors="replace")
            try:
                detail = json.loads(body)
            except json.JSONDecodeError:
                detail = body[:800]
            raise ApiError(exc.code, detail, url) from None

    def upload(self, path: str, files: dict[str, Path], fields: dict[str, str] | None = None,
               timeout: int = 600) -> object:
        boundary = "----e2e-boundary-20261024"
        chunks: list[bytes] = []
        for name, value in (fields or {}).items():
            chunks.append(
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n".encode()
            )
        for field, file_path in files.items():
            name = file_path.name
            chunks.append(
                (
                    f"--{boundary}\r\nContent-Disposition: form-data; name=\"{field}\"; "
                    f"filename=\"{name}\"\r\nContent-Type: application/octet-stream\r\n\r\n"
                ).encode()
                + file_path.read_bytes()
                + b"\r\n"
            )
        chunks.append(f"--{boundary}--\r\n".encode())
        body = b"".join(chunks)
        return self.request(
            "POST",
            path,
            raw=body,
            content_type=f"multipart/form-data; boundary={boundary}",
            timeout=timeout,
        )

    def upload_many(self, path: str, field: str, files: list[Path],
                    fields: dict[str, str] | None = None, timeout: int = 3600) -> object:
        """同一字段名重复上传多个文件（FastAPI 的 ``list[UploadFile]`` 形态）。"""

        boundary = "----e2e-boundary-20261024"
        chunks: list[bytes] = []
        for name, value in (fields or {}).items():
            chunks.append(
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n".encode()
            )
        for file_path in files:
            chunks.append(
                (
                    f"--{boundary}\r\nContent-Disposition: form-data; name=\"{field}\"; "
                    f"filename=\"{file_path.name}\"\r\nContent-Type: application/octet-stream\r\n\r\n"
                ).encode()
                + file_path.read_bytes()
                + b"\r\n"
            )
        chunks.append(f"--{boundary}--\r\n".encode())
        return self.request(
            "POST",
            path,
            raw=b"".join(chunks),
            content_type=f"multipart/form-data; boundary={boundary}",
            timeout=timeout,
        )

    # -- domain helpers --------------------------------------------
    def ensure_institution(self, code: str = "YBT-BANK", name: str = "一表通试点行") -> dict:
        institutions = self.request("GET", "/api/admin/institutions")
        for institution in institutions:
            if institution["institution_code"] == code:
                return institution
        return self.request("POST", "/api/admin/institutions", json_body={
            "institution_code": code,
            "institution_name": name,
            "institution_type": "bank",
        })

    def ensure_project(self, name: str = PROJECT_NAME) -> dict:
        projects = self.request("GET", "/api/projects")
        for project in projects:
            if project["name"] == name:
                return project
        institution = self.ensure_institution()
        return self.request("POST", "/api/projects", json_body={
            "name": name,
            "bank_name": "一表通试点行",
            "description": "以 20261024 GBASE 跑批脚本与一表通报送口径调研表为输入的真实交付演练",
            "institution_id": institution["id"],
            "governance_workflow_enabled": False,
        })


def dump(label: str, value: object, limit: int = 4000) -> None:
    text = json.dumps(value, ensure_ascii=False, indent=2, default=str) if not isinstance(value, str) else value
    print(f"\n===== {label} =====")
    print(text[:limit] + ("\n... (truncated)" if len(text) > limit else ""))


def step_project(client: Client, args) -> None:
    project = client.ensure_project(args.project or PROJECT_NAME)
    dump("project", project)


def step_template(client: Client, args) -> None:
    project = client.ensure_project(args.project or PROJECT_NAME)
    result = client.upload(
        f"/api/templates/upload",
        {"file": SURVEY},
        {
            "project_id": str(project["id"]),
            "template_code": "YBT_SURVEY_2026",
            "display_name": "一表通报送口径需求调研表",
            "regulatory_version": "2026.10",
            "publisher": "监管机构",
        },
    )
    dump("template upload", result, limit=6000)


def step_template_check(client: Client, args) -> None:
    project = client.ensure_project(args.project or PROJECT_NAME)
    templates = client.request("GET", f"/api/projects/{project['id']}/templates")
    dump("templates", templates)
    for template in templates:
        detail = client.request("GET", f"/api/templates/{template['id']}/detail")
        dump(f"template {template['id']} detail", detail, limit=3000)
        results = client.request("GET", f"/api/templates/{template['id']}/parse-results")
        summary = [
            {
                "sheet": row.get("sheet_name"),
                "table_code": row.get("table_code"),
                "field_count": row.get("field_count"),
                "warnings": (row.get("warnings_json") or [])[:3],
            }
            for row in results
        ]
        dump(f"template {template['id']} parse results", summary[:20], limit=4000)
        print("parsed sheets:", len(results), "fields:", sum(r.get("field_count") or 0 for r in results))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("step", choices=["project", "template", "template-check"])
    parser.add_argument("--project", default=None)
    args = parser.parse_args(argv)

    client = Client()
    client.login()
    {"project": step_project, "template": step_template, "template-check": step_template_check}[args.step](client, args)
    return 0


if __name__ == "__main__":
    sys.exit(main())

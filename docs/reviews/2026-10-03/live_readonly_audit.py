"""Local review: read business APIs, save only aggregate evidence.

Optional credentials are read from an existing local file and kept in memory.
Login/logout update session/audit records; no business write or model call occurs.
"""
from __future__ import annotations

import argparse
import ast
from collections import Counter
from datetime import datetime
import json
from pathlib import Path
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8000")
    parser.add_argument("--credentials-file", type=Path)
    parser.add_argument("--output", type=Path, default=Path(__file__).with_name("live-api-evidence.json"))
    args = parser.parse_args()
    if urlparse(args.base).hostname not in {"127.0.0.1", "localhost", "::1"}:
        parser.error("This review tool only accepts loopback targets.")
    evidence = {"observed_at": datetime.now().astimezone().isoformat(), "base": args.base,
                "scope": "aggregate-only; no business writes or model calls", "probes": []}
    access_token = None
    refresh_token = None

    def call(path, *, body=None, authenticated=False):
        headers = {"Content-Type": "application/json"}
        if authenticated and access_token:
            headers["Authorization"] = "Bearer " + access_token
        request = Request(args.base.rstrip("/") + path,
                          data=json.dumps(body).encode() if body is not None else None,
                          headers=headers, method="POST" if body is not None else "GET")
        started = time.perf_counter()
        status = None
        data = None
        try:
            with urlopen(request, timeout=30) as response:
                status = response.status
                data = json.loads(response.read())
        except HTTPError as error:
            status = error.code
        except (URLError, TimeoutError, ValueError):
            pass
        observation = {"path": path, "authenticated": authenticated, "http_status": status,
                       "elapsed_ms": round((time.perf_counter() - started) * 1000, 1)}
        if isinstance(data, list):
            observation["returned_count"] = len(data)
            observation["status_counts"] = dict(Counter(str(item.get("status", "unspecified"))
                for item in data if isinstance(item, dict)))
        elif isinstance(data, dict):
            for key in ("status", "total", "total_count", "score", "overall_score", "ready", "is_ready"):
                value = data.get(key)
                if value is None or isinstance(value, (str, int, float, bool)):
                    if key in data:
                        observation["resource_status" if key == "status" else key] = value
            if path.endswith("/health/ready"):
                observation["checks"] = data.get("checks", {})
            if path.endswith("/agent/metrics"):
                # Metric names and scalar/count values only, never prompts/objectives.
                observation["metrics"] = {
                    key: value for key, value in data.items()
                    if isinstance(value, (int, float, bool)) or value is None
                }
                if isinstance(data.get("metrics"), dict):
                    observation["metrics"] = {
                        key: value for key, value in data["metrics"].items()
                        if isinstance(value, (int, float, bool)) or value is None
                    }
                    observation["metric_denominators"] = data.get("denominators", {})
                    source_file = Path(__file__).resolve().parents[3] / "backend/app/services/agent/observability.py"
                    declared = {}
                    for node in ast.parse(source_file.read_text(encoding="utf-8")).body:
                        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id in {"V1_METRICS", "V2_METRICS"}:
                            declared[node.target.id] = ast.literal_eval(node.value)
                    expected_keys = set(declared.get("V1_METRICS", ())) | set(declared.get("V2_METRICS", ()))
                    observation["missing_metric_keys_vs_current_source"] = sorted(expected_keys - set(data["metrics"]))
            for key in ("items", "requirements", "tables", "tasks", "runs", "blockers", "gaps"):
                if isinstance(data.get(key), list):
                    observation[key + "_returned_count"] = len(data[key])
        evidence["probes"].append(observation)
        return status, data

    call("/health/live")
    call("/health/ready")
    for path in ("/api/projects", "/api/agent/tools", "/api/ai-skills", "/api/audit", "/api/jobs"):
        call(path)
    status, schema = call("/openapi.json")
    if status == 200 and isinstance(schema, dict):
        operations = [(path, method, item) for path, methods in schema.get("paths", {}).items()
                      for method, item in methods.items() if method in {"get", "post", "put", "patch", "delete"}]
        evidence["openapi"] = {"path_count": len(schema.get("paths", {})), "operation_count": len(operations),
            "tag_operation_counts": dict(Counter(tag for _, _, item in operations for tag in item.get("tags", [])))}

    if args.credentials_file:
        credentials = dict(line.split("=", 1) for line in args.credentials_file.read_text(encoding="utf-8-sig").splitlines()
                           if "=" in line)
        status, session = call("/api/auth/login", body={"username": credentials["username"].strip(),
                                                       "password": credentials["password"].strip()})
        del credentials
        if status == 200 and isinstance(session, dict):
            access_token, refresh_token = session["access_token"], session["refresh_token"]
            del session
            call("/api/auth/me", authenticated=True)
            call("/api/ai-runtime/status", authenticated=True)
            status, projects = call("/api/projects", authenticated=True)
            project_ids = [item["id"] for item in projects] if status == 200 and isinstance(projects, list) else []
            selected = list(dict.fromkeys(([1] if 1 in project_ids else []) + ([11] if 11 in project_ids else [])
                                         + project_ids[:1]))
            evidence["sample_project_ids"] = selected
            for project_id in selected:
                call(f"/api/target-tables?project_id={project_id}", authenticated=True)
                for suffix in ("readiness", "requirements", "catalog/tables", "deliverables",
                               "questions", "agent/tasks?limit=200", "agent/metrics", "knowledge/documents", "uat-suites", "uat-runs"):
                    response_status, response_data = call(f"/api/projects/{project_id}/{suffix}", authenticated=True)
                    if suffix == "requirements" and response_status == 200 and isinstance(response_data, list):
                        for requirement in response_data[:2]:
                            for detail_suffix in ("formal-deliveries", "review-submissions", "review-readiness", "snapshots", "revisions"):
                                detail_query = f"?content_version={max(1, int(requirement.get('content_version') or 1))}" if detail_suffix == "review-readiness" else ""
                                call(f"/api/projects/{project_id}/requirements/{requirement['id']}/{detail_suffix}{detail_query}", authenticated=True)
            for path in ("/api/jobs", "/api/me/notifications", "/api/agent/tools", "/api/audit"):
                call(path, authenticated=True)
            call("/api/auth/logout", body={"refresh_token": refresh_token}, authenticated=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(evidence, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

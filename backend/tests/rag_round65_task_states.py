"""Create isolated, visibly synthetic task states without dispatching jobs."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

import httpx
from sqlalchemy import select

BACKEND = Path(__file__).resolve().parents[1]
REPOSITORY = BACKEND.parent
sys.path[:0] = [str(BACKEND), str(BACKEND / "scripts"), str(BACKEND / "tests")]

from rag_round60_inflight_governance import _configure_database

API = "http://127.0.0.1:18140"
PROJECT_ID = 18
MARKER = "[ROUND65-SYNTHETIC-UI]"


def run(output: Path) -> dict:
    if output.exists():
        raise FileExistsError("Use a new attempt directory")
    output.mkdir(parents=True)
    bootstrap = _configure_database()
    from app.core.database import SessionLocal
    from app.models import AgentPlan, AgentStep, AgentTask

    with httpx.Client(base_url=API, timeout=30, trust_env=False) as client:
        version = client.get("/version")
        version.raise_for_status()
        login = client.post("/api/auth/login", json={
            "username": bootstrap["username"], "password": bootstrap["password"],
        })
        login.raise_for_status()
        client.headers["Authorization"] = "Bearer " + login.json()["access_token"]
        projects = client.get("/api/projects")
        projects.raise_for_status()
        if not any(item["id"] == PROJECT_ID for item in projects.json()):
            raise RuntimeError("Round53 synthetic project 18 is unavailable")

        fixtures = []
        for suffix, status in (("running", "running"), ("failed", "failed"),
                               ("waiting", "waiting_human")):
            response = client.post(f"/api/projects/{PROJECT_ID}/agent/tasks", json={
                "objective": f"{MARKER} {suffix} 状态详情与键盘交互验收",
                "scenario_key": "knowledge_question",
                "use_llm_planner": False,
                "adaptive": False,
                "auto_start": False,
                "max_retries": 1,
            })
            response.raise_for_status()
            task_id = response.json()["task"]["id"]
            with SessionLocal() as db:
                task = db.get(AgentTask, task_id)
                plan = db.scalar(select(AgentPlan).where(
                    AgentPlan.task_id == task_id,
                    AgentPlan.version_no == task.plan_version))
                step = db.scalar(select(AgentStep).where(
                    AgentStep.task_id == task_id).order_by(AgentStep.order_index, AgentStep.id))
                if task is None or plan is None or step is None:
                    raise RuntimeError("Created task is missing its persisted plan or step")
                now = datetime.now(timezone.utc)
                task.status = status
                task.current_step_key = step.step_key if status != "failed" else None
                task.error_code = "synthetic_acceptance_failure" if status == "failed" else None
                task.error_message = "隔离验收样例：此任务未执行。" if status == "failed" else None
                task.finished_at = now if status == "failed" else None
                task.started_at = now if status != "failed" else None
                task.completed_steps = 0
                task.pending_steps = 0
                task.failed_steps = 1 if status == "failed" else 0
                task.human_pending_steps = 1 if status == "waiting_human" else 0
                step.status = status
                step.started_at = now
                step.finished_at = now if status == "failed" else None
                step.attempt_count = 1
                step.error_code = task.error_code
                step.error_message = task.error_message
                if status == "waiting_human":
                    step.requires_human_confirmation = True
                    step.human_gate_key = "round65_confirmation"
                    step.input_json = {**(step.input_json or {}), "required_permission": "task.manage"}
                    step.output_summary_json = {
                        **(step.output_summary_json or {}),
                        "title": "确认分析对象",
                        "reason": "隔离验收样例，未创建真实审核记录或触发后续步骤。",
                    }
                db.commit()
                fixtures.append({
                    "task_id": task_id, "step_id": step.id, "status": status,
                    "objective": task.objective, "plan_id": plan.id,
                })

        observed = []
        for fixture in fixtures:
            detail = client.get(f"/api/agent/tasks/{fixture['task_id']}")
            detail.raise_for_status()
            body = detail.json()
            if body["task"]["status"] != fixture["status"]:
                raise RuntimeError("Synthetic state did not survive the API read model")
            observed.append({
                "task_id": fixture["task_id"], "status": body["task"]["status"],
                "step_statuses": [step["status"] for step in body["steps"]],
                "project_id": body["task"]["project_id"],
            })
    identity = version.json()
    result = {
        "round": 65, "project_id": PROJECT_ID, "source_is_synthetic": True,
        "gold": False, "holdout": False, "tasks": fixtures, "api_observations": observed,
        "api_identity": {
            "app_commit": identity.get("app_commit"),
            "build_time": identity.get("build_time"),
            "schema_head": identity.get("schema_head"),
        },
        "jobs_dispatched": 0, "worker_started": False,
        "external_provider_requests": 0, "external_provider_tokens": 0,
        "existing_tasks_modified": False, "remote_write": False,
    }
    (output / "fixtures.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                                          encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    run(args.output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

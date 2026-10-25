"""把 requirement 10 未完成的生成项重置为 pending，并重新派发一次真实生成。

背景：换掉"无法判定即阻断"的口径后，之前被 generation_validation_blocked 的两项需要重跑；
旧 worker 崩溃留下的 running 项也需要重置，否则租约永远不回。
"""
import json
import os
import sys
from pathlib import Path

from sqlalchemy import create_engine, text

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND.parent / "scripts"))
from e2e_20261024 import Client  # noqa: E402

REQUIREMENT_ID = int(os.environ.get("REQUIREMENT_ID", "10"))
ENGINE = create_engine(os.environ["DATABASE_URL"])


def retire_jobs_and_reset_items():
    with ENGINE.begin() as conn:
        input_id = conn.execute(text(
            "select id from requirement_generation_inputs where requirement_id = :rid order by id desc limit 1"
        ), {"rid": REQUIREMENT_ID}).scalar_one()
        job_id = conn.execute(text(
            "select job_id from requirement_generation_inputs where id = :iid"
        ), {"iid": input_id}).scalar()
        if job_id:
            conn.execute(text(
                "update background_jobs set idempotency_key = :key, status = 'failed', "
                "finished_at = now(), error_message = 'superseded: claim-support semantics changed', "
                "lease_owner = null, lease_expires_at = null where id = :jid and status in ('running','queued')"
            ), {"key": f"retired-{job_id}-{os.getpid()}", "jid": job_id})
        reset = conn.execute(text(
            "update requirement_generation_items set status = 'pending', lease_key = null, lease_until = null, "
            "reason_code = null, decision = 'pending', decided_by = null, decided_at = null, usage_json = '{}'::json "
            "where input_id = :iid and status in ('blocked', 'running', 'failed') returning id"
        ), {"iid": input_id})
        remaining = conn.execute(text(
            "select status, count(*) from requirement_generation_items where input_id = :iid group by status"
        ), {"iid": input_id}).fetchall()
        print(f"input_id={input_id} retired_job={job_id} reset_items={len(reset.fetchall())}")
        print("status counts:", [(r[0], r[1]) for r in remaining])
        fields = json.loads(conn.execute(text(
            "select input_json::text from requirement_generation_inputs where id = :iid"
        ), {"iid": input_id}).scalar_one())
    return input_id, fields


def main():
    input_id, fields = retire_jobs_and_reset_items()
    client = Client()
    client.login()
    body = {
        "expected_content_version": fields["content_version"],
        "field_ids": fields["field_ids"],
        "sections": fields["sections"],
        "idempotency_key": f"rerun-{input_id}-{os.getpid()}",
    }
    status, payload, _headers = client.request(
        "POST", f"/api/projects/9/requirements/{REQUIREMENT_ID}/generation-runs", json_body=body, timeout=120
    )
    print("generation-runs:", status, payload)


if __name__ == "__main__":
    main()

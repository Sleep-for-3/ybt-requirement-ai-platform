"""重派同一个生成输入（保住已完成的条目，只补跑未完成的）。

真实事故（2026-10-24，项目 9 的 T_3_8 / input 32）：celery 进程被杀掉时，
正在跑的那一条 item 已经被 claim（租约 15 分钟），进程死了但 item 还是 running；
而 `generation-runs` 的幂等键是 `requirement-input-{input_id}`，`create_or_get_job`
只按幂等键查既有行、不看状态——于是重复调用只会拿回那个死掉的 job，永远 pending。

这里做的三件事与真实语义一致，不做任何"假装完成"：
1. 把该输入的旧 job 退役（改幂等键 + 置 failed + 清租约），不删除历史；
2. 把 running / pending 的 item 重置回 pending（completed / blocked / failed 不动）；
3. 新建一个 job 并派发，让 worker 只补跑未完成的部分。

用法：
    python scripts/redispatch_input.py 32
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from sqlalchemy import select, update  # noqa: E402

from app.core.database import SessionLocal  # noqa: E402
from app.models import (  # noqa: E402
    BackgroundJob,
    Project,
    RequirementGenerationInput,
    RequirementGenerationItem,
)
from app.services.requirement_generation_worker import (  # noqa: E402
    requirement_generation_handler,
)
from app.services.task_queue import get_task_queue  # noqa: E402
from app.services.task_queue.idempotency import scoped_idempotency_key  # noqa: E402


def main(argv: list[str]) -> int:
    if len(argv) != 2 or not argv[1].isdigit():
        print("用法：python scripts/redispatch_input.py <input_id>")
        return 64
    input_id = int(argv[1])
    db = SessionLocal()
    try:
        generation_input = db.get(RequirementGenerationInput, input_id)
        if generation_input is None:
            print(f"生成输入 {input_id} 不存在")
            return 1
        key = f"requirement-input-{input_id}"
        project = db.get(Project, generation_input.project_id)
        # 真正的幂等键是 sha256("机构:项目:job_type:键")，不是明文键；
        # 直接按明文键查会一个都匹配不到（真踩过：退役 0 个、重派又拿回同一个死 job）。
        scoped = scoped_idempotency_key(
            institution_id=project.institution_id,
            project_id=generation_input.project_id,
            job_type="requirement_generation",
            idempotency_key=key,
        )
        retired = 0
        for job in db.scalars(select(BackgroundJob).where(BackgroundJob.idempotency_key == scoped)):
            job.idempotency_key = f"retired-{job.id}-{int(datetime.now(timezone.utc).timestamp())}"
            job.status = "failed"
            job.finished_at = datetime.now(timezone.utc)
            job.lease_owner = None
            job.lease_expires_at = None
            job.error_message = "重派：原 worker 已中断（租约失效）"
            retired += 1
        reset = db.execute(
            update(RequirementGenerationItem)
            .where(
                RequirementGenerationItem.input_id == input_id,
                RequirementGenerationItem.status.in_(("running", "pending")),
            )
            .values(status="pending", lease_key=None, lease_until=None, usage_json={})
        ).rowcount
        db.commit()

        # institution_id 必须来自项目：传 None 会被 handler 以
        # "Invalid institution scope" 拒掉（真踩过）。
        job = get_task_queue().enqueue(
            db,
            job_type="requirement_generation",
            institution_id=project.institution_id,
            project_id=generation_input.project_id,
            created_by=generation_input.created_by or 0,
            idempotency_key=key,
            payload_summary={"input_id": input_id},
            handler=requirement_generation_handler,
        )
        persisted = db.get(RequirementGenerationInput, input_id)
        persisted.job_id = job.id
        db.commit()
        print(f"input={input_id} 退役 {retired} 个旧 job，重置 {reset} 个条目，"
              f"新 job={job.id}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

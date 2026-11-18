"""Isolated browser acceptance worker. Never use with shared or deployed queues."""
import asyncio
import os
import sys
from dataclasses import replace

from rag_round60_inflight_governance import _configure_database


def main() -> None:
    project_id = int(sys.argv[1])
    _configure_database()
    os.environ.update(
        CELERY_BROKER_URL="redis://127.0.0.1:16392/14",
        CELERY_RESULT_BACKEND="redis://127.0.0.1:16392/15",
        REDIS_URL="redis://127.0.0.1:16392/14",
        TASK_QUEUE_PROVIDER="celery",
        LLM_PROVIDER="mock",
    )
    from app.services.agent import runtime
    from app.services.agent.tools.registry import ToolExecutionError, get_tool, register_tool
    from app.workers import celery_app

    tool = get_tool("answer_knowledge_question")
    assert tool is not None
    original_replan = runtime._replan_after_failure

    def fault_fixture(task) -> bool:
        return task.project_id == project_id and task.objective.startswith("UXDEMO controlled failure:")

    async def answer(ctx):
        if fault_fixture(ctx.task) and not ctx.task.retry_count:
            await asyncio.sleep(8)
            raise ToolExecutionError("model_unavailable", "Controlled local acceptance failure")
        return await tool.handler(ctx)

    def replan(db, task, step, code):
        # Exercise the manual retry path after no automatic fallback is available.
        if fault_fixture(task) and code == "model_unavailable":
            return False
        return original_replan(db, task, step, code)

    register_tool(replace(tool, handler=answer), replace=True)
    runtime._replan_after_failure = replan
    celery_app.worker_main(["worker", "--pool=solo", "--loglevel=INFO", "--hostname=ux-fault@localhost"])


if __name__ == "__main__":
    main()

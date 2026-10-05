"""Phase 5 acceptance: versioned evaluation dataset, annotation review, batch rerun, failure diff.

The engineering review asks for (item 5): a *versioned* evaluation dataset, an annotation review
step, a batch rerun, and a comparison of failing samples -- all exercised first with the synthetic
project rather than real bank truth.

What this script actually proves on a throw-away database:

1. a synthetic, versioned dataset is created through the real API and the platform records a
   deterministic ``dataset_version`` (content hash) in the run config;
2. changing the dataset changes that version (so a reported number can be tied to the exact inputs);
3. the same dataset is re-run (batch rerun) and per-case results are retrievable;
4. failing samples are listed and compared across the two runs, so a regression is attributable to a
   case rather than to "the score moved".

Real bank truth, thresholds and identity are explicitly out of scope and stay as acceptance
preconditions (the script prints them).
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[3] / "backend"
sys.path.insert(0, str(BACKEND))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", default="ybt_iso_phase5_eval")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5432)
    parser.add_argument("--user", default="postgres")
    parser.add_argument("--allow-reset-existing", action="store_true")
    parser.add_argument("--report", default="")
    args = parser.parse_args()

    password = os.environ.get("PGPASSWORD") or ""
    if not password:
        print(json.dumps({"ok": False, "error": "PGPASSWORD is not set"}, ensure_ascii=False))
        return 2

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "2026-10-03"))
    from isolated_pg_guard import require_isolated_target

    require_isolated_target(
        args.database, script="phase5_evaluation_dataset.py", host=args.host, port=args.port,
        user=args.user, password=password, allow_existing=args.allow_reset_existing,
    )

    url = f"postgresql+psycopg://{args.user}:{password}@{args.host}:{args.port}/{args.database}"
    os.environ["DATABASE_URL"] = url
    os.environ.setdefault("AUTH_MODE", "required")
    os.environ.setdefault("TASK_QUEUE_PROVIDER", "inline")
    os.environ.setdefault("APP_SECRET_KEY", "phase5-eval-app-secret")
    os.environ.setdefault("JWT_SECRET_KEY", "phase5-eval-jwt-secret-at-least-32-chars")
    os.environ.setdefault("VECTOR_STORE_PROVIDER", "mock")
    os.environ.setdefault("LLM_PROVIDER", "mock")
    os.environ.setdefault("EMBEDDING_PROVIDER", "mock")

    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import sessionmaker

    engine = create_engine(url)

    from app.core.database import Base
    from app.models import (  # noqa: F401 - imported so Base.metadata is populated before create_all
        Institution, InstitutionMembership, Project, ProjectMembership, RagEvaluationCase,
        RagEvaluationResult, RagEvaluationRun, User,
    )
    from app.services.auth.password import hash_password

    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    steps: list[dict] = []

    def step(name: str, **payload: object) -> None:
        record = {"step": name, **payload}
        steps.append(record)
        print(json.dumps({"phase5": record}, ensure_ascii=False), flush=True)

    with factory() as db:
        institution = Institution(institution_code="P5EVAL", institution_name="合成评测机构",
                                  institution_type="bank", status="active")
        db.add(institution)
        db.flush()
        owner = User(username="p5_eval_owner", display_name="合成-评测负责人",
                     password_hash=hash_password("Synthetic-Eval-Owner-2026!"), status="active")
        db.add(owner)
        db.flush()
        db.add(InstitutionMembership(institution_id=institution.id, user_id=owner.id,
                                     role="member", status="active"))
        project = Project(name="合成评测项目", institution_id=institution.id)
        db.add(project)
        db.flush()
        db.add(ProjectMembership(project_id=project.id, user_id=owner.id,
                                 project_role="project_manager", status="active"))
        db.commit()
        project_id = int(project.id)

    step("synthetic_eval_project", ok=True, project_id=project_id)

    # ---------------------------------------------------------------- 1. versioned dataset
    from app.services.evaluation.rag_evaluator import _dataset_version

    cases = []
    with factory() as db:
        for index in range(6):
            row = RagEvaluationCase(
                project_id=project_id,
                case_name=f"合成评测用例 {index + 1}",
                case_type="retrieval",
                query_text=f"合成查询：贷款余额口径 {index + 1}",
                expected_source_system="核心系统",
                expected_table_name="SRC_LOAN",
                # Half the cases expect a unit that the synthetic index will not return, so the
                # failure path is exercised deliberately instead of only measuring a happy path.
                expected_knowledge_unit_ids_json=[9000 + index] if index % 2 == 0 else [],
                expected_answer_keywords_json=["贷款余额"] if index % 3 == 0 else [],
                enabled=True,
            )
            db.add(row)
            db.flush()
            cases.append(row)
        db.commit()
        dataset_version = _dataset_version(cases)
        case_ids = [int(row.id) for row in cases]

    step("dataset_created", ok=len(case_ids) == 6, case_count=len(case_ids),
         dataset_version=dataset_version, case_ids=case_ids)

    # The version must be *derived from the content*, so an edited dataset cannot reuse the old
    # number. This is the "versioned dataset" requirement: a reported metric is bound to inputs.
    with factory() as db:
        rows = list(db.scalars(select(RagEvaluationCase).where(
            RagEvaluationCase.project_id == project_id,
            RagEvaluationCase.enabled.is_(True)).order_by(RagEvaluationCase.id)).all())
        before = _dataset_version(rows)
        rows[0].query_text = rows[0].query_text + "（标注复核后修订）"
        db.commit()
        rows = list(db.scalars(select(RagEvaluationCase).where(
            RagEvaluationCase.project_id == project_id,
            RagEvaluationCase.enabled.is_(True)).order_by(RagEvaluationCase.id)).all())
        after = _dataset_version(rows)
        # restore the reviewed text so the two runs compare the same dataset
        rows[0].query_text = rows[0].query_text.replace("（标注复核后修订）", "")
        db.commit()
    step("dataset_version_tracks_content", ok=before != after,
         before=before[:16], after_edit=after[:16])

    # ---------------------------------------------------------------- 2. annotation review
    # A disabled case must drop out of the dataset version, which is how "annotation review" is
    # enforced: reviewed-out samples stop influencing the reported number.
    with factory() as db:
        rows = list(db.scalars(select(RagEvaluationCase).where(
            RagEvaluationCase.project_id == project_id,
            RagEvaluationCase.enabled.is_(True)).order_by(RagEvaluationCase.id)).all())
        with_disabled = _dataset_version(rows)
        rows[-1].enabled = False
        db.commit()
        rows = list(db.scalars(select(RagEvaluationCase).where(
            RagEvaluationCase.project_id == project_id,
            RagEvaluationCase.enabled.is_(True)).order_by(RagEvaluationCase.id)).all())
        without = _dataset_version(rows)
        rows_n = len(rows)
        rows_last = db.get(RagEvaluationCase, case_ids[-1])
        rows_last.enabled = True
        db.commit()
    step("annotation_review_excludes_disabled_cases",
         ok=with_disabled != without and rows_n == 5,
         with_all=with_disabled[:16], without_disabled=without[:16], active_after=rows_n)

    # ---------------------------------------------------------------- 3. batch rerun
    def run_once(run_name: str) -> dict:
        with factory() as db:
            run = RagEvaluationRun(project_id=project_id, run_name=run_name, status="pending",
                                   retrieval_config_json={"retrieval_mode": "keyword_only", "top_k": 10})
            db.add(run)
            db.commit()
            run_id = int(run.id)
        with factory() as db:
            run = db.get(RagEvaluationRun, run_id)
            asyncio.run(_execute(db, run))
            db.refresh(run)
            results = list(db.scalars(select(RagEvaluationResult).where(
                RagEvaluationResult.evaluation_run_id == run_id).order_by(RagEvaluationResult.id)).all())
            return {
                "run_id": run_id,
                "status": run.status,
                "dataset_version": (run.retrieval_config_json or {}).get("dataset_version"),
                "metrics": run.summary_metrics_json or {},
                "cases": [
                    {"case_id": item.evaluation_case_id, "recall_at_k": item.recall_at_k,
                     "reciprocal_rank": item.reciprocal_rank, "groundedness": item.groundedness_score}
                    for item in results
                ],
            }

    first = run_once("合成评测-第一次")
    step("first_run", ok=first["status"] == "completed", run_id=first["run_id"],
         status=first["status"], dataset_version=(first["dataset_version"] or "")[:16],
         case_count=len(first["cases"]))

    second = run_once("合成评测-第二次（批量重跑）")
    step("batch_rerun", ok=second["status"] == "completed",
         run_id=second["run_id"], status=second["status"],
         dataset_version=(second["dataset_version"] or "")[:16],
         case_count=len(second["cases"]))

    same_dataset = first["dataset_version"] == second["dataset_version"]
    step("rerun_uses_the_same_dataset_version", ok=same_dataset,
         requirement="重跑必须绑定同一 dataset_version，否则分数变化无法归因")

    # ---------------------------------------------------------------- 4. failure comparison
    def failing(cases: list[dict]) -> dict[int, float]:
        return {item["case_id"]: item["recall_at_k"] for item in cases if item["recall_at_k"] < 1.0}

    f1, f2 = failing(first["cases"]), failing(second["cases"])
    step("failure_samples_compared",
         ok=len(first["cases"]) == len(second["cases"]),
         first_run_failures=len(f1), second_run_failures=len(f2),
         newly_failing=sorted(set(f2) - set(f1)),
         fixed=sorted(set(f1) - set(f2)),
         case_level_comparable=True,
         note="失败样本按 case_id 对齐比较，而不是只看总分变化")

    report = {
        "ok": all(item.get("ok") for item in steps),
        "disclaimer": "工程验收（合成数据集 + 隔离环境）；真实银行真值、阈值与身份未接入，不得当作业务准确率。",
        "acceptance_preconditions_not_met": [
            "真实银行评测真值（标注数据）与业务阈值未提供，本脚本只用合成用例验证框架可用。",
            "embedding/LLM 走 mock 或本地服务，指标不代表生产检索质量。",
        ],
        "steps": steps,
    }
    if args.report:
        Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps({"ok": report["ok"], "steps": len(steps)}, ensure_ascii=False))
    return 0 if report["ok"] else 1


async def _execute(db, run) -> None:
    """Run the real evaluator; a missing retrieval index is reported, not hidden."""
    from app.services.evaluation.rag_evaluator import run_evaluation

    try:
        await run_evaluation(db, run)
    except Exception as exc:  # noqa: BLE001 - the harness reports the real failure
        db.rollback()
        run.status = "failed"
        run.retrieval_config_json = {**(run.retrieval_config_json or {}),
                                     "harness_error": f"{type(exc).__name__}: {exc}"[:300]}
        db.commit()


if __name__ == "__main__":
    raise SystemExit(main())

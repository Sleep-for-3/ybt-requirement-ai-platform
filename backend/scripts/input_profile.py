r"""看一次生成输入到底占多少字节、钱花在哪几个键上。

真实事故（2026-10-24）：真实跑批脚本生成的需求在 `generation-inputs` 报 422
「输入字节：请求 73324 字节，上限 64000 字节」。凭"看起来不大"去猜没有意义，
必须逐键量出来，才知道该做投影还是该调预算。

用法（在 `ai-platform/backend` 下）：

    $env:PYTHONPATH="."
    .\.venv\Scripts\python.exe scripts\input_profile.py 9 10

前两个参数是 project_id 与 requirement_id。脚本只读，不改任何数据。
"""

from __future__ import annotations

import json
import sys

from app.core.database import SessionLocal
from app.models import Requirement, RequirementRevision
from app.services.mapping import requirement_input as ri


def main(project_id: int, requirement_id: int) -> int:
    db = SessionLocal()
    try:
        requirement = db.get(Requirement, requirement_id)
        if requirement is None or requirement.project_id != project_id:
            print(f"需求不存在：project={project_id} requirement={requirement_id}")
            return 1
        revision = (
            db.query(RequirementRevision)
            .filter(RequirementRevision.requirement_id == requirement_id)
            .order_by(RequirementRevision.content_version.desc())
            .first()
        )
        if revision is None:
            print("需求没有修订版本")
            return 1

        field_ids = list(revision.content_json["requirement"]["field_ids"])
        original_limit = ri.MAX_INPUT_BYTES
        ri.MAX_INPUT_BYTES = 10**9  # 只读测量：临时放开预算，否则量不到真实体积
        try:
            result = ri.build_requirement_input(db, revision, field_ids, ("business", "lineage"))
        finally:
            ri.MAX_INPUT_BYTES = original_limit

        sizes = {
            key: len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
            for key, value in result.items()
        }
        total = len(json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        print(f"content_version={revision.content_version} fields={len(field_ids)} budget={original_limit}")
        print(f"total_bytes={total}")
        for key, size in sorted(sizes.items(), key=lambda item: item[1], reverse=True):
            print(f"  {key}: {size}")

        basis = result.get("script_basis") or {}
        if isinstance(basis, dict):
            print("script_basis 明细：")
            for key, value in sorted(basis.items(), key=lambda item: len(json.dumps(item[1], ensure_ascii=False)), reverse=True):
                print(f"  {key}: {len(json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode('utf-8'))}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main(int(sys.argv[1]), int(sys.argv[2])))

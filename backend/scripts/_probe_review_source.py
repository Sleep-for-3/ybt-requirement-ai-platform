"""一次性只读勘察：打印审核/冻结相关端点实现片段。"""
from pathlib import Path

SOURCE = Path("app/api/requirements.py").read_text(encoding="utf-8")

for key in ("review-readiness", '"/review-submissions"', "finalize_review_submission"):
    index = SOURCE.find(key)
    print("=" * 20, key, index)
    print(SOURCE[max(0, index - 300) : index + 2600])
    print()

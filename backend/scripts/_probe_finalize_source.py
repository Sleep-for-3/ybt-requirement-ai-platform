"""一次性只读勘察：打印 review finalize 端点实现片段。"""
from pathlib import Path

SOURCE = Path("app/api/requirements.py").read_text(encoding="utf-8")
index = SOURCE.find("/finalize")
print("index", index)
print(SOURCE[max(0, index - 800) : index + 2600])

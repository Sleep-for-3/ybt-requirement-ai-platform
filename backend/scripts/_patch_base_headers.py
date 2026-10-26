"""一次性补丁：把 survey 渲染器的 11 个基础列名改成与客户示例完全一致的写法（去掉表头里的换行）。"""
from pathlib import Path

TARGET = Path("app/services/requirement_survey_export.py")


def main() -> None:
    text = TARGET.read_bytes().decode("utf-8").replace("\r\n", "\n")
    replacements = (
        ('"字段业务定义\\n（监管原始口径）"', '"字段业务定义（监管原始口径）"'),
        ('"字段业务定义\\n（监管定义细化）"', '"字段业务定义（监管定义细化）"'),
        ('"字段业务定义\\n（行内）"', '"字段业务定义（行内）"'),
    )
    for old, new in replacements:
        if old not in text:
            raise SystemExit(f"anchor missing: {old}")
        text = text.replace(old, new, 1)
    TARGET.write_bytes(text.replace("\n", "\r\n").encode("utf-8"))
    print("patched", TARGET)


if __name__ == "__main__":
    main()

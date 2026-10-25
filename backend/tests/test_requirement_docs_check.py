"""交付文档结构检查器自身的测试（离线、不连库）。

两类断言：
1. 真实的 `docs/requirement-delivery-upgrade/` 五份文档必须通过结构检查——
   防止后续追加轮次时再出现"章节编号重复 / 层级写错 / §引用指向不存在的章节"。
2. 检查器确实能抓到这三类问题（用临时目录造坏样本），避免它退化成永远返回 0。
"""

from __future__ import annotations

import importlib.util
import sys
import textwrap
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_DIR = BACKEND_DIR.parent
CHECKER_PATH = REPO_DIR / "scripts" / "requirement_docs_check.py"
DOCS_DIR = REPO_DIR / "docs" / "requirement-delivery-upgrade"


def _load_checker():
    spec = importlib.util.spec_from_file_location("requirement_docs_check", CHECKER_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    # dataclass 在 `from __future__ import annotations` 下要靠 sys.modules 解析字符串注解，
    # 不注册就直接 exec 会报 AttributeError: 'NoneType' object has no attribute '__dict__'
    sys.modules.setdefault("requirement_docs_check", module)
    spec.loader.exec_module(module)
    return module


_CHECKER = None


def checker_module():
    global _CHECKER
    if _CHECKER is None:
        _CHECKER = _load_checker()
    return _CHECKER


@pytest.fixture(scope="module")
def checker():
    assert CHECKER_PATH.is_file(), f"检查器不存在：{CHECKER_PATH}"
    return checker_module()


def _write_docs(root: Path, **files: str) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    # 检查器要求五份文档齐全，没给的那几份补最小占位，避免"文档不存在"掩盖真正的断言
    for name in checker_module().DOC_NAMES:
        if name not in files:
            (root / name).write_text("## 1. 占位\n内容\n", encoding="utf-8")
    for name, body in files.items():
        (root / name).write_text(textwrap.dedent(body).lstrip(), encoding="utf-8")
    return root


def test_real_delivery_docs_pass_structure_check(checker) -> None:
    assert DOCS_DIR.is_dir(), f"交付文档目录不存在：{DOCS_DIR}"
    issues, parsed = checker.check(DOCS_DIR)
    assert parsed, "没有解析到任何文档"
    assert issues == [], "交付文档存在结构问题：\n" + "\n".join(issues)


def test_checker_detects_duplicate_section_numbers(checker, tmp_path: Path) -> None:
    docs = _write_docs(
        tmp_path / "dup",
        **{
            "plan.md": """\
            ## 1. 甲
            内容
            ## 1. 乙
            内容
            """,
        },
    )
    issues, _ = checker.check(docs)
    assert any("重复" in issue for issue in issues), issues


def test_checker_detects_missing_reference_target(checker, tmp_path: Path) -> None:
    docs = _write_docs(
        tmp_path / "ref",
        **{
            "plan.md": """\
            ## 1. 甲
            见 `evidence-index.md` §9。
            """,
            "evidence-index.md": """\
            ## 1. 只有一节
            内容
            """,
        },
    )
    issues, _ = checker.check(docs)
    assert any("§9 不存在" in issue for issue in issues), issues


def test_checker_detects_depth_mistake(checker, tmp_path: Path) -> None:
    docs = _write_docs(
        tmp_path / "depth",
        **{
            "checkpoint.md": """\
            ## 1. 甲
            内容
            ### 7. 被写成三级标题的顶级章节
            内容
            """,
        },
    )
    issues, _ = checker.check(docs)
    assert any("三级标题写成顶级编号" in issue for issue in issues), issues


def test_checker_resolves_reference_to_other_document(checker, tmp_path: Path) -> None:
    docs = _write_docs(
        tmp_path / "cross",
        **{
            "plan.md": """\
            ## 1. 甲
            见 `final-report.md` §2 与 §3。
            """,
            "final-report.md": """\
            ## 1. 甲
            内容
            ## 2. 乙
            内容
            ## 3. 丙
            内容
            """,
        },
    )
    issues, _ = checker.check(docs)
    assert issues == [], issues

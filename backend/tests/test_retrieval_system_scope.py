"""Reporting-system recognition (nightly task, package C).

The conversion Q&A rows for EAST and 1104 share the same data item and nearly
the same wording, so a single-system question used to rank the other system's
row first. These tests pin detection and unit labelling; the ranking effect is
verified by the replay script (`stale_index_probe` and per-case ranks).
"""

from app.services.retrieval.query_expansion import detect_systems, unit_system


def test_detect_systems_recognises_single_system_questions():
    assert detect_systems("EAST 的其他自定义合作方式怎么转成一表通码值？") == {"east", "ybt"}
    assert detect_systems("1104 表里合作方式的码值怎么设置？") == {"1104"}
    assert detect_systems("一表通 F250007 的码值规则是什么？") == {"ybt"}


def test_detect_systems_recognises_cross_system_questions():
    assert detect_systems("互联网贷款合作方式在 EAST 和 1104 转换中分别有哪些码值设置问题？") == {"east", "1104"}
    assert detect_systems("EAST 与 1104 的口径差异") == {"east", "1104"}


def test_detect_systems_returns_empty_for_unscoped_questions():
    assert detect_systems("合作方式有哪些码值？") == set()
    assert detect_systems("合作机构类型有哪些？") == set()
    assert detect_systems("") == set()


def test_unit_system_prefers_sheet_then_question_id():
    assert unit_system("转EAST问答", "问题编号：EAST_2024091200044") == "east"
    assert unit_system("转1104问答", "问题编号：1104_2024051000013") == "1104"
    assert unit_system("一表通制度问答", "问题编号：YBZD_2024080900154") == "ybt"
    # Sheet missing from metadata: fall back to the question id prefix.
    assert unit_system(None, "流程状态：已办结；问题编号：EAST_2024091200044") == "east"
    assert unit_system(None, "问题编号：1104_2024051000013") == "1104"
    assert unit_system(None, "问题编号：YBZD_2024080900154") == "ybt"


def test_unit_system_returns_none_when_no_system_is_known():
    assert unit_system(None, "合作方式按 01-10 报送") is None
    assert unit_system("", "") is None

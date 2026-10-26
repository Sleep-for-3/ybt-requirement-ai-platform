from pathlib import Path

p = Path("tests/test_retrieval_query_expansion.py")
t = p.read_text(encoding="utf-8")
t = t.replace(
    "from app.services.retrieval.query_expansion import (\n    SYNONYM_GROUPS,\n    expand_query,\n    matched_scenarios,\n)\n",
    "from app.services.retrieval.query_expansion import (\n    INTENT_RULES,\n    INTENT_TYPES,\n    SYNONYM_GROUPS,\n    detect_intent,\n    expand_query,\n    matched_scenarios,\n)\n",
)
extra = '''

def test_detect_intent_prefers_processing_over_regulatory():
    assert detect_intent("E010005 科目类型 的加工逻辑是什么") == "processing"
    assert detect_intent("这个字段来自哪个系统、哪张表") == "lineage"
    assert detect_intent("借记卡场景下这个字段的业务口径") == "scenario"
    assert detect_intent("产品ID 的监管口径原文") == "regulatory"
    assert detect_intent("T_5_1 有哪些字段") is None


def test_intent_types_cover_every_rule():
    assert set(INTENT_TYPES) == {intent for intent, _ in INTENT_RULES}
    assert {kind for kind, _ in INTENT_TYPES.values()} <= {
        "field_explanation",
        "business_research",
        "technical_research",
    }
'''
if "test_detect_intent_prefers_processing_over_regulatory" not in t:
    t += extra
    p.write_text(t, encoding="utf-8")
    print("tests updated")
else:
    print("already updated")

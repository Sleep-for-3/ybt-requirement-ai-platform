"""P2-A 运行事实断言进入候选主张校验（claim-support-v1 的 runtime_fact 扩展）。

事实包在导入时冻结，`allowed_level` 已由 `claim_allowed` 决定。这里固定三条边界：

1. 事实达到要求级别时，运行事实主张可以被判为 supported；
2. 事实低于要求级别（只能当静态推断）时，任何"运行验证"表述都必须判 conflict，
   不能因为事实包里"有这一项"就算已支持；
3. 没有事实包 / 事实包里没有该项时，判 unknown（需要人确认或补资料），不得判 supported。
"""
from app.services import requirement_claim_support as claim_support


def runtime_context(facts, *, section="business", verified=True):
    return {
        "section": section,
        "runtime_facts": {
            "fact_pack_id": 7,
            "pack_sha256": "a" * 64,
            "level": "full_run_validation",
            "status": "verified",
            "verified": verified,
            "frozen_at_import": True,
            "facts": facts,
        },
    }


def fact(name, allowed="full_run_validation", required=None):
    return {
        "fact": name,
        "required_level": required or "full_run_validation",
        "declared_level": allowed,
        "allowed_level": allowed,
    }


def claim(kind="runtime_fact", text="本字段主键唯一率 100%，可直接作为唯一性依据。",
          supports=None):
    # 主张必须登记支持项，否则与其它主张一样被记为「无支持项」；运行事实主张的
    # 支持项来源是 runtime_fact，ref_id 用事实键。
    if supports is None:
        supports = [{"source": "runtime_fact", "ref_id": "key_uniqueness", "status": "supported"}]
    return {
        "claim_id": "claim-1",
        "section": "business",
        "text": text,
        "assertion_kind": kind,
        "support": list(supports),
    }


def evaluate(context, claims):
    report = claim_support.evaluate_claim_support(context, {"claims": claims})
    return report


def test_full_run_fact_supports_runtime_claim():
    context = runtime_context([fact("key_uniqueness")])
    report = evaluate(context, [claim()])

    assert report.status == "supported"
    assert report.conflict_count == 0
    assert report.evaluations[0].status == "supported"
    assert report.evaluations[0].assertion_kind == "runtime_fact"


def test_fact_below_required_level_blocks_run_verified_wording():
    context = runtime_context(
        [fact("key_uniqueness", allowed="static_inference")], verified=False,
    )
    report = evaluate(context, [claim()])

    assert report.status == "conflict"
    assert "runtime_fact_level_insufficient" in report.evaluations[0].codes
    assert any("static_inference" in finding.message and "full_run_validation" in finding.message
               for finding in report.findings)
    assert report.violations


def test_missing_fact_pack_is_unknown_not_supported():
    report = evaluate({"section": "business"}, [claim(supports=[])])

    assert report.status == "unknown"
    assert "runtime_fact_unavailable" in report.evaluations[0].codes
    # unknown 也会进入 violations（阻断送审、要求人工确认），但不得记成"确定冲突"。
    assert report.conflict_count == 0
    assert all("无法确定性校验" in item for item in report.violations)


def test_unrelated_wording_is_unknown_and_named():
    context = runtime_context([fact("key_uniqueness")])
    report = evaluate(context, [claim(text="该字段按业务口径加工。")])

    assert report.status == "unknown"
    assert "runtime_fact_unspecified" in report.evaluations[0].codes


def test_fact_absent_from_pack_is_unknown():
    context = runtime_context([fact("key_uniqueness")])
    report = evaluate(context, [claim(text="分组对账完全一致。", supports=[])])

    assert report.status == "unknown"
    assert "runtime_fact_missing" in report.evaluations[0].codes


def test_support_ref_outside_pack_is_conflict():
    context = runtime_context([fact("key_uniqueness")])
    report = evaluate(context, [claim(supports=[{
        "source": "runtime_fact", "ref_id": "row_count_total", "status": "supported",
    }])])

    assert report.status == "conflict"
    assert "runtime_fact_reference_out_of_scope" in report.evaluations[0].codes


def test_support_ref_inside_pack_does_not_add_violation():
    context = runtime_context([fact("key_uniqueness")])
    report = evaluate(context, [claim(supports=[{
        "source": "runtime_fact", "ref_id": "key_uniqueness", "status": "supported",
    }])])

    assert report.status == "supported"
    assert report.violations == []


def test_candidate_without_claims_stays_not_evaluated():
    report = claim_support.evaluate_claim_support({"section": "business"}, {})

    assert report.status == "not_evaluated"
    assert report.violations == []


def test_other_claim_kinds_are_not_hijacked_by_runtime_aliases():
    """业务日期是需求常见术语，不得让 filter/as_of_date 类主张被运行事实校验接管。"""
    context = runtime_context([fact("business_date", allowed="static_inference")], verified=False)
    report = evaluate(context, [claim(kind="as_of_date",
                                      text="统计口径取业务日期当日余额。")])

    assert "runtime_fact_level_insufficient" not in report.evaluations[0].codes

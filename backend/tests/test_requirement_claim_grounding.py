"""证据接地（grounding）校验的定向测试。

真实事故背景（round 75）：T_5_1 批次候选把证据原文几乎逐字抄进正文，但断言类型多为
``other``、且候选自述 support.status=unknown，于是 100% 主张被判 unknown —— 报告"正确
但无用"，人工复核看不出哪条主张其实有证据支撑。

本组测试锁定新增的接地语义：
1. 逐字抄自所引证据 → supported，并带 ``evidence_grounding_verified`` 与覆盖率说明；
2. 与所引证据文本无关 → 仍 unknown（不能凭空放行）；
3. 主张否定证据 → 不放行；
4. 引用了不在固定输入里的证据 → 不放行（evidence_missing 不在可取代集合的边界之外）；
5. 文本覆盖率不足阈值 → 不放行；
6. 报告状态与计数随接地结果一致。
"""
from app.services import requirement_claim_support as claim_support

EVIDENCE_TEXT = (
    "数据项编码：E010002；数据项名称：机构ID；监管定义：按照既定规则生成分配给实际业务经办"
    "最小单位机构的唯一编码。生成规则为：使用长度不超过24位的数字与字母组合，前11位与金融"
    "许可证号前11位相同，后13位使用内部机构号，不足部分不用补齐。"
)
CLAIM_TEXT = (
    "按照既定规则生成分配给实际业务经办最小单位机构的唯一编码，使用长度不超过24位的数字与"
    "字母组合，前11位与金融许可证号前11位相同，后13位使用内部机构号。"
)


def evidence_unit(unit_id=23, content=EVIDENCE_TEXT):
    return {
        "unit_id": unit_id,
        "document_id": 4,
        "document_version_id": 8,
        "content_hash": f"hash-{unit_id}",
        "content": content,
        "title": "T_5_1 监管口径与字段画像",
        "confidentiality_level": "internal",
        "source_category": "regulatory_formal",
        "regulatory_version": "20261024",
        "lifecycle_status": "active",
        "locator": {"row_no": 2, "sheet_name": "监管口径", "cell_range": "A2:I2"},
    }


def context(units=None, section="business"):
    return {
        "section": section,
        "evidence": units if units is not None else [evidence_unit()],
        "script_basis": {"rules": [], "condition_texts": {}, "metadata": []},
        "physical_sources": [],
        "mapping_sources": [],
        "requirement": {},
        "pinned_versions": {},
    }


def support(ref_id="23", status="unknown"):
    return [{
        "source": "evidence",
        "ref_id": ref_id,
        "status": status,
        "method": "deterministic_fact_match",
        "method_version": "claim-support-v1",
    }]


def candidate(text, kind="other", ref_id="23", status="unknown", evidence_ids=(23,)):
    return {
        "final_content": text,
        "evidence_unit_ids": list(evidence_ids),
        "script_rule_ids": [],
        "claims": [{
            "claim_id": "C1",
            "section": "business",
            "text": text,
            "assertion_kind": kind,
            "support": support(ref_id, status),
        }],
    }


def evaluate(text, **kwargs):
    ctx = context(units=kwargs.pop("units", None))
    return claim_support.evaluate_claim_support(ctx, candidate(text, **kwargs))


def codes(report):
    return [code for evaluation in report.evaluations for code in evaluation.codes]


def test_claim_copied_from_cited_evidence_is_supported():
    report = evaluate(CLAIM_TEXT)
    assert report.status == "supported"
    assert report.supported_count == 1
    assert report.unknown_count == 0
    assert "evidence_grounding_verified" in codes(report)
    message = report.evaluations[0].message
    assert "字符二连覆盖" in message
    assert "文本级核对" in message
    assert "不代表业务结论已经业务确认" in message
    # 接地是取代"无法校验"，不是新增 finding：findings 必须为空。
    assert report.findings == []


def test_unrelated_claim_stays_unknown():
    report = evaluate("该字段用于统计客户在本行的所有信用卡透支余额，并按月汇总报送。")
    assert report.status == "unknown"
    assert report.supported_count == 0
    assert "evidence_grounding_verified" not in codes(report)
    assert any(finding.status == "unknown" for finding in report.findings)


def test_negated_claim_is_not_grounded():
    report = evaluate(
        "按照既定规则生成分配给实际业务经办最小单位机构的唯一编码，但前11位与金融许可证号前11位"
        "并不相同，后13位也不使用内部机构号。"
    )
    assert report.status == "unknown"
    assert "evidence_grounding_verified" not in codes(report)


def test_claim_citing_missing_evidence_is_not_grounded():
    # 引用不在固定输入里的证据：既有规则判 conflict（越界），接地不得覆盖它。
    report = evaluate(CLAIM_TEXT, ref_id="999", evidence_ids=(999,))
    assert report.status == "conflict"
    assert report.conflict_count == 1
    assert "evidence_grounding_verified" not in codes(report)


def test_partial_overlap_below_threshold_is_not_grounded():
    # 只有开头一句来自证据，其余是无关内容，覆盖率明显低于 0.75。
    report = evaluate(
        "按照既定规则生成分配给实际业务经办最小单位机构的唯一编码。此外该字段还用于反洗钱"
        "可疑交易监测、信贷资产五级分类迁移矩阵，以及每月末对账时的差异归集和人工补录。"
    )
    assert report.status == "unknown"
    assert "evidence_grounding_verified" not in codes(report)


def test_report_counts_follow_grounding():
    ctx = context(units=[evidence_unit(), evidence_unit(unit_id=24, content="另一条与主张无关的政策原文。")])
    payload = candidate(CLAIM_TEXT)
    payload["claims"].append({
        "claim_id": "C2",
        "section": "business",
        "text": "该字段用于统计客户在本行的所有信用卡透支余额，并按月汇总报送。",
        "assertion_kind": "other",
        "support": support("24", "unknown"),
    })
    payload["evidence_unit_ids"] = [23, 24]
    report = claim_support.evaluate_claim_support(ctx, payload)
    assert report.claim_count == 2
    assert report.supported_count == 1
    assert report.unknown_count == 1
    assert report.status == "unknown"

"""Build synthetic fixed-revision examples only; never open an existing DB."""
from copy import deepcopy
import json
import os
from pathlib import Path
import sys

os.environ["DATABASE_URL"] = "sqlite:///:memory:"
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
from app.core.settings import Settings
Settings.model_config["env_file"] = None
from app.services.requirement_scope import content_digest, export_document
from app.services.requirement_word import export_word
from app.services.requirement_policy_comparison import basis_hash


def sample(multilayer=False):
    tables = [("ods", "accounts", "贴源层"), ("dwd", "account_balance", "明细层"), ("reg", "report", "监管报送表")]
    if not multilayer:
        tables.pop(1)
    content = {"requirement": {"id": 1, "project_id": 1, "version": 1, "content_version": 3,
        "name": "隔离银行多层路径样本" if multilayer else "隔离银行直接报送样本", "target_table_id": 1,
        "scenario_id": 1, "field_ids": [11], "document_ids": [1], "source_table_ids": [], "mart_table_ids": [],
        "background": "核验固定需求文档的字段说明和证据展示。", "objective": "由业务人员核验本金报送口径。",
        "inclusion": "期末有效账户的本金余额", "exclusion": "不包含利息和核销账户", "effective_date": "2026-09-17"},
        "target_table": {"id": 1, "table_code": "YBT_ACCOUNT", "table_name": "账户报送表"},
        "fields": [{"field": {"id": 11, "field_code": "AMOUNT", "field_name": "期末本金余额", "field_type": "DECIMAL(18,2)"},
            "business": {"business_definition": "期末仍有效账户的本金余额。", "final_content": "按期末本金原值报送。"},
            "lineage": {"source_system_name": "隔离核心业务系统", "processing_logic": "当前脚本放大余额，需要修订。",
                "final_content": "脚本事实与制度原值要求存在差异，暂不能形成正式交付。"},
            "mart_mappings": [], "source_mappings": {}, "evidence": []}], "resources": [],
        "gaps": [{"id": "sample:conflict", "field_id": 11, "origin": "analysis", "status": "open",
                  "message": "脚本乘以二与制度原值报送要求冲突，待修订实现及业务验收要求。"}],
        "status": "draft", "assessment": "gaps", "manual_ownership": {"11": {"business.final_content": {"kind": "manual", "actor_id": 501}}}}
    versions, rules = [], []
    for index, (source, target) in enumerate(zip(tables, tables[1:]), 1):
        versions.append({"id": index, "script_file_id": index, "version_no": 1,
            "path": f"sample_step_{index}.sql", "file_hash": str(index) * 64, "parse_status": "parsed"})
        def node(table):
            return {"database_name": "sample_bank", "schema_name": table[0], "table_name": table[1], "column_name": "amount"}
        rules.append({"rule_id": f"sample-rule-{index}", "script_version_id": index, "statement_id": index,
            "source_line_start": 1, "source_line_end": 4, "source": node(source), "target": node(target),
            "transformation_expression": "a.amount * 2" if index == 1 else "a.amount",
            "join_condition": "a.account_id = c.account_id", "filter_condition": "c.status = 'ACTIVE'",
            "aggregation_rule": None, "code_mapping_rule": None})
    basis = {"versions": versions, "statements": [], "rules": rules, "confirmation": {"target_table_id": 1},
        "metadata": [{"database_name": "sample_bank", "schema_name": t[0], "table_name": t[1],
            "assignment": {"layer_name": t[2], "business_system_id": 101}} for t in tables],
        "template": {"id": 1, "version_no": 1, "regulatory_version": "隔离样本版本"},
        "policy_snapshot": {"evidence": [{"unit_id": 1, "document_id": 1, "document_version_id": 1,
            "title": "本金口径样本条款", "regulatory_version": "隔离样本版本", "source_category": "regulatory_formal",
            "content": "期末本金余额应按原值报送。不得通过未经业务确认的倍数加工改变报送值。"}]}}
    content["script_basis"] = basis
    content["policy_comparisons"] = {"basis_hash": basis_hash(basis), "decisions": {"1": {
        "unit_id": 1, "rule_ids": [r["rule_id"] for r in rules], "status": "conflict",
        "rationale": "核对条款原值要求与脚本乘法表达式。", "difference": "脚本将期末本金乘以二，偏离制度原值口径。",
        "confirmed_by": 501, "confirmed_at": "2026-09-17T00:00:00+00:00"}}}
    return content


if __name__ == "__main__":
    output = Path(sys.argv[1]).resolve()
    output.mkdir(parents=True, exist_ok=False)
    manifest = []
    for name, multi in (("direct-draft", False), ("multilayer-draft", True)):
        content = sample(multi)
        original = deepcopy(content)
        (output / f"{name}.docx").write_bytes(export_word(content))
        (output / f"{name}.xlsx").write_bytes(export_document(content))
        assert content == original
        manifest.append({"sample": name, "content_version": 3, "snapshot_hash": content_digest(content),
                         "status": "synthetic_draft", "visual_review": "pending"})
    (output / "version-evidence.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"ARTIFACT_ROOT={output}")

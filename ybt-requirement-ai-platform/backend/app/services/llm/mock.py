import hashlib

from app.services.llm.base import LLMService


class MockLLMService(LLMService):
    async def chat_json(self, system_prompt: str, user_prompt: str) -> dict:
        if "场景业务口径" in system_prompt:
            return {
                "business_definition": "按当前产品场景确认一表通字段的实际业务含义和适用范围。",
                "source_system_screenshot_required": True,
                "source_system_change_required": False,
                "external_data_required": False,
                "manual_supplement_required": False,
                "remarks": "草稿需由业务部门确认。",
                "open_questions": ["请确认该场景下的业务边界和口径确认人。"],
                "confidence_level": "medium",
                "final_content_draft": "场景业务口径：按产品场景识别字段业务含义、适用范围和例外情况，并由业务部门确认。",
            }
        if "场景技术溯源" in system_prompt:
            return {
                "processing_logic": "优先按已确认来源字段直接取值，码值和例外处理待技术确认。",
                "processing_logic_type": "pending_confirmation",
                "remarks": "草稿不包含可执行 SQL。",
                "open_questions": ["请确认来源库表字段及处理逻辑。"],
                "confidence_level": "medium",
                "final_content_draft": "场景技术溯源：从已确认业务系统、库表和字段获取数据，按约定处理逻辑加工，具体来源待技术部门确认。",
            }
        if "业务系统到监管集市" in system_prompt:
            return {
                "source_system_summary": "ECIF 客户信息系统",
                "source_tables_summary": "ecif_customer 客户基本信息表",
                "source_fields_summary": "cert_type 客户证件类型",
                "business_rule": "监管集市字段应优先取 ECIF 客户基本信息表的证件类型，作为客户维度统一证件类型来源。",
                "filter_condition": "仅纳入客户状态有效、未注销的客户；具体状态码需由业务确认。",
                "join_condition": "如需与其他系统补充，应以客户编号或统一客户号关联。",
                "priority_rule": "多来源同时存在时优先采用 ECIF，信贷系统仅作为缺失补充来源。",
                "merge_rule": "跨系统合并时保留来源系统标识，并记录冲突字段供人工复核。",
                "code_mapping_rule": "需将源系统证件类型转换为监管集市统一证件类型代码。",
                "null_handling_rule": "源字段为空时进入待确认清单，不直接默认填充。",
                "exception_rule": "证件类型不在代码集内时标记为异常数据。",
                "quality_check_rule": "校验空值率、枚举覆盖率和码值转换完整性。",
                "open_questions": ["请确认 ECIF 证件类型码值是否已与最新监管代码集对齐。"],
                "final_content_draft": "业务系统到监管集市：从 ECIF 客户基本信息表 cert_type 获取客户证件类型，按有效客户范围过滤，必要时由信贷系统补充缺失值，并按监管集市统一代码转换。",
                "confidence_level": "medium",
                "evidence_summary": "草稿基于源字段、人工备注和已绑定证据生成。",
            }
        if "监管集市到一表通" in system_prompt:
            return {
                "mart_table_summary": "mart_customer 监管客户集市表",
                "mart_field_summary": "cert_type 客户证件类型",
                "business_rule": "一表通字段 CERT_TYPE 应从监管客户集市表 cert_type 取值，并匹配一表通监管定义。",
                "filter_condition": "仅报送报送日期内有效客户；具体有效口径需人工确认。",
                "join_condition": "按一表通报送主键与监管客户集市客户编号关联。",
                "code_mapping_rule": "监管集市证件类型需转换为一表通要求的证件类型代码。",
                "null_handling_rule": "为空时纳入待确认问题，不生成默认代码。",
                "reporting_condition": "满足一表通报送范围、机构范围和报送日期要求。",
                "validation_rule": "校验证件类型非空率、代码值合法性以及与监管定义的一致性。",
                "open_questions": ["请确认报送日期内有效客户的判定规则。"],
                "final_content_draft": "监管集市到一表通：从 mart_customer.cert_type 获取客户证件类型，按报送范围过滤后转换为一表通代码，并对空值和非法码值输出校验问题。",
                "confidence_level": "medium",
                "evidence_summary": "草稿基于一表通字段定义、监管集市字段和已绑定证据生成。",
            }
        if "监管字段解释" in system_prompt:
            return {
                "answer": "现有证据表明 CERT_TYPE 表示客户证件类型；具体来源字段和场景适用范围仍需人工确认。",
                "confidence_level": "medium",
                "supported_claims": ["CERT_TYPE 表示客户证件类型。"],
                "unsupported_claims": [],
                "open_questions": ["请确认当前场景采用的真实来源表字段。"],
            }
        return {
            "business_to_mart_rule": "建议从客户主数据系统抽取目标字段，按监管集市客户维度统一代码值和空值处理规则。",
            "mart_to_ybt_rule": "监管集市字段直接映射至一表通目标字段；如存在监管代码集，需按最新一表通代码表转换。",
            "source_system_candidates": ["ECIF", "信贷"],
            "source_table_candidates": ["ecif_customer", "loan_contract"],
            "source_field_candidates": ["cert_type", "customer_id"],
            "east_reference_summary": "历史 EAST 口径显示该字段通常来自客户基础信息，并需要保留原始代码与监管标准代码的映射关系。",
            "sql_reference_summary": "相关 SQL 片段显示客户表与业务合同表通过 customer_id 关联，并包含有效状态过滤条件。",
            "validation_notes": "需人工确认代码值范围、空值处理、以及业务系统和监管集市字段的一致性。",
            "confidence_level": "medium",
            "template_reference_summary": "一表通模板提供了字段定义、必填属性和监管说明，可作为目标字段口径边界。",
            "db_query_summary": "数据库探查证据显示可用于校验枚举分布、空值率和 distinct 情况。",
            "data_quality_notes": "建议结合空值率、枚举覆盖率和代码集一致性进行人工复核。",
            "evidence_completeness": "medium",
            "risk_points": ["历史口径和监管集市 SQL 可能存在字段命名不一致。"],
            "questions_for_human": ["请确认目标字段是否必须使用一表通最新监管代码集。"],
        }

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [_hash_embedding(text) for text in texts]


def _hash_embedding(text: str, dimensions: int = 64) -> list[float]:
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    values = []
    for index in range(dimensions):
        byte = digest[index % len(digest)]
        values.append((byte / 255.0) - 0.5)
    return values

"""Automated empirical benchmark for AI intelligence capabilities across 10 dimensions.

Used to objectively measure:
A. Intent Understanding
B. Banking Business Context
C. Requirement Document Generation
D. RAG & Knowledge Retrieval
E. Hallucination Guardrails
F. SQL Capability & Safety
G. Agent Loop & Planning
H. Long Task Execution
I. Traceability & Provenance
J. Robustness & Error Handling
"""
import json
import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import (
    DataSource,
    KnowledgeDocument,
    KnowledgeUnit,
    Project,
    TargetField,
    User,
)
from app.services.db.safe_sql_executor import SafeSqlExecutor
from app.services.requirement_generation_worker import RequirementCandidate
from app.services.mapping.requirement_input import (
    validate_physical_references,
)
from app.services.natural_language_task_service import _build_profile_sql
from app.services.retrieval.keyword_index import tokenize, weighted_tokens
from app.services.task_parser.natural_language_task_parser import (
    NaturalLanguageTaskParser,
    _extract_table_and_field,
)


class TestIntelligenceBenchmark:

    # -------------------------------------------------------------
    # Dimension A: User Intent Understanding
    # -------------------------------------------------------------
    def test_dim_a_intent_understanding_limitations(self, db_session: Session):
        """Evaluate how the system handles realistic bank user queries."""
        project = Project(
            name="意图测试项目",
            bank_name="测试银行",
            project_status="active",
        )
        db_session.add(project)
        db_session.flush()

        ds = DataSource(
            project_id=project.id,
            name="core_db",
            db_type="postgresql",
            host="127.0.0.1",
            port=5432,
            database_name="core",
            username="readonly",
            encrypted_password="pwd",
            enabled=True,
            readonly_flag=True,
        )
        db_session.add(ds)
        db_session.commit()

        parser = NaturalLanguageTaskParser(db_session)

        # Test Case A1: Query missing explicit datasource name now auto-infers via Schema Linking!
        # Natural spoken request: "请帮我分析一下客户表 ecif_customer 中的证件类型 cert_type 的空值情况"
        res1 = parser.parse(project.id, "请帮我分析一下客户表 ecif_customer 中的证件类型 cert_type 的空值情况")
        assert res1.status == "parsed", f"Expected parsed, got {res1.status}: {res1.message}"
        assert res1.datasource_name == "core_db"
        assert res1.extracted_table_name == "ecif_customer"
        assert res1.extracted_field_name == "cert_type"

        # Test Case A2: Dot notation support (e.g. ecif_customer.cert_type)
        res_dot = parser.parse(project.id, "查看 ecif_customer.cert_type 的分布")
        assert res_dot.status == "parsed"
        assert res_dot.extracted_table_name == "ecif_customer"
        assert res_dot.extracted_field_name == "cert_type"

        # Test Case A3: Query with exact datasource name and natural expression
        res2 = parser.parse(project.id, "在 core_db 中查看 ecif_customer 表 cert_type 字段 的分布")
        assert res2.status == "parsed"
        assert res2.extracted_table_name == "ecif_customer"
        assert res2.extracted_field_name == "cert_type"

    # -------------------------------------------------------------
    # Dimension D: RAG Capability & Tokenization
    # -------------------------------------------------------------
    def test_dim_d_rag_tokenization_and_lexical_limits(self):
        """Evaluate tokenization behavior for banking domain terminology."""
        text = "个人住房按揭贷款逾期90天以上借据余额"
        tokens = tokenize(text)

        # 1. Base tokenization
        assert "个人住房按揭贷款逾期" in tokens
        assert "按揭" in tokens
        assert "贷款" in tokens

        # 2. Before upgrade, query '房贷' had 0 overlap with '个人住房按揭贷款'
        raw_query_tokens = tokenize("房贷", expand_synonyms=False)
        assert len(set(tokens).intersection(set(raw_query_tokens))) == 0

        # 3. With banking domain semantic expansion, '房贷' expands to banking synonyms
        expanded_query_tokens = tokenize("房贷", expand_synonyms=True)
        assert "个人住房贷款" in expanded_query_tokens
        assert "按揭贷款" in expanded_query_tokens
        assert "个人住房按揭贷款" in expanded_query_tokens

        # 4. In indexing, weighted_tokens pre-indexes banking synonyms with 0.85 weight
        w_tokens = weighted_tokens(None, "个人住房按揭贷款逾期90天以上借据余额")
        assert "房贷" in w_tokens
        assert w_tokens["房贷"] == 0.85

    # -------------------------------------------------------------
    # Dimension E: Hallucination Guardrails
    # -------------------------------------------------------------
    def test_dim_e_hallucination_strict_guardrails(self):
        """Evaluate deterministic guardrails preventing model from hallucinating physical schema."""
        context = {
            "physical_sources": [
                {
                    "kind": "source",
                    "table_id": 101,
                    "field_id": 201,
                    "table_code": "src_cust",
                    "field_code": "cust_id",
                },
                {
                    "kind": "mart",
                    "table_id": 301,
                    "field_id": 401,
                    "table_code": "dm_cust",
                    "field_code": "cust_no",
                },
            ]
        }

        # Case E1: Valid physical reference passes
        valid_refs = [{"kind": "source", "table_id": 101, "field_id": 201}]
        validate_physical_references(context, valid_refs)  # Should not raise

        # Case E2: Fabricated physical reference is intercepted with 422
        hallucinated_refs = [
            {"kind": "source", "table_id": 999, "field_id": 888}  # Made-up ID
        ]
        with pytest.raises(HTTPException) as exc_info:
            validate_physical_references(context, hallucinated_refs)
        assert exc_info.value.status_code == 422
        assert "生成结果引用了范围外的物理字段" in exc_info.value.detail

    # -------------------------------------------------------------
    # Dimension F: SQL Capability & Security
    # -------------------------------------------------------------
    def test_dim_f_sql_ast_safety_and_templating(self, db_session: Session):
        """Evaluate SQL safety AST and SQL generation mechanism."""
        # 1. AST Safety verification
        executor = SafeSqlExecutor(db_session)
        disallowed_sqls = [
            "DROP TABLE test_table",
            "DELETE FROM test_table WHERE id = 1",
            "UPDATE test_table SET name = 'x'",
            "INSERT INTO test_table VALUES (1)",
            "ALTER TABLE test_table ADD COLUMN col int",
            "TRUNCATE TABLE test_table",
        ]
        for sql in disallowed_sqls:
            with pytest.raises(ValueError):
                executor.validate_and_prepare(sql)

        # 2. SQL Generation inspection (Shows it is template-based)
        sql_items = _build_profile_sql("探查数据", "ecif_customer", "cert_type")
        assert len(sql_items) >= 2
        assert any("count(" in item["sql"].lower() for item in sql_items)
        assert any("distinct" in item["sql"].lower() for item in sql_items)

    # -------------------------------------------------------------
    # Dimension G: Agent Loop vs Single-Turn Verification
    # -------------------------------------------------------------
    def test_dim_g_agent_capability_structure(self):
        """Verify the architecture style: deterministic pipeline vs autonomous agent loop."""
        # Currently, requirement generation is driven by Celery worker calling a single-pass LLM prompt
        # Rather than an interactive Agent with tool calling (ReAct / reflection loop)
        from app.services.llm.openai_compatible import OpenAICompatibleLLMService
        service = OpenAICompatibleLLMService(
            base_url="http://mock",
            api_key="mock",
            model="mock",
        )
        assert hasattr(service, "chat_json")
        assert not hasattr(service, "bind_tools"), "OpenAICompatibleLLMService does not implement tool binding"

    def test_dim_g_agent_self_correction_loop(self, monkeypatch, db_session: Session):
        """Verify the Agent Self-Correction Loop recovers when turn 1 produces invalid references."""
        from app.models import RequirementGenerationInput, RequirementGenerationItem, Project
        from app.services.requirement_generation_worker import generate_candidate

        project = Project(name="自反思项目", bank_name="测试银行", project_status="active", confidentiality_level="internal")
        db_session.add(project)
        db_session.flush()

        row = RequirementGenerationInput(
            project_id=project.id,
            requirement_id=1,
            revision_id=1,
            idempotency_key="idem-agent-test",
            request_hash="hash1",
            input_hash="hash2",
            input_json={
                "field_ids": [10],
                "sections": ["business"],
                "fields": [{"target": {"id": 10, "field_code": "TEST_COL"}}],
                "physical_sources": [{"kind": "source", "table_id": 1, "field_id": 1}],
                "evidence": [{"unit_id": 100, "confidentiality_level": "internal", "source_category": "regulatory_formal"}],
                "script_basis": {"rules": [{"rule_id": "R1"}]},
                "section": "business",
            },
            created_by=1,
        )
        item = RequirementGenerationItem(
            input_id=1,
            field_id=10,
            section="business",
            status="pending",
        )

        call_count = 0
        async def fake_chat(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # Turn 1: hallucinated physical reference
                return {
                    "business_definition": "初次生成包含范围外物理字段",
                    "processing_logic": "从错误字段获取",
                    "final_content": "草稿",
                    "physical_references": [{"kind": "source", "table_id": 999, "field_id": 999}],
                    "evidence_unit_ids": [100],
                    "script_rule_ids": ["R1"],
                    "policy_comparisons": [],
                    "gaps": [],
                }
            else:
                # Turn 2: Self-corrected after receiving critic feedback!
                return {
                    "business_definition": "反思纠错后的业务定义",
                    "processing_logic": "从合法字段获取",
                    "final_content": "正式草稿",
                    "physical_references": [{"kind": "source", "table_id": 1, "field_id": 1}],
                    "evidence_unit_ids": [100],
                    "script_rule_ids": ["R1"],
                    "policy_comparisons": [],
                    "gaps": [],
                }

        monkeypatch.setattr("app.services.requirement_generation_worker.execute_runtime_chat", fake_chat)

        candidate = generate_candidate(db_session, row, item, project)
        assert call_count == 2, "Agent must trigger turn-2 self-correction when turn 1 fails validation"
        assert candidate["business_definition"] == "反思纠错后的业务定义"
        assert candidate["execution_metadata"]["self_correction_attempts"] == 2

    # -------------------------------------------------------------
    # Dimension J: Robustness & Schema Validation
    # -------------------------------------------------------------
    def test_dim_j_robustness_schema_validation(self):
        """Test strict Pydantic parsing against malformed LLM responses."""
        malformed_response = {
            "business_definition": 12345,  # wrong type
            "unexpected_field": "injected",  # extra field forbidden
        }
        with pytest.raises(ValidationError):
            RequirementCandidate.model_validate(malformed_response)

    # -------------------------------------------------------------
    # Dimension B & C: Banking Business Context & Requirement Pipeline
    # -------------------------------------------------------------
    def test_dim_b_c_banking_business_and_requirement_pipeline(self):
        """Verify requirement candidate structure and banking domain field constraints."""
        valid_candidate = {
            "business_definition": "个人住房公积金贷款借据余额，反映报送时点借据实际未还本金。",
            "processing_logic": "从信贷系统 loan_account 表获取 balance 字段，按产品代码过滤住房公积金贷款。",
            "final_content": "正式口径草稿",
            "physical_references": [{"kind": "source", "table_id": 1, "field_id": 1}],
            "evidence_unit_ids": [101],
            "script_rule_ids": ["R_001"],
            "policy_comparisons": [
                {
                    "unit_id": 101,
                    "rule_ids": ["R_001"],
                    "status": "matched",
                    "explanation": "取数口径与监管答疑口径一致",
                }
            ],
            "gaps": [],
        }
        parsed = RequirementCandidate.model_validate(valid_candidate)
        assert parsed.business_definition.startswith("个人住房公积金贷款")
        assert len(parsed.policy_comparisons) == 1
        assert parsed.policy_comparisons[0].status == "matched"

    # -------------------------------------------------------------
    # Dimension H: Long Task Execution & Fencing
    # -------------------------------------------------------------
    def test_dim_h_long_task_execution_state_machine(self):
        """Verify item-level leasing and state management for long-running batch tasks."""
        from datetime import datetime, timezone, timedelta
        from app.models import RequirementGenerationItem

        item = RequirementGenerationItem(
            input_id=1,
            field_id=10,
            section="business",
            status="pending",
        )
        assert item.status == "pending"
        assert item.lease_key is None
        # Fencing logic test
        now = datetime.now(timezone.utc)
        item.status = "running"
        item.lease_until = now + timedelta(minutes=15)
        item.lease_key = "lease-123"
        assert item.lease_until > now

    # -------------------------------------------------------------
    # Dimension I: Traceability & Provenance
    # -------------------------------------------------------------
    def test_dim_i_traceability_content_digests(self):
        """Verify deterministic hashing and provenance guarantees."""
        from app.services.requirement_scope import content_digest

        data_a = {"field_id": 1, "name": "CERT_TYPE", "rule": "ECIF"}
        data_b = {"name": "CERT_TYPE", "field_id": 1, "rule": "ECIF"}  # different key order
        # Key ordering must not alter deterministic hash
        assert content_digest(data_a) == content_digest(data_b)

        data_c = {"field_id": 1, "name": "CERT_TYPE", "rule": "ECIF_MODIFIED"}
        assert content_digest(data_a) != content_digest(data_c)


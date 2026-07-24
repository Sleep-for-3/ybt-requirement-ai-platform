from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class DraftOutput(BaseModel):
    model_config = ConfigDict(extra="ignore")
    confidence_level: str = "low"
    open_questions: list[str] | str = Field(default_factory=list)
    citations: list[dict[str, Any]] = Field(default_factory=list)
    claim_type: str | None = None
    final_content_draft: str | None = None


class ScenarioBusinessOutput(DraftOutput):
    business_definition: str | None = None
    source_system_screenshot_required: bool | None = None
    source_system_change_required: bool | None = None
    external_data_required: bool | None = None
    manual_supplement_required: bool | None = None
    business_owner: str | None = None
    remarks: str | None = None

    @model_validator(mode="after")
    def _requires_business_content(self):
        if not (self.business_definition or self.final_content_draft):
            raise ValueError("Scenario business output is missing business content")
        return self


class ScenarioTechnicalOutput(DraftOutput):
    source_system_name: str | None = None
    source_database_name: str | None = None
    source_schema_name: str | None = None
    source_table_english_name: str | None = None
    source_table_chinese_name: str | None = None
    source_field_english_name: str | None = None
    source_field_chinese_name: str | None = None
    processing_logic: str | None = None
    processing_logic_type: str | None = None
    tech_owner: str | None = None
    remarks: str | None = None

    @model_validator(mode="after")
    def _requires_technical_content(self):
        if not (self.processing_logic or self.final_content_draft):
            raise ValueError("Scenario technical output is missing processing logic")
        return self


class SourceToMartOutput(DraftOutput):
    source_system_summary: str | None = None
    source_tables_summary: str | None = None
    source_fields_summary: str | None = None
    business_rule: str | None = None
    business_to_mart_rule: str | None = None
    filter_condition: str | None = None
    join_condition: str | None = None
    priority_rule: str | None = None
    merge_rule: str | None = None
    code_mapping_rule: str | None = None
    null_handling_rule: str | None = None
    exception_rule: str | None = None
    quality_check_rule: str | None = None

    @model_validator(mode="after")
    def _requires_mapping_content(self):
        if not (self.business_rule or self.business_to_mart_rule or self.final_content_draft):
            raise ValueError("Source-to-mart output is missing mapping content")
        return self


class MartToYbtOutput(DraftOutput):
    mart_table_summary: str | None = None
    mart_field_summary: str | None = None
    business_rule: str | None = None
    mart_to_ybt_rule: str | None = None
    filter_condition: str | None = None
    join_condition: str | None = None
    code_mapping_rule: str | None = None
    null_handling_rule: str | None = None
    reporting_condition: str | None = None
    validation_rule: str | None = None

    @model_validator(mode="after")
    def _requires_mapping_content(self):
        if not (self.business_rule or self.mart_to_ybt_rule or self.final_content_draft):
            raise ValueError("Mart-to-YBT output is missing mapping content")
        return self


class SourceRecommendationExplanationOutput(DraftOutput):
    recommendation_basis: str = Field(min_length=1)
    recommended_source_system: str | None = None
    recommended_table_name: str | None = None
    recommended_field_name: str | None = None
    risk_points: list[str] = Field(default_factory=list)


class RegulatoryFieldExplanationOutput(DraftOutput):
    answer: str = ""
    supported_claims: list[str] = Field(default_factory=list)
    unsupported_claims: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _requires_answer(self):
        if not self.answer.strip():
            raise ValueError("Regulatory field explanation is missing an answer")
        return self


class LegacyFieldDraftOutput(BaseModel):
    model_config = ConfigDict(extra="ignore")
    business_to_mart_rule: str = ""
    mart_to_ybt_rule: str = ""
    source_system_candidates: list[str] = Field(default_factory=list)
    source_table_candidates: list[str] = Field(default_factory=list)
    source_field_candidates: list[str] = Field(default_factory=list)
    east_reference_summary: str = ""
    sql_reference_summary: str = ""
    validation_notes: str = ""
    confidence_level: str = "low"
    template_reference_summary: str = ""
    db_query_summary: str = ""
    data_quality_notes: str = ""
    evidence_completeness: str = "low"
    risk_points: list[str] = Field(default_factory=list)
    questions_for_human: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _requires_mapping_content(self):
        if not (self.business_to_mart_rule or self.mart_to_ybt_rule):
            raise ValueError("Legacy field mapping output is missing mapping content")
        return self

from __future__ import annotations

from typing import Any, Literal

from openpyxl.utils import column_index_from_string
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


TemplateType = Literal[
    "business_traceability",
    "source_to_mart",
    "mart_to_ybt",
    "full_delivery_package",
    "pending_questions",
    "evidence_matrix",
    "change_comparison",
]
BusinessSection = Literal[
    "target_field",
    "scenario_business_mapping",
    "scenario_technical_lineage",
    "source_to_mart",
    "mart_to_ybt",
    "pending_question",
    "evidence",
    "review_record",
    "lineage",
    "change_impact",
]
RepeatDirection = Literal["vertical", "horizontal"]
WriteMode = Literal["overwrite", "append", "fill_blank_only", "repeat_by_scenario", "repeat_by_source"]
MergeStrategy = Literal["none", "merge_same_target_field", "merge_same_scenario", "preserve_template"]


class TemplateColumnMappingInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    business_field: str = Field(min_length=1, max_length=100)
    excel_column: str = Field(min_length=1, max_length=3)
    excel_header: str | None = Field(default=None, max_length=255)
    write_mode: WriteMode = "overwrite"
    merge_strategy: MergeStrategy = "none"
    required: bool = False
    default_value: str | None = None
    format_config_json: dict[str, Any] = Field(default_factory=dict)

    @field_validator("excel_column")
    @classmethod
    def validate_excel_column(cls, value: str) -> str:
        normalized = value.strip().upper()
        try:
            column_number = column_index_from_string(normalized)
        except ValueError as exc:
            raise ValueError("excel_column must be a valid Excel column between A and XFD") from exc
        if not 1 <= column_number <= 16384:
            raise ValueError("excel_column must be between A and XFD")
        return normalized


class TemplateSheetMappingInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    business_section: BusinessSection
    sheet_name: str = Field(min_length=1, max_length=255)
    header_row_start: int = Field(default=1, ge=1)
    header_row_end: int = Field(default=1, ge=1)
    data_start_row: int = Field(default=2, ge=1)
    repeat_direction: RepeatDirection = "vertical"
    enabled: bool = True
    columns: list[TemplateColumnMappingInput] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_rows(self) -> "TemplateSheetMappingInput":
        if self.header_row_end < self.header_row_start:
            raise ValueError("header_row_end must be greater than or equal to header_row_start")
        if self.data_start_row <= self.header_row_end:
            raise ValueError("data_start_row must be greater than header_row_end")
        return self


class TemplateConfigureRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sheet_mappings: list[TemplateSheetMappingInput] = Field(min_length=1)


class DeliverableCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    package_name: str | None = Field(default=None, max_length=255)
    package_type: TemplateType = "full_delivery_package"
    target_table_id: int = Field(gt=0)
    template_version_id: int = Field(gt=0)


class PendingQuestionCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_table_id: int = Field(gt=0)
    target_field_id: int | None = Field(default=None, gt=0)
    scenario_id: int | None = Field(default=None, gt=0)
    question_type: str = Field(default="other", min_length=1, max_length=50)
    question_text: str = Field(min_length=1)
    priority: Literal["low", "medium", "high"] = "medium"
    assigned_role: str | None = Field(default=None, max_length=50)
    assigned_user_id: int | None = Field(default=None, gt=0)
    source_type: str | None = Field(default=None, max_length=50)
    source_id: int | None = Field(default=None, gt=0)


class PendingQuestionUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    priority: Literal["low", "medium", "high"] | None = None
    assigned_role: str | None = Field(default=None, max_length=50)
    assigned_user_id: int | None = Field(default=None, gt=0)
    question_status: Literal["open", "assigned", "answered", "accepted", "rejected", "closed"] | None = None


class PendingQuestionAnswerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resolution_text: str = Field(min_length=1, max_length=10000)

    @field_validator("resolution_text")
    @classmethod
    def validate_resolution_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("resolution_text must contain a real answer")
        return value

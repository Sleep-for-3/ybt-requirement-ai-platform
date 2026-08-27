from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


QualityRuleType = Literal["not_null", "unique", "range", "enum", "referential", "consistency", "custom_expression"]
QualityStatus = Literal["draft", "ai_suggested", "confirmed", "rejected", "retired"]
QualityScopeType = Literal["requirement", "mapping", "uat", "monitoring"]


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class QualityExpectationBindingCreate(_StrictModel):
    scope_type: QualityScopeType
    entity_type: str = Field(min_length=1, max_length=80)
    entity_id: int | None = Field(default=None, gt=0)
    entity_key: str | None = Field(default=None, max_length=500)
    configuration_json: dict[str, Any] = Field(default_factory=dict, max_length=50)

    @field_validator("entity_type", "entity_key")
    @classmethod
    def strip_text(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None

    @model_validator(mode="after")
    def require_scope_identity(self):
        if self.entity_id is None and not self.entity_key:
            raise ValueError("a binding requires entity_id or entity_key")
        return self


class QualityExpectationCreate(_StrictModel):
    rule_code: str = Field(min_length=1, max_length=120)
    rule_name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=4000)
    rule_type: QualityRuleType
    expression: str | None = Field(default=None, max_length=4000)
    parameters_json: dict[str, Any] = Field(default_factory=dict, max_length=50)
    severity: Literal["info", "warning", "error"] = "warning"
    status: Literal["draft", "ai_suggested"] = "draft"
    source_type: str = Field(default="manual", min_length=1, max_length=50)
    source_id: int | None = Field(default=None, gt=0)
    confidence_level: Literal["low", "medium", "high"] = "medium"
    bindings: list[QualityExpectationBindingCreate] = Field(default_factory=list, max_length=100)

    @field_validator("rule_code", "rule_name", "source_type")
    @classmethod
    def strip_required(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("value must not be blank")
        return value

    @model_validator(mode="after")
    def validate_rule_shape(self):
        parameters = self.parameters_json
        if self.rule_type == "range" and "min" not in parameters and "max" not in parameters:
            raise ValueError("range rule requires min or max")
        if self.rule_type == "enum" and not isinstance(parameters.get("values"), list):
            raise ValueError("enum rule requires a values list")
        if self.rule_type == "referential" and not parameters.get("reference"):
            raise ValueError("referential rule requires reference metadata")
        if self.rule_type in {"consistency", "custom_expression"} and not self.expression:
            raise ValueError(f"{self.rule_type} rule requires an expression")
        return self


class QualityExpectationStatusTransition(_StrictModel):
    status: Literal["confirmed", "rejected", "retired"]
    comment: str | None = Field(default=None, max_length=1000)


class QualityExpectationBindingRead(_StrictModel):
    id: int
    project_id: int
    expectation_id: int
    scope_type: str
    entity_type: str
    entity_id: int | None
    entity_key: str | None
    binding_status: str
    configuration_json: dict
    created_at: datetime
    updated_at: datetime


class QualityExpectationRead(_StrictModel):
    id: int
    project_id: int
    rule_code: str
    rule_name: str
    description: str | None
    rule_type: str
    expression: str | None
    parameters_json: dict
    severity: str
    status: str
    source_type: str
    source_id: int | None
    confidence_level: str
    created_by: str | None
    confirmed_by: str | None
    confirmed_at: datetime | None
    status_reason: str | None
    created_at: datetime
    updated_at: datetime
    bindings: list[QualityExpectationBindingRead] = Field(default_factory=list)

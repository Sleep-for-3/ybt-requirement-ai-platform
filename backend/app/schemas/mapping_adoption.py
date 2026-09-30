from pydantic import BaseModel, ConfigDict, Field


class MappingDraftAdoption(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_draft_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

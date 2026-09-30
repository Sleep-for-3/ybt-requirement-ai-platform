"""Small public provenance projection shared by business result readers."""
from copy import deepcopy


def safe_execution_metadata(recorded, legacy=None):
    recorded = recorded or {}
    legacy = legacy or {}
    keys = ("runtime_mode", "execution_kind", "provider_type", "model_name", "model_profile_id",
            "skill_key", "skill_version_id", "skill_version_no", "run_id", "context_hash",
            "context_complete", "input_contract_version")
    result = {key: deepcopy(recorded[key]) for key in keys if key in recorded}
    result.setdefault("runtime_mode", "legacy")
    for key, original in (("provider_type", "provider"), ("model_name", "model"), ("execution_kind", "execution_kind")):
        if key not in result and legacy.get(original) is not None:
            result[key] = legacy[original]
    return result

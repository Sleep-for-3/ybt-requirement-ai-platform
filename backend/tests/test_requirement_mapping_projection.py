from app.services.requirement_candidate_contract import project_candidate_context


def _frozen(field_id: int) -> dict:
    return {
        "section": "lineage",
        "sections": ["business", "lineage"],
        "field_ids": [field_id],
        "fields": [{"target": {"id": field_id}}],
        "mapping_sources": [
            {"kind": "mart", "table_id": 1, "field_id": 11, "source": "mart_mapping", "target_field_id": field_id},
            {"kind": "mart", "table_id": 1, "field_id": 12, "source": "mart_mapping", "target_field_id": field_id + 1},
            {"kind": "mart", "table_id": 1, "field_id": 13, "source": "field_mapping", "target_field_id": None},
        ],
        "script_basis": {},
    }


def test_mapping_only_context_keeps_current_field_sources():
    context = project_candidate_context(_frozen(48), 48, "lineage")
    assert [item["field_id"] for item in context["mapping_sources"]] == [11]


def test_unbound_field_mapping_is_not_leaked_to_other_field():
    context = project_candidate_context(_frozen(48), 48, "lineage")
    assert all(item.get("target_field_id") in (None, 48) for item in context["mapping_sources"])
    assert context["field_ids"] == [48]
    assert len(context["fields"]) == 1

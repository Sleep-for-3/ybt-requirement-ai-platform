"""Whole-evidence context selection under an explicit token estimate budget."""
from app.services.semantic_index.chunking import estimate_tokens

MAX_CONTEXT_ITEMS = 50
LEGACY_CONTEXT_ITEMS = 12


def assemble_context(items, *, budget, roles=()):
    selected = []
    selected_ids = set()
    used = 0
    role_names = list(dict.fromkeys(roles))
    rejected = []

    def add(item):
        nonlocal used
        unit_id = item["knowledge_unit_id"]
        if unit_id in selected_ids:
            return True
        cost = estimate_tokens(f"[{unit_id}] {item['content']}\n")
        if cost + used > budget:
            rejected.append(unit_id)
            return False
        used += cost
        selected.append(item)
        selected_ids.add(unit_id)
        return True

    # Preserve one available item for each requested role before normal filling.
    for role in role_names:
        for item in items:
            if role in item.get("evidence_roles", []) and add(item):
                break
    for item in items:
        if len(selected) >= MAX_CONTEXT_ITEMS:
            break
        add(item)
    covered = {role for item in selected for role in item.get("evidence_roles", [])}
    return selected, {
        "budget_tokens": budget, "estimated_tokens": used,
        "counter": "estimate-tokens-v1", "selected_count": len(selected),
        "selected_ids": [item["knowledge_unit_id"] for item in selected],
        "budget_excluded_ids": list(dict.fromkeys(rejected)),
        "missing_roles": [role for role in role_names if role not in covered],
    }

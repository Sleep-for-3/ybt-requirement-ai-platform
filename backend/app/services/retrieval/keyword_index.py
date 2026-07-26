import re

from sqlalchemy import delete

from app.models import KnowledgeKeywordIndex


def tokenize(text: str) -> list[str]:
    words = [
        item.lower()
        for item in re.findall(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]{2,}", text or "")
    ]
    bigrams = [
        word[index : index + 2]
        for word in words
        if re.search(r"[\u4e00-\u9fff]", word)
        for index in range(len(word) - 1)
    ]
    return list(dict.fromkeys(words + bigrams))


def weighted_tokens(title: str | None, content: str, structured_text: str = "") -> dict[str, float]:
    weights: dict[str, float] = {}
    for text, weight in [(content, 1.0), (title or "", 1.25), (structured_text, 1.5)]:
        for token in tokenize(text):
            weights[token] = max(weights.get(token, 0.0), weight)
    return weights


def index_knowledge_unit(db, unit, *, replace: bool = False) -> None:
    if replace:
        db.execute(delete(KnowledgeKeywordIndex).where(KnowledgeKeywordIndex.knowledge_unit_id == unit.id))
    structured = " ".join(
        filter(
            None,
            [
                unit.target_table_code,
                unit.target_field_code,
                unit.target_field_name,
                unit.source_table_name,
                unit.source_field_name,
            ],
        )
    )
    for token, weight in weighted_tokens(unit.title, unit.normalized_content, structured).items():
        db.add(
            KnowledgeKeywordIndex(
                project_id=unit.project_id,
                knowledge_unit_id=unit.id,
                token=token,
                weight=weight,
            )
        )

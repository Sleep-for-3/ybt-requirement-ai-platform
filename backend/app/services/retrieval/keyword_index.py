import re

from sqlalchemy import delete

from app.models import KnowledgeKeywordIndex


from app.services.retrieval.banking_vocabulary import get_banking_synonyms, _SYNONYM_MAP


def token_matches(text: str, token: str) -> bool:
    """Match English concepts at identifier boundaries, not inside other words.

    Underscores separate field-name concepts (balance_amt); digits remain part
    of a code so 1104 cannot match 110400. Chinese terms use substring matching.
    """
    if token.isascii():
        return re.search(r"(?<![a-z0-9])" + re.escape(token.lower()) + r"(?![a-z0-9])", text.lower()) is not None
    return token.lower() in text.lower()


def tokenize(text: str, expand_synonyms: bool = False) -> list[str]:
    lower_text = (text or "").lower()
    words = [
        item.lower()
        for item in re.findall(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]{2,}", text or "")
    ]
    # Chinese terms can occur within phrases; English terms require boundaries.
    domain_matches = [term for term in sorted(_SYNONYM_MAP) if len(term) >= 2 and token_matches(lower_text, term)]
    words.extend(domain_matches)

    bigrams = [
        word[index : index + 2]
        for word in words
        if re.search(r"[\u4e00-\u9fff]", word)
        for index in range(len(word) - 1)
    ]
    all_tokens = list(dict.fromkeys(words + bigrams))
    if expand_synonyms:
        expanded = []
        for token in all_tokens:
            for syn in sorted(get_banking_synonyms(token)):
                expanded.append(syn)
        all_tokens = list(dict.fromkeys(all_tokens + expanded))
    return all_tokens


def weighted_tokens(title: str | None, content: str, structured_text: str = "") -> dict[str, float]:
    weights: dict[str, float] = {}
    for text, weight in [(content, 1.0), (title or "", 1.25), (structured_text, 1.5)]:
        for token in tokenize(text):
            weights[token] = max(weights.get(token, 0.0), weight)
    # Expand domain synonyms with discounted weight (0.85) for higher recall
    expanded_synonyms: dict[str, float] = {}
    for token, weight in weights.items():
        for syn in sorted(get_banking_synonyms(token)):
            if syn not in weights:
                expanded_synonyms[syn] = max(expanded_synonyms.get(syn, 0.0), weight * 0.85)
    for syn, weight in expanded_synonyms.items():
        weights[syn] = weight
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

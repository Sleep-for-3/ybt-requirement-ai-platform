import math
import re
from dataclasses import dataclass, field

from sqlalchemy import delete, func, select

from app.models import KnowledgeKeywordIndex, KnowledgeUnit


from app.services.retrieval.banking_vocabulary import get_banking_synonyms, _SYNONYM_MAP


def token_matches(text: str, token: str) -> bool:
    """Match English concepts at identifier boundaries, not inside other words.

    Underscores separate field-name concepts (balance_amt); digits remain part
    of a code so 1104 cannot match 110400. Chinese terms use substring matching.
    """
    if token.isascii():
        return re.search(r"(?<![a-z0-9])" + re.escape(token.lower()) + r"(?![a-z0-9])", text.lower()) is not None
    return token.lower() in text.lower()


_JIEBA_MODULE = None


def _get_jieba():
    """Import jieba lazily; a missing/inert dependency degrades to the regex+bigram tokenizer."""
    global _JIEBA_MODULE
    if _JIEBA_MODULE is None:
        try:
            import jieba
        except Exception:  # pragma: no cover - depends on install state
            _JIEBA_MODULE = False
        else:
            if hasattr(jieba, "setLogLevel"):
                jieba.setLogLevel(60)
            _JIEBA_MODULE = jieba
    return _JIEBA_MODULE or None


def segment_chinese(text: str) -> list[str]:
    """Chinese word segmentation (jieba) feeding BM25; English stays with tokenize's regex."""
    if not text:
        return []
    jieba = _get_jieba()
    if jieba is None:  # pragma: no cover - only without the optional dependency
        return []
    terms: list[str] = []
    for term in jieba.lcut(text):
        candidate = term.strip().lower()
        if len(candidate) >= 2 and re.search(r"[\u4e00-\u9fff]", candidate):
            terms.append(candidate)
    return list(dict.fromkeys(terms))


def tokenize(text: str, expand_synonyms: bool = False) -> list[str]:
    lower_text = (text or "").lower()
    words = [
        item.lower()
        for item in re.findall(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]{2,}", text or "")
    ]
    # Chinese terms can occur within phrases; English terms require boundaries.
    domain_matches = [term for term in sorted(_SYNONYM_MAP) if len(term) >= 2 and token_matches(lower_text, term)]
    words.extend(domain_matches)
    words.extend(segment_chinese(text))

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


DEFAULT_BM25_K1 = 1.2
DEFAULT_BM25_B = 0.75


@dataclass(frozen=True)
class BM25Stats:
    """Corpus statistics for BM25, aggregated live from knowledge_keyword_indexes.

    No new table and no migration: document length and document frequency are
    derived from the existing per-unit token rows on every query.
    """

    idf: dict[str, float] = field(default_factory=dict)
    lengths: dict[int, float] = field(default_factory=dict)
    frequencies: dict[int, dict[str, float]] = field(default_factory=dict)
    average_length: float = 0.0
    corpus_size: int = 0
    k1: float = DEFAULT_BM25_K1
    b: float = DEFAULT_BM25_B


def bm25_idf(corpus_size: int, document_frequency: int) -> float:
    """Probabilistic IDF; strictly positive whenever the corpus is non-empty."""
    size = int(corpus_size or 0)
    if size <= 0:
        return 0.0
    frequency = min(max(int(document_frequency or 0), 0), size)
    return math.log(1.0 + (size - frequency + 0.5) / (frequency + 0.5))


def bm25_term_score(
    term_frequency: float,
    document_length: float,
    average_length: float,
    idf: float,
    *,
    k1: float = DEFAULT_BM25_K1,
    b: float = DEFAULT_BM25_B,
) -> float:
    """Saturated term frequency with document-length normalisation."""
    frequency = max(float(term_frequency), 0.0)
    if frequency <= 0.0 or float(idf) <= 0.0:
        return 0.0
    saturation = max(float(k1), 0.0)
    length_ratio = min(max(float(b), 0.0), 1.0)
    if average_length and average_length > 0.0:
        normalization = 1.0 - length_ratio + length_ratio * (float(document_length) / float(average_length))
    else:
        normalization = 1.0
    denominator = frequency + saturation * normalization
    if denominator <= 0.0:
        return 0.0
    return float(idf) * (frequency * (saturation + 1.0)) / denominator


def compute_bm25_stats(
    db,
    *,
    predicates,
    tokens,
    document_frequency: dict[str, int] | None = None,
    k1: float = DEFAULT_BM25_K1,
    b: float = DEFAULT_BM25_B,
) -> BM25Stats:
    """Aggregate IDF and document-length statistics live from knowledge_keyword_indexes.

    No new table and no migration: corpus size, document lengths and document
    frequencies are all derived from the existing per-unit token rows. The corpus
    is the set of knowledge units that have at least one indexed token under
    ``predicates`` (units without keyword rows can never be keyword candidates).
    """
    join = KnowledgeUnit.id == KnowledgeKeywordIndex.knowledge_unit_id
    document_count, token_count = db.execute(
        select(
            func.count(func.distinct(KnowledgeKeywordIndex.knowledge_unit_id)),
            func.count(),
        )
        .join(KnowledgeUnit, join)
        .where(*predicates)
    ).one()
    corpus_size = int(document_count or 0)
    average_length = (float(token_count or 0.0) / corpus_size) if corpus_size else 0.0

    token_list = list(dict.fromkeys(token for token in tokens if token))
    frequencies = document_frequency
    if frequencies is None:
        frequencies = {}
        if token_list:
            rows = db.execute(
                select(
                    KnowledgeKeywordIndex.token,
                    func.count(func.distinct(KnowledgeKeywordIndex.knowledge_unit_id)),
                )
                .join(KnowledgeUnit, join)
                .where(*predicates, KnowledgeKeywordIndex.token.in_(token_list))
                .group_by(KnowledgeKeywordIndex.token)
            ).all()
            frequencies = {str(token): int(frequency or 0) for token, frequency in rows}
    idf = {
        token: bm25_idf(corpus_size, int(frequencies.get(token, 0)))
        for token in token_list
    }
    return BM25Stats(
        idf=idf,
        average_length=average_length,
        corpus_size=corpus_size,
        k1=float(k1),
        b=float(b),
    )


def load_unit_statistics(db, unit_ids, tokens) -> tuple[dict[int, float], dict[int, dict[str, float]]]:
    """Per-unit document length and query-token weights for the candidate units."""
    identifiers = [int(unit_id) for unit_id in unit_ids if unit_id is not None]
    if not identifiers:
        return {}, {}
    token_list = list(dict.fromkeys(token for token in tokens if token))
    lengths = {
        int(unit_id): float(length or 0.0)
        for unit_id, length in db.execute(
            select(KnowledgeKeywordIndex.knowledge_unit_id, func.count())
            .where(KnowledgeKeywordIndex.knowledge_unit_id.in_(identifiers))
            .group_by(KnowledgeKeywordIndex.knowledge_unit_id)
        ).all()
    }
    frequencies: dict[int, dict[str, float]] = {}
    if token_list:
        for unit_id, token, weight in db.execute(
            select(
                KnowledgeKeywordIndex.knowledge_unit_id,
                KnowledgeKeywordIndex.token,
                KnowledgeKeywordIndex.weight,
            ).where(
                KnowledgeKeywordIndex.knowledge_unit_id.in_(identifiers),
                KnowledgeKeywordIndex.token.in_(token_list),
            )
        ).all():
            tokens_for_unit = frequencies.setdefault(int(unit_id), {})
            tokens_for_unit[str(token)] = max(tokens_for_unit.get(str(token), 0.0), float(weight or 0.0))
    return lengths, frequencies


def score_bm25(
    tokens,
    frequencies: dict[str, float],
    document_length: float,
    stats: BM25Stats,
) -> float:
    """Sum BM25 contributions of ``tokens`` present in one document's ``frequencies``."""
    total = 0.0
    for token in dict.fromkeys(token for token in tokens if token):
        weight = float(frequencies.get(token, 0.0) or 0.0)
        if weight <= 0.0:
            continue
        idf = stats.idf.get(token)
        if idf is None:
            idf = bm25_idf(stats.corpus_size, 0)
        total += bm25_term_score(
            weight,
            document_length,
            stats.average_length,
            idf,
            k1=stats.k1,
            b=stats.b,
        )
    return total

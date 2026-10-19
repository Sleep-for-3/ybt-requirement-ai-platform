"""Real BM25 keyword scoring (landing plan item ③).

Covers the scoring primitives (IDF, saturation, length normalisation), the live
corpus aggregation over ``knowledge_keyword_indexes`` (no new table, no
migration) and the boundaries the plan calls out: empty query, empty corpus,
single document and IDF = 0. The statement-count test pins the SQL budget so the
keyword branch cannot silently add queries when it has no candidates.
"""

import pytest
from sqlalchemy import event

from app.models import KnowledgeDocument, KnowledgeDocumentVersion, KnowledgeUnit, Project
from app.services.knowledge_eligibility import governed_unit_predicates
from app.services.retrieval import hybrid_retriever
from app.services.retrieval.hybrid_retriever import HybridRetriever
from app.services.retrieval.keyword_index import (
    BM25Stats,
    DEFAULT_BM25_B,
    DEFAULT_BM25_K1,
    bm25_idf,
    bm25_term_score,
    compute_bm25_stats,
    index_knowledge_unit,
    load_unit_statistics,
    score_bm25,
    segment_chinese,
    tokenize,
)


def _seed(db, contents):
    project = Project(name="BM25 语料", bank_name="模拟机构")
    db.add(project)
    db.flush()
    document = KnowledgeDocument(
        project_id=project.id,
        file_name="bm25.md",
        file_type="md",
        source_type="upload",
        storage_path="bm25",
        document_status="indexed",
    )
    db.add(document)
    db.flush()
    version = KnowledgeDocumentVersion(
        project_id=project.id,
        document_id=document.id,
        version_no=1,
        file_name=document.file_name,
        storage_path="bm25",
        file_hash="a" * 64,
    )
    db.add(version)
    db.flush()
    units = []
    for index, text in enumerate(contents):
        unit = KnowledgeUnit(
            project_id=project.id,
            document_id=document.id,
            document_version_id=version.id,
            knowledge_type="manual_note",
            knowledge_scope="project",
            unit_type="paragraph",
            content=text,
            normalized_content=text,
            source_file_name=document.file_name,
            confidentiality_level="internal",
            enabled=True,
            content_hash=format(index + 1, "064d"),
        )
        db.add(unit)
        db.flush()
        index_knowledge_unit(db, unit)
        units.append(unit)
    db.commit()
    return project, units



def _rarer_and_common_corpus(db):
    """One unit holding a rare token, four units holding a frequent one."""
    return _seed(db, ["alpha_rare"] + ["beta_common"] * 4)


# ---------------------------------------------------------------- primitives


def test_idf_is_positive_and_decreases_with_document_frequency():
    assert bm25_idf(5, 1) > bm25_idf(5, 4) > bm25_idf(5, 5) > 0.0
    assert bm25_idf(5, 0) == pytest.approx(2.4849066497880004)
    assert bm25_idf(5, 1) == pytest.approx(1.3862943611198906)
    # A token present everywhere still carries a (small) positive IDF.
    assert bm25_idf(5, 5) == pytest.approx(0.08701137698962969)


def test_idf_is_zero_for_an_empty_corpus():
    assert bm25_idf(0, 0) == 0.0
    assert bm25_idf(0, 7) == 0.0


def test_term_score_saturates_and_normalises_document_length():
    twice_k1 = DEFAULT_BM25_K1 + 1.0
    assert bm25_term_score(1.0, 1.0, 1.0, 1.0) == pytest.approx(1.0)
    # Term frequency saturates: doubling tf must not double the score.
    doubled = bm25_term_score(2.0, 1.0, 1.0, 1.0)
    assert doubled == pytest.approx(2 * twice_k1 / (2 + DEFAULT_BM25_K1))
    assert 1.0 < doubled < 2.0
    # A longer document is penalised when the average length stays fixed.
    longer = bm25_term_score(1.0, 4.0, 1.0, 1.0)
    assert longer < bm25_term_score(1.0, 1.0, 1.0, 1.0)
    assert longer == pytest.approx(twice_k1 / (1 + DEFAULT_BM25_K1 * (1 - DEFAULT_BM25_B + DEFAULT_BM25_B * 4)))


def test_term_score_is_zero_without_term_frequency_or_idf():
    assert bm25_term_score(0.0, 1.0, 1.0, 1.0) == 0.0
    assert bm25_term_score(3.0, 1.0, 1.0, 0.0) == 0.0


def test_score_bm25_skips_tokens_with_zero_idf():
    stats = BM25Stats(idf={"known": 0.0}, average_length=1.0, corpus_size=0)
    assert score_bm25(["known"], {"known": 1.0}, 1.0, stats) == 0.0
    # A token missing from the idf table degenerates to IDF(corpus_size, 0).
    empty_corpus = BM25Stats(idf={}, average_length=1.0, corpus_size=0)
    assert score_bm25(["unknown"], {"unknown": 1.0}, 1.0, empty_corpus) == 0.0
    single_doc = BM25Stats(idf={}, average_length=1.0, corpus_size=1)
    assert score_bm25(["unknown"], {"unknown": 1.0}, 1.0, single_doc) > 0.0


# ---------------------------------------------------------------- tokenizing


def test_segment_chinese_uses_jieba_and_ignores_ascii_only_input():
    segments = segment_chinese("个人住房按揭贷款")
    assert "按揭" in segments and "贷款" in segments
    assert all(any("\u4e00" <= character <= "\u9fff" for character in term) for term in segments)
    assert segment_chinese("BALANCE_AMT 110400") == []
    assert segment_chinese("") == []


def test_tokenize_keeps_field_identifiers_and_chinese_bigrams():
    tokens = tokenize("LOAN_DTL.BALANCE_AMT 对应的业务含义是什么？")
    assert "loan_dtl" in tokens and "balance_amt" in tokens
    assert tokenize("个人住房按揭贷款") == tokenize("个人住房按揭贷款")


# ------------------------------------------------------------- live aggregate


def test_corpus_statistics_are_aggregated_from_existing_keyword_rows(db_session):
    project, units = _rarer_and_common_corpus(db_session)
    predicates = governed_unit_predicates(project.id)
    tokens = ["alpha_rare", "beta_common"]

    stats = compute_bm25_stats(db_session, predicates=predicates, tokens=tokens)

    assert stats.corpus_size == 5
    assert stats.average_length == pytest.approx(1.0)
    assert stats.k1 == pytest.approx(DEFAULT_BM25_K1)
    assert stats.b == pytest.approx(DEFAULT_BM25_B)
    assert stats.idf["alpha_rare"] == pytest.approx(bm25_idf(5, 1))
    assert stats.idf["beta_common"] == pytest.approx(bm25_idf(5, 4))


def test_load_unit_statistics_reports_lengths_and_query_weights(db_session):
    project, units = _rarer_and_common_corpus(db_session)
    lengths, frequencies = load_unit_statistics(db_session, [unit.id for unit in units], ["alpha_rare"])

    assert lengths == {unit.id: 1.0 for unit in units}
    assert frequencies == {units[0].id: {"alpha_rare": 1.0}}

    empty_lengths, empty_frequencies = load_unit_statistics(db_session, [], ["alpha_rare"])
    assert empty_lengths == {} and empty_frequencies == {}


def test_rarer_term_outranks_a_common_term_of_equal_length(db_session):
    """Pure coverage scoring ties here; IDF has to break the tie."""
    project, units = _rarer_and_common_corpus(db_session)
    predicates = governed_unit_predicates(project.id)
    tokens = ["alpha_rare", "beta_common"]

    stats = compute_bm25_stats(db_session, predicates=predicates, tokens=tokens)
    lengths, frequencies = load_unit_statistics(db_session, [unit.id for unit in units], tokens)

    rare = score_bm25(tokens, frequencies[units[0].id], lengths[units[0].id], stats)
    common = score_bm25(tokens, frequencies[units[1].id], lengths[units[1].id], stats)
    assert rare > common > 0.0

    log, items = HybridRetriever(db_session).search(
        project.id,
        "alpha_rare beta_common",
        top_k=5,
        retrieval_mode="keyword_only",
    )
    assert log.retrieval_strategy == "keyword_only"
    assert log.keyword_result_count == 5
    assert items[0]["knowledge_unit_id"] == units[0].id


# ----------------------------------------------------------------- boundaries


def test_single_document_corpus_still_scores_positive(db_session):
    project, units = _seed(db_session, ["alpha_rare"])
    predicates = governed_unit_predicates(project.id)
    stats = compute_bm25_stats(db_session, predicates=predicates, tokens=["alpha_rare"])

    assert stats.corpus_size == 1
    lengths, frequencies = load_unit_statistics(db_session, [units[0].id], ["alpha_rare"])
    assert score_bm25(["alpha_rare"], frequencies[units[0].id], lengths[units[0].id], stats) > 0.0

    log, items = HybridRetriever(db_session).search(project.id, "alpha_rare", top_k=5, retrieval_mode="keyword_only")
    assert log.keyword_result_count == 1
    assert [item["knowledge_unit_id"] for item in items] == [units[0].id]


def test_empty_corpus_returns_no_keyword_results(db_session):
    project, _units = _seed(db_session, [])
    log, items = HybridRetriever(db_session).search(project.id, "alpha_rare", top_k=5, retrieval_mode="keyword_only")
    assert items == []
    assert log.keyword_result_count == 0
    assert log.final_result_count == 0


def test_empty_query_returns_no_results_and_no_statistics(db_session, monkeypatch):
    project, _units = _rarer_and_common_corpus(db_session)
    monkeypatch.setattr(
        hybrid_retriever,
        "compute_bm25_stats",
        lambda *args, **kwargs: pytest.fail("empty query must not aggregate corpus statistics"),
    )
    log, items = HybridRetriever(db_session).search(project.id, "   ", top_k=5, retrieval_mode="keyword_only")
    assert items == []
    assert log.keyword_result_count == 0


def test_keyword_branch_adds_no_statements_when_no_candidate_matches(db_session, monkeypatch):
    """Pins the SQL budget: statistics are only aggregated for real candidates."""
    project, _units = _rarer_and_common_corpus(db_session)
    monkeypatch.setattr(
        hybrid_retriever,
        "compute_bm25_stats",
        lambda *args, **kwargs: pytest.fail("no candidates must skip the BM25 aggregation"),
    )

    statements = []
    engine = db_session.get_bind()
    listener = lambda *args, **kwargs: statements.append(args[2])  # noqa: E731
    event.listen(engine, "before_cursor_execute", listener)
    try:
        log, items = HybridRetriever(db_session).search(
            project.id,
            "zzz_nonmatching_token",
            top_k=5,
            retrieval_mode="keyword_only",
        )
        baseline = len(statements)
        HybridRetriever(db_session).search(project.id, "zzz_nonmatching_token", top_k=5, retrieval_mode="keyword_only")
        growth = len(statements) - baseline
    finally:
        event.remove(engine, "before_cursor_execute", listener)

    assert items == [] and log.keyword_result_count == 0
    # Candidate select + log insert/refresh only; no BM25 aggregation statements.
    assert growth <= 4


def test_candidate_match_does_aggregate_statistics(db_session, monkeypatch):
    project, _units = _rarer_and_common_corpus(db_session)
    calls = []
    original = hybrid_retriever.compute_bm25_stats

    def recording(*args, **kwargs):
        calls.append(kwargs.get("tokens"))
        return original(*args, **kwargs)

    monkeypatch.setattr(hybrid_retriever, "compute_bm25_stats", recording)
    HybridRetriever(db_session).search(project.id, "alpha_rare", top_k=5, retrieval_mode="keyword_only")
    assert calls == [["alpha_rare"]]

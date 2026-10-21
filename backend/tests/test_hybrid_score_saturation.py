"""Regression: the ``final_score`` clamp must not erase the retrieval ordering.

``_normalize_scores`` maps the best fused candidate to ``1.0``; adding the ``+0.05``
rule boost and clamping at ``1.0`` then makes several plausible candidates show the
same score.  The historical sort key used the *clamped* score, so ties fell back to
``-knowledge_unit_id`` (newest unit first) and the genuinely better match lost the
top slot.  This reproduces on the real 5-unit knowledge corpus as well ("报送数据按
哪天取数" ranking the date rule below a generic rule).
"""

from types import SimpleNamespace

from app.models import (
    KnowledgeDocument,
    KnowledgeDocumentVersion,
    KnowledgeUnit,
    Project,
    TargetField,
    TargetTable,
)
from app.services.embeddings.mock import MockEmbeddingService
from app.services.retrieval import hybrid_retriever
from app.services.retrieval.hybrid_retriever import HybridRetriever
from app.services.retrieval.keyword_index import index_knowledge_unit


def _settings(**overrides):
    values = dict(
        keyword_top_k=500,
        vector_top_k=30,
        hybrid_keyword_weight=0.55,
        hybrid_vector_weight=0.45,
        vector_store_provider="mock",
        fusion_strategy="rrf",
        rrf_k=60,
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def _seed(db, texts, field_code="RPT_DT", field_codes=None):
    project = Project(name="评分饱和回归", bank_name="模拟机构")
    db.add(project)
    db.flush()
    table = TargetTable(project_id=project.id, table_code="EAST_REPORT", table_name="监管报送表")
    db.add(table)
    db.flush()
    field = TargetField(
        project_id=project.id,
        target_table_id=table.id,
        field_code=field_code,
        field_name="报送日期",
    )
    db.add(field)
    db.flush()
    document = KnowledgeDocument(
        project_id=project.id,
        file_name="dates.md",
        file_type="md",
        source_type="upload",
        storage_path="dates",
        document_status="indexed",
    )
    db.add(document)
    db.flush()
    version = KnowledgeDocumentVersion(
        project_id=project.id,
        document_id=document.id,
        version_no=1,
        file_name=document.file_name,
        storage_path="dates",
        file_hash="c" * 64,
    )
    db.add(version)
    db.flush()
    units = []
    for index, text in enumerate(texts):
        codes = field_codes or [field_code] * len(texts)
        unit = KnowledgeUnit(
            project_id=project.id,
            document_id=document.id,
            document_version_id=version.id,
            knowledge_type="manual_note",
            knowledge_scope="project",
            unit_type="paragraph",
            content=text,
            normalized_content=text,
            target_field_code=codes[index],
            source_file_name=document.file_name,
            confidentiality_level="internal",
            enabled=True,
            content_hash=format(200 + index, "064d"),
        )
        db.add(unit)
        db.flush()
        index_knowledge_unit(db, unit)
        units.append(unit)
    db.commit()
    return project, field, units


def _run(db, project, field, monkeypatch, units, query="报送日期口径取数"):
    monkeypatch.setattr(hybrid_retriever, "get_settings", lambda: _settings())
    monkeypatch.setattr(hybrid_retriever, "get_embedding_service", MockEmbeddingService)
    monkeypatch.setattr(
        hybrid_retriever,
        "get_active_index_version",
        lambda *args, **kwargs: SimpleNamespace(collection_name="c", vector_dimension=64, id=1),
    )
    # A (better date rule) ranks first in both sources, B second in both, C is a weak
    # vector-only distractor: min-max then compresses A and B into 1.0 / 0.97 so the
    # +0.05 rule boost saturates both.
    monkeypatch.setattr(
        hybrid_retriever,
        "get_vector_store",
        lambda *args, **kwargs: SimpleNamespace(
            search=lambda *a, **k: [
                SimpleNamespace(score=0.9, metadata={"knowledge_unit_id": units[1].id}),
                SimpleNamespace(score=0.8, metadata={"knowledge_unit_id": units[0].id}),
                SimpleNamespace(score=0.7, metadata={"knowledge_unit_id": units[2].id}),
            ]
        ),
    )
    return HybridRetriever(db).search(
        project.id,
        query,
        target_field_id=field.id,
        top_k=5,
        retrieval_mode="hybrid",
    )


def test_equal_clamped_scores_keep_the_better_fused_candidate_first(db_session, monkeypatch):
    project, field, units = _seed(
        db_session,
        [
            "报送数据取数口径说明",
            "报送日期口径：按报告期最后一日取数",
            "客户信息采集说明",
        ],
        field_codes=["RPT_DT", "RPT_DT", None],
    )

    log, items = _run(db_session, project, field, monkeypatch, units)

    ordered_ids = [item["knowledge_unit_id"] for item in items]
    # The date rule is the better match in both sources but was stored last (higher id),
    # so a clamped-score tie pushes it below the generic rule via the ``-id`` tie-break.
    assert ordered_ids[0] == units[1].id
    assert log.filters_json["fusion_strategy"] == "rrf"

    by_id = {item["knowledge_unit_id"]: item for item in items}
    # Both candidates satisfy the field-code rule, which is exactly what saturated the
    # displayed score: the contract keeps scores inside [0, 1] and stays stable.
    assert all(0.0 <= item["final_score"] <= 1.0 for item in items)
    assert by_id[units[0].id]["final_score"] == by_id[units[1].id]["final_score"] == 1.0
    assert by_id[units[1].id]["rerank_score"] == by_id[units[1].id]["final_score"]
    assert "字段代码匹配" in by_id[units[0].id]["match_reasons"]
    assert "字段代码匹配" in by_id[units[1].id]["match_reasons"]

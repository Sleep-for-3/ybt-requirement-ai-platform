"""⑥ Chunking strategy landing: fixed regression safety, semantic, degradation."""
import asyncio
import logging
import sys
from io import BytesIO
from types import SimpleNamespace

import pytest
from fastapi import UploadFile

from app.core.settings import get_settings
from app.models import Project
from app.services import document_ingestion
from app.services.text_processing import chunk_text, chunk_text_by_strategy
from app.services import text_processing


def _rearm_logger(name: str) -> None:
    """Re-enable a logger that an earlier test may have disabled.

    alembic's env.py calls ``logging.config.fileConfig(...)``, which sets
    ``disable_existing_loggers=True`` and permanently silences app loggers for the
    rest of the session. caplog then sees no records, so re-arm the logger under test.
    """
    logging.getLogger(name).disabled = False


@pytest.fixture(autouse=True)
def _fresh_settings():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


TEXTS = [
    ("客户号用于唯一识别客户。" * 80, 120, 20),
    ("abcdefghij" * 25, 37, 5),
    ("no-overlap-" * 30, 64, 0),
    ("段落一。段落二。段落三。", 8, 3),
    ("single", 1000, 150),
    ("", 1000, 150),
    ("\r\n\r\n  \r\n", 1000, 150),
]


@pytest.mark.parametrize("text,chunk_size,overlap", TEXTS)
def test_fixed_strategy_is_byte_identical_to_legacy_chunk_text(text, chunk_size, overlap):
    legacy = chunk_text(text, chunk_size=chunk_size, overlap=overlap)
    adapted = chunk_text_by_strategy(text, chunk_size=chunk_size, overlap=overlap, strategy="fixed")

    assert [(chunk.chunk_index, chunk.content) for chunk in adapted] == [
        (chunk.chunk_index, chunk.content) for chunk in legacy
    ]


@pytest.mark.parametrize("text,chunk_size,overlap", TEXTS)
def test_default_strategy_matches_legacy_behaviour(monkeypatch, text, chunk_size, overlap):
    monkeypatch.setenv("CHUNK_STRATEGY", "fixed")
    get_settings.cache_clear()

    legacy = chunk_text(text, chunk_size=chunk_size, overlap=overlap)
    adapted = chunk_text_by_strategy(text, chunk_size=chunk_size, overlap=overlap)

    assert [chunk.content for chunk in adapted] == [chunk.content for chunk in legacy]


def test_unconfigured_strategy_defaults_to_fixed():
    assert get_settings().chunk_strategy == "fixed"
    assert [chunk.content for chunk in chunk_text_by_strategy("a" * 2500)] == [
        chunk.content for chunk in chunk_text("a" * 2500)
    ]


def test_configured_fixed_strategy_keeps_default_chunk_size(monkeypatch):
    monkeypatch.setenv("CHUNK_STRATEGY", "fixed")
    get_settings.cache_clear()

    chunks = chunk_text_by_strategy("字" * 2500)
    assert [len(chunk.content) for chunk in chunks] == [1000, 1000, 800]


def _assert_slices_of(chunks, text, chunk_size):
    normalized = text.replace("\r\n", "\n").strip()
    cursor = 0
    for chunk in chunks:
        start = normalized.find(chunk.content, cursor)
        assert start >= 0, "chunk content is not a contiguous slice of the source text"
        assert len(chunk.content) <= chunk_size
        assert chunk.content
        cursor = start + 1
    return normalized


def test_semantic_strategy_splits_on_semantic_boundaries_and_keeps_offsets():
    text = (
        "第一段介绍客户信息与账户结构。\n\n"
        "第二段描述交易流水与对手方信息。\n\n"
        "第三段说明监管报送口径与校验规则。\n\n"
        "第四段记录历史整改情况。"
    )

    chunks = chunk_text_by_strategy(text, chunk_size=30, overlap=0, strategy="semantic")

    assert len(chunks) >= 2
    assert [chunk.chunk_index for chunk in chunks] == list(range(len(chunks)))
    _assert_slices_of(chunks, text, 200)
    joined = "".join(chunk.content for chunk in chunks)
    assert joined.replace("\n", "") == text.replace("\n", "")


def test_semantic_strategy_respects_chunk_size_bound_for_long_text():
    text = "。".join(f"第{index}条 说明字段{index}的口径" for index in range(400))

    chunks = chunk_text_by_strategy(text, chunk_size=120, overlap=20, strategy="semantic")

    assert len(chunks) > 1
    _assert_slices_of(chunks, text, 120)
    assert max(len(chunk.content) for chunk in chunks) <= 120


def test_semantic_strategy_overlap_repeats_context_between_chunks():
    text = "\n\n".join(f"第{index}段落内容" * 12 for index in range(6))

    chunks = chunk_text_by_strategy(text, chunk_size=100, overlap=25, strategy="semantic")

    assert len(chunks) > 1
    normalized = _assert_slices_of(chunks, text, 100)
    covered = set(range(len(normalized)))
    # Overlap must duplicate context: the chunks carry more characters than the source.
    assert sum(len(chunk.content) for chunk in chunks) > len(normalized)


def test_semantic_strategy_falls_back_to_fixed_when_chonkie_missing(monkeypatch, caplog):
    monkeypatch.setitem(sys.modules, "chonkie", None)
    text = "客户号用于唯一识别客户。" * 80

    _rearm_logger("app.services.text_processing")
    with caplog.at_level(logging.WARNING, logger="app.services.text_processing"):
        chunks = chunk_text_by_strategy(text, chunk_size=120, overlap=20, strategy="semantic")

    assert [chunk.content for chunk in chunks] == [
        chunk.content for chunk in chunk_text(text, chunk_size=120, overlap=20)
    ]
    assert any("falling back to fixed chunking" in record.message for record in caplog.records)


def test_semantic_strategy_falls_back_when_chonkie_raises(monkeypatch, caplog):
    class _BrokenChunker:
        def __init__(self, *args, **kwargs):
            raise RuntimeError("synthetic chonkie failure")

    monkeypatch.setitem(sys.modules, "chonkie", SimpleNamespace(RecursiveChunker=_BrokenChunker))

    _rearm_logger("app.services.text_processing")
    with caplog.at_level(logging.WARNING, logger="app.services.text_processing"):
        chunks = chunk_text_by_strategy("abcdef" * 100, chunk_size=50, overlap=5, strategy="semantic")

    assert [chunk.content for chunk in chunks] == [
        chunk.content for chunk in chunk_text("abcdef" * 100, chunk_size=50, overlap=5)
    ]
    assert any("RuntimeError" in str(record.message) for record in caplog.records) or any(
        "synthetic chonkie failure" in str(record.args) for record in caplog.records
    )


def test_semantic_strategy_handles_empty_and_rejects_invalid_sizes():
    assert chunk_text_by_strategy("", strategy="semantic") == []
    assert chunk_text_by_strategy("   \r\n ", strategy="semantic") == []

    with pytest.raises(ValueError, match="chunk_size must be positive"):
        chunk_text_by_strategy("abc", chunk_size=0, overlap=0, strategy="semantic")

    with pytest.raises(ValueError, match="overlap must be smaller"):
        chunk_text_by_strategy("abc", chunk_size=10, overlap=10, strategy="semantic")


def test_semantic_spans_ignore_degenerate_chonkie_pieces(monkeypatch):
    class _Chunker:
        def chunk(self, text):
            return [
                SimpleNamespace(start_index=None, end_index=None, text=""),
                SimpleNamespace(start_index=0, end_index=3, text=text[:3]),
                SimpleNamespace(start_index=0, end_index=0, text=""),
            ]

    monkeypatch.setitem(sys.modules, "chonkie", SimpleNamespace(RecursiveChunker=lambda **kwargs: _Chunker()))

    chunks = chunk_text_by_strategy("abcdef", chunk_size=10, overlap=0, strategy="semantic")
    normalized = "abcdef"
    assert [chunk.content for chunk in chunks] == ["abc"]
    assert "def" not in "".join(chunk.content for chunk in chunks)


def _stub_settings(**overrides):
    values = {"chunk_strategy": "fixed", "chunk_size": 12, "chunk_overlap": 0}
    values.update(overrides)
    return SimpleNamespace(**values)


def _run_ingest_document(db_session, monkeypatch, settings, filename="notes.txt", payload=None):
    payload = payload if payload is not None else "段落一内容。段落二内容。段落三内容。段落四内容。"
    captured = {}
    monkeypatch.setattr(document_ingestion, "get_settings", lambda: settings)
    monkeypatch.setattr(
        document_ingestion,
        "get_storage_service",
        lambda: SimpleNamespace(save=lambda *args, **kwargs: SimpleNamespace(storage_key="synthetic-object")),
    )
    monkeypatch.setattr(document_ingestion, "get_embedding_service", lambda: SimpleNamespace())
    monkeypatch.setattr(
        document_ingestion,
        "embed_with_observability",
        lambda db, project_id, service, texts, levels: [[0.0, 0.0] for _ in texts],
    )
    monkeypatch.setattr(
        document_ingestion,
        "get_vector_store",
        lambda: SimpleNamespace(upsert=lambda records: captured.setdefault("records", records)),
    )
    upload = UploadFile(filename=filename, file=BytesIO(payload.encode("utf-8")))
    document, chunks = asyncio.run(document_ingestion.ingest_document(db_session, 1, "manual_note", upload))
    return document, chunks, captured


def test_ingest_document_uses_configured_fixed_chunk_size(db_session, monkeypatch):
    project = Project(name="chunk-fixed")
    db_session.add(project)
    db_session.flush()

    document, chunks, captured = _run_ingest_document(db_session, monkeypatch, _stub_settings())

    assert document.id is not None
    assert chunks
    assert all(len(chunk.content) <= 12 for chunk in chunks)
    assert [chunk.chunk_index for chunk in chunks] == list(range(len(chunks)))
    assert "".join(chunk.content for chunk in chunks).startswith("段落一内容。段落二")
    assert len(captured["records"]) == len(chunks)


def test_ingest_document_uses_semantic_strategy_when_configured(db_session, monkeypatch):
    project = Project(name="chunk-semantic")
    db_session.add(project)
    db_session.flush()

    payload = "\n\n".join(f"第{index}段 监管口径说明" * 6 for index in range(5))
    document, chunks, _captured = _run_ingest_document(
        db_session,
        monkeypatch,
        _stub_settings(chunk_strategy="semantic", chunk_size=60, chunk_overlap=10),
        payload=payload,
    )

    assert document.id is not None
    assert len(chunks) > 1
    normalized = payload.replace("\r\n", "\n").strip()
    assert all(len(chunk.content) <= 60 for chunk in chunks)
    assert all(chunk.content in normalized for chunk in chunks)
    expected = text_processing.chunk_text_by_strategy(payload, chunk_size=60, overlap=10, strategy="semantic")
    assert [chunk.content for chunk in chunks] == [chunk.content for chunk in expected]
    assert len({chunk.content for chunk in chunks}) == len(chunks)

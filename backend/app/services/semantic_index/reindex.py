import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from sqlalchemy import func, select

from app.models import (
    BackgroundJobItem,
    EmbeddingIndexVersion,
    EmbeddingRecord,
    KnowledgeDocument,
    KnowledgeUnit,
    Project,
)
from app.services.embeddings import get_embedding_service
from app.services.embeddings.observability import (
    embed_with_observability,
    ensure_embedding_external_allowed,
)
from app.services.semantic_index.chunking import (
    DEFAULT_MAX_TOKENS,
    FRAGMENT_STRATEGY_VERSION,
    build_fragment_vector_records,
    plan_fragments,
)
from app.services.semantic_index.versioning import (
    activate_index_version,
    build_collection_name,
)
from app.services.vector import get_vector_store
from app.services.vector.knowledge_record import build_knowledge_vector_record


CHUNK_STRATEGY_VERSION = "existing-knowledge-unit-v1"
INDEX_CONFIG_VERSION = "formal-semantic-index-v1"
# 允许的索引分片策略。默认仍是"一个知识单元一个向量"，分片策略必须由建索引请求显式选择，
# 不做按长度自动切换——否则同一个语料在不同批次里会得到不同规模的索引，无法对账。
SUPPORTED_CHUNK_STRATEGIES = (CHUNK_STRATEGY_VERSION, FRAGMENT_STRATEGY_VERSION)


def resolve_chunk_strategy(value: object) -> str:
    """Validate an explicitly requested chunk strategy; never guess or fall back silently."""
    strategy = str(value or CHUNK_STRATEGY_VERSION)
    if strategy not in SUPPORTED_CHUNK_STRATEGIES:
        raise ValueError(
            f"Unsupported chunk strategy: {strategy}. "
            f"Supported values are {list(SUPPORTED_CHUNK_STRATEGIES)}."
        )
    return strategy


def resolve_fragment_budget(value: object) -> int:
    """Validate the fragment token budget used by the fragment chunk strategy."""
    if value is None or value == "":
        return DEFAULT_MAX_TOKENS
    try:
        budget = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("fragment_max_tokens must be an integer token budget") from exc
    if budget <= 0:
        raise ValueError("fragment_max_tokens must be a positive integer token budget")
    return budget


@dataclass(frozen=True)
class CorpusSnapshot:
    project_id: int
    document_count: int
    chunk_count: int
    corpus_hash: str
    units: tuple[KnowledgeUnit, ...]


def build_corpus_snapshot(db, project_id: int) -> CorpusSnapshot:
    """Freeze the currently enabled, non-archived project corpus without recutting it."""
    units = tuple(db.scalars(
        select(KnowledgeUnit)
        .join(KnowledgeDocument, KnowledgeDocument.id == KnowledgeUnit.document_id)
        .where(
            KnowledgeUnit.project_id == project_id,
            KnowledgeUnit.enabled.is_(True),
            KnowledgeDocument.document_status != "archived",
        )
        .order_by(KnowledgeUnit.id)
    ).all())
    material = "\n".join(
        f"{unit.id}:{unit.document_id}:{unit.document_version_id}:{unit.content_hash}"
        for unit in units
    )
    return CorpusSnapshot(
        project_id=project_id,
        document_count=len({unit.document_id for unit in units}),
        chunk_count=len(units),
        corpus_hash=hashlib.sha256(material.encode("utf-8")).hexdigest(),
        units=units,
    )


def reindex_project_knowledge(
    db,
    job,
    *,
    embedding_service=None,
    vector_store_factory: Callable | None = None,
) -> dict:
    payload = job.payload_summary_json or {}
    snapshot = build_corpus_snapshot(db, int(job.project_id))
    if snapshot.corpus_hash != payload.get("corpus_hash"):
        raise ValueError("Knowledge corpus changed after submission; submit a fresh reindex task")
    expected_dimension = int(payload["vector_dimension"])
    batch_size = max(1, min(int(payload.get("batch_size", 64)), 256))
    embedding = embedding_service or get_embedding_service()
    provider = str(getattr(embedding, "provider", embedding.last_call.provider))
    model_name = str(getattr(embedding, "model", embedding.last_call.model))
    if provider != payload.get("provider") or model_name != payload.get("model_name"):
        raise ValueError("Embedding runtime changed after submission; submit a fresh reindex task")
    ensure_embedding_external_allowed(
        db,
        snapshot.project_id,
        embedding,
        [unit.confidentiality_level for unit in snapshot.units],
        persist_denial=True,
    )

    # 提交接口写入的是 `chunk_strategy_version`（见 api/knowledge_rag.py 的 job_payload），
    # 而历史调用方与单元测试用的是 `chunk_strategy`；只读其中一个键会让用户选的分片
    # 策略被静默降级成默认策略（真实事故：选了 knowledge-fragment-v1，任务结果里却是
    # existing-knowledge-unit-v1，且没有任何提示）。
    requested_value = payload.get("chunk_strategy") or payload.get("chunk_strategy_version")
    requested_strategy = resolve_chunk_strategy(requested_value)
    fragment_mode = requested_strategy == FRAGMENT_STRATEGY_VERSION
    fragment_max_tokens = resolve_fragment_budget(payload.get("fragment_max_tokens"))

    version = db.scalar(
        select(EmbeddingIndexVersion).where(
            EmbeddingIndexVersion.background_job_id == job.id
        )
    )
    if version is None:
        _progress(db, job, 3, "creating_index_version")
        project = db.get(Project, snapshot.project_id)
        version = EmbeddingIndexVersion(
            project_id=snapshot.project_id,
            institution_id=project.institution_id if project else None,
            background_job_id=job.id,
            provider=provider,
            model_name=model_name,
            model_fingerprint=str(payload["model_fingerprint"]),
            vector_dimension=expected_dimension,
            distance_metric="COSINE",
            collection_name=f"pending_semantic_job_{job.id}",
            corpus_hash=snapshot.corpus_hash,
            status="preparing",
            document_count=snapshot.document_count,
            chunk_count=snapshot.chunk_count,
            indexed_count=0,
            failed_count=0,
            config_json={
                "batch_size": batch_size,
                "chunk_strategy_version": requested_strategy,
                "index_config_version": INDEX_CONFIG_VERSION,
                **(
                    {
                        "fragment_max_tokens": fragment_max_tokens,
                        "fragment_counter": "estimate-tokens-v1",
                    }
                    if fragment_mode
                    else {}
                ),
            },
            validation_json={},
            created_by=str(job.created_by),
        )
        db.add(version)
        db.flush()
        version.collection_name = build_collection_name(
            project_id=snapshot.project_id,
            version_id=version.id,
            model_fingerprint=version.model_fingerprint,
            dimension=version.vector_dimension,
        )
        db.commit()
        db.refresh(version)
    else:
        version.status = "indexing"
        version.failure_summary = None
        db.commit()

    store_factory = vector_store_factory or (
        lambda collection, dimension: get_vector_store(collection, dimension)
    )
    store = store_factory(version.collection_name, expected_dimension)
    sample_vector: list[float] | None = None
    current_item_id: int | None = None
    try:
        version.status = "indexing"
        _progress(db, job, 5, "preparing_corpus")
        store.ensure_collection(expected_dimension)
        total = snapshot.chunk_count
        planned: dict[int, list] = {}
        if fragment_mode:
            for unit in snapshot.units:
                planned[unit.id] = plan_fragments(unit, max_tokens=fragment_max_tokens)
            expected_record_count = sum(len(items) for items in planned.values())
        else:
            expected_record_count = total
        batch_total = max(1, (total + batch_size - 1) // batch_size)
        for batch_number, offset in enumerate(range(0, total, batch_size), start=1):
            db.refresh(job)
            if job.status == "cancelled":
                version.status = "cancelled"
                version.completed_at = datetime.now(timezone.utc)
                db.commit()
                return {
                    "success_count": 0,
                    "failed_count": 0,
                    "cancelled": True,
                    "index_version_id": version.id,
                }
            item_key = f"batch-{batch_number:06d}"
            item = db.scalar(select(BackgroundJobItem).where(
                BackgroundJobItem.background_job_id == job.id,
                BackgroundJobItem.item_key == item_key,
            ))
            if item is not None and item.status == "completed":
                continue
            if item is None:
                item = BackgroundJobItem(
                    background_job_id=job.id,
                    item_key=item_key,
                    status="running",
                    result_summary_json={},
                )
                db.add(item)
            else:
                item.status = "running"
                item.error_message = None
            db.commit()
            current_item_id = item.id

            batch = snapshot.units[offset : offset + batch_size]
            if fragment_mode:
                texts: list[str] = []
                levels: list[str] = []
                for unit in batch:
                    for fragment in planned.get(unit.id, []):
                        texts.append(fragment.text)
                        levels.append(unit.confidentiality_level)
            else:
                texts = [unit.content for unit in batch]
                levels = [unit.confidentiality_level for unit in batch]
            progress = 8 + int((offset / max(total, 1)) * 75)
            _progress(
                db,
                job,
                progress,
                f"embedding_chunks {offset}/{total} batch {batch_number}/{batch_total}",
            )
            vectors = embed_with_observability(
                db,
                snapshot.project_id,
                embedding,
                texts,
                levels,
            )
            if len(vectors) != len(texts):
                raise ValueError("Embedding result count does not match the corpus batch")
            if any(len(vector) != expected_dimension for vector in vectors):
                raise ValueError("Embedding dimension does not match the configured index dimension")
            unit_records: dict[int, list] = {}
            if fragment_mode:
                records: list = []
                cursor = 0
                for unit in batch:
                    fragments = planned.get(unit.id, [])
                    if not fragments:
                        continue
                    unit_vectors = vectors[cursor : cursor + len(fragments)]
                    cursor += len(fragments)
                    built = build_fragment_vector_records(
                        unit,
                        unit_vectors,
                        fragments,
                        index_version_id=version.id,
                        model_fingerprint=version.model_fingerprint,
                        institution_id=version.institution_id,
                    )
                    if len(built) != len(fragments):
                        raise ValueError("Fragment record count does not match planned fragments")
                    records.extend(built)
                    unit_records[unit.id] = built
            else:
                records = [
                    build_knowledge_vector_record(
                        unit,
                        vector,
                        index_version_id=version.id,
                        model_fingerprint=version.model_fingerprint,
                        institution_id=version.institution_id,
                    )
                    for unit, vector in zip(batch, vectors, strict=True)
                ]
                unit_records = {unit.id: [record] for unit, record in zip(batch, records, strict=True)}
            _progress(db, job, min(88, progress + 3), f"writing_milvus batch {batch_number}/{batch_total}")
            store.upsert_embeddings(records)
            if records and sample_vector is None:
                sample_vector = records[0].embedding
            for unit in batch:
                flat_records = unit_records.get(unit.id) or []
                if not flat_records:
                    continue
                record_ids = [item.id for item in flat_records]
                embedding_record = db.scalar(select(EmbeddingRecord).where(
                    EmbeddingRecord.embedding_index_version_id == version.id,
                    EmbeddingRecord.knowledge_unit_id == unit.id,
                    EmbeddingRecord.content_hash == unit.content_hash,
                ))
                if embedding_record is None:
                    db.add(EmbeddingRecord(
                        project_id=snapshot.project_id,
                        knowledge_unit_id=unit.id,
                        embedding_index_version_id=version.id,
                        embedding_provider=provider,
                        embedding_model=model_name,
                        vector_store_provider="milvus",
                        vector_record_id=record_ids[0],
                        vector_record_ids_json=record_ids,
                        embedding_dimension=expected_dimension,
                        content_hash=unit.content_hash,
                        status="active",
                    ))
                else:
                    # 重跑同一单元时，向量 id 会随策略/批次变化；记录最新一组，避免"账上只有一条"。
                    embedding_record.vector_record_id = record_ids[0]
                    embedding_record.vector_record_ids_json = record_ids
            item.status = "completed"
            item.result_summary_json = {
                "batch_number": batch_number,
                "chunk_count": len(batch),
                "first_chunk_id": batch[0].id if batch else None,
                "last_chunk_id": batch[-1].id if batch else None,
            }
            version.indexed_count = min(total, offset + len(batch))
            db.commit()
            current_item_id = None

        _progress(db, job, 90, "validating_index")
        version.status = "validating"
        db.commit()
        validation = store.validate_index(
            expected_count=expected_record_count,
            expected_dimension=expected_dimension,
        )
        if sample_vector is None and snapshot.units:
            first_record = db.scalar(select(EmbeddingRecord).where(
                EmbeddingRecord.embedding_index_version_id == version.id
            ).order_by(EmbeddingRecord.id))
            if first_record is None:
                raise ValueError("Index checkpoint is missing its embedding records")
            first_unit = db.get(KnowledgeUnit, first_record.knowledge_unit_id)
            sample_vector = embed_with_observability(
                db,
                snapshot.project_id,
                embedding,
                [first_unit.content],
                [first_unit.confidentiality_level],
            )[0]
        if sample_vector is not None:
            validation["sample_search_hit_count"] = len(store.search(sample_vector, 1))
            validation["valid"] = bool(validation["valid"] and validation["sample_search_hit_count"] > 0)
        if not validation.get("valid"):
            raise ValueError("Milvus index integrity validation failed")
        version.validation_json = validation
        version.status = "validated"
        db.commit()

        _progress(db, job, 97, "activating_index")
        activate_index_version(db, version)
        db.commit()
        _progress(db, job, 99, "completed")
        return {
            "success_count": 1,
            "failed_count": 0,
            "index_version_id": version.id,
            "embedding_provider": provider,
            "embedding_model": model_name,
            "vector_dimension": expected_dimension,
            "document_count": snapshot.document_count,
            "chunk_count": snapshot.chunk_count,
            "record_count": expected_record_count,
            "chunk_strategy_version": requested_strategy,
            "indexed_count": version.indexed_count,
            "collection": version.collection_name,
            "validation": {
                "actual_count": validation.get("actual_count"),
                "sample_search_hit_count": validation.get("sample_search_hit_count", 0),
                "valid": True,
            },
        }
    except Exception as exc:
        db.rollback()
        failed_version = db.get(EmbeddingIndexVersion, version.id)
        failed_item = db.get(BackgroundJobItem, current_item_id) if current_item_id else None
        if failed_item is not None:
            failed_item.status = "failed"
            failed_item.error_message = (
                f"{type(exc).__name__}: semantic index batch failed"
            )
        if failed_version is not None and failed_version.status != "active":
            failed_version.status = "failed"
            failed_version.failed_count = max(
                0, failed_version.chunk_count - failed_version.indexed_count
            )
            failed_version.failure_summary = (
                f"{type(exc).__name__}: formal semantic indexing did not activate"
            )
            failed_version.completed_at = datetime.now(timezone.utc)
            db.commit()
        raise


def _progress(db, job, progress: int, step: str) -> None:
    job.progress = max(job.progress or 0, min(progress, 99))
    job.current_step = step
    db.commit()

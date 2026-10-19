"""Cross-encoder reranking for hybrid retrieval.

Contract (landing plan item ②):

* ``settings.reranker_enabled`` defaults to False. While it is False this module
  is completely inert: ``fastembed`` is never imported, no ONNX session is
  created and no model file is downloaded, so the disabled path costs one
  attribute read plus the cost of building a new list reference.
* Every failure mode (missing optional dependency, download error, ONNX/runtime
  error, unusable score output) degrades to the incoming order and is reported
  through :class:`RerankOutcome` diagnostics instead of raising, so retrieval
  never becomes unavailable because of the optional reranker.
* Only the first ``settings.reranker_top_k`` candidates are scored, and the
  reranked slice is re-sorted with the same key layout used by the retriever
  (``authority_rank`` first), so regulatory authority ordering is preserved and
  the cross-encoder only refines ordering inside an authority tier.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

DEFAULT_RERANKER_TOP_K = 50
DEFAULT_RERANKER_MODEL = "BAAI/bge-reranker-base"

# ``fastembed`` does not re-export TextCrossEncoder from its package root; the
# only import that works on fastembed 0.8.0 is the rerank subpackage.
_CROSS_ENCODER_IMPORT = "fastembed.rerank.cross_encoder"

_MODEL_CACHE: dict[tuple[str, str], object] = {}
_FAILURE_CACHE: dict[tuple[str, str], str] = {}


@dataclass(frozen=True)
class RerankOutcome:
    """Result of one reranking attempt; always carries the items to return."""

    items: list
    enabled: bool
    applied: bool
    reason: str | None = None
    model: str | None = None
    candidate_count: int = 0
    reranked_count: int = 0
    degraded: bool = False

    def diagnostics(self) -> dict:
        """JSON-safe diagnostics, persisted into RetrievalLog.filters_json."""
        return {
            "enabled": self.enabled,
            "applied": self.applied,
            "degraded": self.degraded,
            "reason": self.reason,
            "model": self.model,
            "candidate_count": self.candidate_count,
            "reranked_count": self.reranked_count,
        }


def is_enabled(settings) -> bool:
    """True only when the reranker is switched on; reads no model state."""
    return bool(getattr(settings, "reranker_enabled", False))


def reranker_top_k(settings) -> int:
    value = getattr(settings, "reranker_top_k", DEFAULT_RERANKER_TOP_K)
    try:
        return int(value)
    except (TypeError, ValueError):
        return DEFAULT_RERANKER_TOP_K


def sigmoid(value: float) -> float:
    """Map unbounded cross-encoder logits into (0, 1) without overflowing."""
    score = float(value)
    if score >= 0.0:
        return 1.0 / (1.0 + math.exp(-score))
    exponent = math.exp(score)
    return exponent / (1.0 + exponent)


def reset_cache() -> None:
    """Drop cached models/failures. Test hook; production never needs it."""
    _MODEL_CACHE.clear()
    _FAILURE_CACHE.clear()


def load_cross_encoder(model_name: str, cache_dir: str | None = None):
    """Load (and cache) a fastembed cross encoder.

    Returns ``(model, None)`` on success or ``(None, reason)`` on failure. A
    failed load is cached too, so a broken optional dependency is not retried
    (and does not re-attempt a download) on every single query.
    """
    key = (str(model_name), str(cache_dir or ""))
    cached = _MODEL_CACHE.get(key)
    if cached is not None:
        return cached, None
    known_failure = _FAILURE_CACHE.get(key)
    if known_failure is not None:
        return None, known_failure
    try:
        from fastembed.rerank.cross_encoder import TextCrossEncoder
    except Exception as error:  # pragma: no cover - depends on install state
        reason = f"import_failed: {type(error).__name__}: {error}"
        _FAILURE_CACHE[key] = reason
        return None, reason
    try:
        model = TextCrossEncoder(model_name=str(model_name), cache_dir=cache_dir or None)
    except Exception as error:
        reason = f"load_failed: {type(error).__name__}: {error}"
        _FAILURE_CACHE[key] = reason
        return None, reason
    _MODEL_CACHE[key] = model
    return model, None


def _default_document_text(item) -> str:
    title = item.get("title") or ""
    content = item.get("content") or ""
    return f"{title}\n{content}".strip()


def rerank_items(items, query, settings=None, *, document_text=None) -> RerankOutcome:
    """Rerank the top ``settings.reranker_top_k`` items against ``query``.

    Never raises: any failure returns ``items`` untouched with a diagnostic
    reason. The returned list is always a fresh list of the same dict objects
    (with ``rerank_score`` replaced on the reranked head), so callers can keep
    treating the result exactly like the fused ranking.
    """
    if settings is None:  # pragma: no cover - callers normally inject settings
        from app.core.settings import get_settings

        settings = get_settings()

    original = list(items)
    if not is_enabled(settings):
        return RerankOutcome(items=original, enabled=False, applied=False, reason="disabled")

    model_name = getattr(settings, "reranker_model", DEFAULT_RERANKER_MODEL) or DEFAULT_RERANKER_MODEL
    cache_dir = getattr(settings, "reranker_cache_dir", "") or None
    head_size = reranker_top_k(settings)
    head = original[:head_size] if head_size > 0 else []
    base = dict(
        enabled=True,
        model=str(model_name),
        candidate_count=len(head),
    )

    if not original or not head:
        return RerankOutcome(items=original, applied=False, reason="empty_candidates", **base)
    if not (query or "").strip():
        return RerankOutcome(items=original, applied=False, reason="empty_query", **base)

    model, failure = load_cross_encoder(str(model_name), cache_dir)
    if model is None:
        return RerankOutcome(items=original, applied=False, reason=failure, degraded=True, **base)

    documents = [document_text(item) if document_text else _default_document_text(item) for item in head]
    try:
        scores = [float(score) for score in model.rerank(query=query, documents=documents)]
    except Exception as error:
        reason = f"inference_failed: {type(error).__name__}: {error}"
        return RerankOutcome(items=original, applied=False, reason=reason, degraded=True, **base)
    if len(scores) != len(head):
        reason = f"score_count_mismatch: expected {len(head)}, got {len(scores)}"
        return RerankOutcome(items=original, applied=False, reason=reason, degraded=True, **base)

    rescored = []
    for item, score in zip(head, scores):
        updated = dict(item)
        updated["rerank_score"] = round(sigmoid(score), 4)
        rescored.append(updated)
    # Keep normative authority ordering dominant; the cross encoder refines
    # ordering only inside one authority tier.
    rescored.sort(
        key=lambda item: (item["authority_rank"], item["rerank_score"], -item["knowledge_unit_id"]),
        reverse=True,
    )
    return RerankOutcome(
        items=rescored + original[head_size:],
        applied=True,
        reason=None,
        reranked_count=len(rescored),
        **base,
    )

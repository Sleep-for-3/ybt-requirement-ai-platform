import logging
from dataclasses import dataclass

logger = logging.getLogger("app.services.text_processing")


@dataclass(frozen=True)
class TextChunk:
    chunk_index: int
    content: str


def chunk_text(text: str, chunk_size: int = 1000, overlap: int = 150) -> list[TextChunk]:
    normalized = text.replace("\r\n", "\n").strip()
    if not normalized:
        return []
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if overlap >= chunk_size:
        raise ValueError("overlap must be smaller than chunk_size")

    chunks: list[TextChunk] = []
    start = 0
    index = 0
    while start < len(normalized):
        end = min(start + chunk_size, len(normalized))
        content = normalized[start:end]
        chunks.append(TextChunk(chunk_index=index, content=content))
        if end == len(normalized):
            break
        start = end - overlap
        index += 1
    return chunks


def _semantic_spans(text: str, chunk_size: int) -> list[tuple[int, int]]:
    """Return non-overlapping recursive/semantic spans of ``text`` via chonkie.

    Raises ImportError when the optional chonkie dependency is unavailable so the
    caller can fall back to the fixed strategy.
    """
    from chonkie import RecursiveChunker  # optional dependency, imported lazily

    chunker = RecursiveChunker(tokenizer="character", chunk_size=chunk_size, min_characters_per_chunk=1)
    spans: list[tuple[int, int]] = []
    position = 0
    for piece in chunker.chunk(text):
        start = getattr(piece, "start_index", None)
        end = getattr(piece, "end_index", None)
        if not isinstance(start, int) or not isinstance(end, int) or end <= start:
            content = getattr(piece, "text", "")
            start, end = position, position + len(content)
        start = max(0, min(start, len(text)))
        end = max(start, min(end, len(text)))
        if end <= start:
            continue
        spans.append((start, end))
        position = end
    return spans


def chunk_text_by_strategy(
    text: str,
    chunk_size: int = 1000,
    overlap: int = 150,
    strategy: str | None = None,
) -> list[TextChunk]:
    """Chunk text using the configured strategy, degrading semantic to fixed.

    ``strategy=None`` resolves ``settings.chunk_strategy``.  The "fixed" path is
    byte-for-byte the historical :func:`chunk_text` behaviour, so switching the
    default keeps existing ingestion output identical.
    """
    resolved = (strategy if strategy is not None else _configured_strategy()).strip().lower()
    if resolved != "semantic":
        return chunk_text(text, chunk_size=chunk_size, overlap=overlap)
    normalized = text.replace("\r\n", "\n").strip()
    if not normalized:
        return []
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if overlap >= chunk_size:
        raise ValueError("overlap must be smaller than chunk_size")
    try:
        spans = _semantic_spans(normalized, chunk_size)
    except Exception as exc:  # chonkie missing or unusable: keep ingesting as before
        logger.warning(
            "semantic chunking unavailable (%s: %s); falling back to fixed chunking",
            type(exc).__name__,
            exc,
        )
        return chunk_text(normalized, chunk_size=chunk_size, overlap=overlap)
    if not spans:
        return chunk_text(normalized, chunk_size=chunk_size, overlap=overlap)

    chunks: list[TextChunk] = []
    for span_start, span_end in spans:
        # Keep every chunk within chunk_size while carrying the overlap backward.
        start = max(span_start - overlap, span_end - chunk_size, 0) if overlap else span_start
        position = start
        while position < span_end:
            stop = min(position + chunk_size, span_end)
            chunks.append(TextChunk(chunk_index=len(chunks), content=normalized[position:stop]))
            if stop == span_end:
                break
            position = stop - overlap
    return chunks


def _configured_strategy() -> str:
    from app.core.settings import get_settings

    return str(getattr(get_settings(), "chunk_strategy", "fixed") or "fixed")

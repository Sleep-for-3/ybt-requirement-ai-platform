from dataclasses import dataclass


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

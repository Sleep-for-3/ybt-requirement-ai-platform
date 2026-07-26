from app.services.text_processing import chunk_text


def test_chunk_text_preserves_content_order_and_metadata():
    text = "客户号用于唯一识别客户。" * 80

    chunks = chunk_text(text, chunk_size=120, overlap=20)

    assert len(chunks) > 1
    assert chunks[0].chunk_index == 0
    assert chunks[0].content.startswith("客户号")
    assert chunks[1].content.startswith(chunks[0].content[-20:])
    assert all(chunk.content for chunk in chunks)


def test_chunk_text_rejects_invalid_overlap():
    try:
        chunk_text("abc", chunk_size=10, overlap=10)
    except ValueError as exc:
        assert "overlap must be smaller" in str(exc)
    else:
        raise AssertionError("Expected ValueError")

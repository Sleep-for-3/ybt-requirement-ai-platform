from fastapi.testclient import TestClient

from app import local_embedding_server


class _FakeEmbeddingModel:
    def embed(self, texts: list[str]):
        for index, _ in enumerate(texts):
            yield [float(index + 1), 0.0, 0.0]

    def query_embed(self, texts: list[str]):
        for _ in texts:
            yield [9.0, 0.0, 0.0]


def test_openai_compatible_embedding_endpoint_returns_ordered_vectors(monkeypatch) -> None:
    monkeypatch.setattr(local_embedding_server, "get_embedding_model", lambda: _FakeEmbeddingModel())

    with TestClient(local_embedding_server.app) as client:
        response = client.post(
            "/v1/embeddings",
            json={"model": "BAAI/bge-small-zh-v1.5", "input": ["第一段", "第二段"]},
        )

    assert response.status_code == 200
    assert response.json() == {
        "object": "list",
        "model": "BAAI/bge-small-zh-v1.5",
        "data": [
            {"object": "embedding", "index": 0, "embedding": [1.0, 0.0, 0.0]},
            {"object": "embedding", "index": 1, "embedding": [2.0, 0.0, 0.0]},
        ],
        "usage": {"prompt_tokens": 0, "total_tokens": 0},
    }


def test_embedding_endpoint_rejects_wrong_model(monkeypatch) -> None:
    monkeypatch.setattr(local_embedding_server, "get_embedding_model", lambda: _FakeEmbeddingModel())

    with TestClient(local_embedding_server.app) as client:
        response = client.post(
            "/v1/embeddings",
            json={"model": "wrong-model", "input": ["文本"]},
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "Unsupported embedding model"


def test_embedding_endpoint_uses_query_encoder_when_requested(monkeypatch) -> None:
    monkeypatch.setattr(local_embedding_server, "get_embedding_model", lambda: _FakeEmbeddingModel())

    with TestClient(local_embedding_server.app) as client:
        response = client.post(
            "/v1/embeddings",
            headers={"X-YBT-Embedding-Input-Type": "query"},
            json={
                "model": "BAAI/bge-small-zh-v1.5",
                "input": ["贷款余额如何计算"],
            },
        )

    assert response.status_code == 200
    assert response.json()["data"][0]["embedding"] == [9.0, 0.0, 0.0]

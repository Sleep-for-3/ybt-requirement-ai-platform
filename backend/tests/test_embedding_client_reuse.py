"""embedding 客户端复用的契约测试。

真实事故：每次 ``/embeddings`` 都 ``httpx.post`` 新建 Client，回环地址单次多花
650–1000ms，检索 P50 被拖到 1s 以上。这里锁住"同一配置复用同一 Client、
不同配置不复用、关闭后重建"三条契约。
"""

from __future__ import annotations

from app.services.embeddings import openai_compatible


def _clear_cache() -> None:
    for client in openai_compatible._CLIENT_CACHE.values():
        client.close()
    openai_compatible._CLIENT_CACHE.clear()


def test_client_is_reused_for_same_configuration() -> None:
    _clear_cache()
    first = openai_compatible._embedding_client("http://127.0.0.1:11434/v1", 60.0, False)
    second = openai_compatible._embedding_client("http://127.0.0.1:11434/v1", 60.0, False)
    assert first is second
    _clear_cache()


def test_client_is_not_shared_across_configurations() -> None:
    _clear_cache()
    loopback = openai_compatible._embedding_client("http://127.0.0.1:11434/v1", 60.0, False)
    proxied = openai_compatible._embedding_client("http://127.0.0.1:11434/v1", 60.0, True)
    other = openai_compatible._embedding_client("http://127.0.0.1:11435/v1", 60.0, False)
    assert loopback is not proxied
    assert loopback is not other
    _clear_cache()


def test_closed_client_is_rebuilt() -> None:
    _clear_cache()
    client = openai_compatible._embedding_client("http://127.0.0.1:11434/v1", 30.0, False)
    client.close()
    rebuilt = openai_compatible._embedding_client("http://127.0.0.1:11434/v1", 30.0, False)
    assert rebuilt is not client
    assert not rebuilt.is_closed
    _clear_cache()

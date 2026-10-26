"""embedding 客户端连接复用：本地/局域网 provider 不再每次请求都新建连接。

真实事故（性能）：每次 ``/embeddings`` 调用都 ``httpx.post(...)``，httpx 会新建
Client、解析代理环境、构建连接；对回环地址单次多花约 650–1000ms，检索
vector/hybrid 的 P50 被拖到 1s 以上。这里改成按 ``(base_url, timeout, trust_env)``
复用一个 ``httpx.Client``（连接池 + keep-alive），进程内并发安全。

测试注入点：``_embedding_client`` 是模块级函数，测试可 monkeypatch 它返回伪客户端，
仍能断言请求 URL、headers 与 JSON 体。
"""

from __future__ import annotations

import sys
import threading
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parent


def patch(path: Path, replacements: list[tuple[str, str]]) -> None:
    raw = path.read_bytes().decode("utf-8")
    text = raw.replace("\r\n", "\n")
    for old, new in replacements:
        if new in text:
            print(f"skip (already applied): {old.splitlines()[0][:60]}")
            continue
        count = text.count(old)
        if count != 1:
            raise SystemExit(f"anchor count={count} in {path} :: {old.splitlines()[0][:80]}")
        text = text.replace(old, new)
    path.write_bytes(text.replace("\n", "\r\n").encode("utf-8"))
    print(f"patched {path}")


MODULE_HEAD = '''import math
import time

import httpx

'''

MODULE_HEAD_NEW = '''import math
import threading
import time

import httpx

'''

HELPER = '''_CLIENT_LOCK = threading.Lock()
_CLIENT_CACHE: dict[tuple[str, float, bool], httpx.Client] = {}


def _embedding_client(base_url: str, timeout_seconds: float, trust_env: bool) -> httpx.Client:
    """按 (base_url, timeout, trust_env) 复用 Client，避免每次请求重建连接/SSL 上下文。

    ``httpx.Client`` 的连接池是线程安全的；进程退出时由操作系统回收。
    """
    key = (base_url, float(timeout_seconds), bool(trust_env))
    client = _CLIENT_CACHE.get(key)
    if client is not None and not client.is_closed:
        return client
    with _CLIENT_LOCK:
        client = _CLIENT_CACHE.get(key)
        if client is None or client.is_closed:
            client = httpx.Client(
                timeout=timeout_seconds,
                follow_redirects=False,
                trust_env=trust_env,
                limits=httpx.Limits(max_keepalive_connections=8, max_connections=16),
            )
            _CLIENT_CACHE[key] = client
        return client


'''

POST_OLD = '''                if self.transport is None:
                    # Trusting the ambient proxy environment for a loopback or LAN
                    # embedding endpoint cost ~1.5s per query: httpx built a fresh
                    # HTTPS proxy transport (and SSL context) before every call.
                    # Local providers are addressed directly, so skip the proxy env.
                    response = httpx.post(
                        f"{self.base_url}/embeddings",
                        json=payload,
                        headers=headers,
                        timeout=self.timeout_seconds,
                        follow_redirects=False,
                        trust_env=not self.local_only,
                    )
'''

POST_NEW = '''                if self.transport is None:
                    # 复用 Client：新建 Client 会重新解析代理环境并构建连接/SSL 上下文，
                    # 对回环地址单次多花 650ms+；本地 provider 走直连（trust_env=False）。
                    client = _embedding_client(
                        self.base_url,
                        self.timeout_seconds,
                        not self.local_only,
                    )
                    response = client.post(
                        f"{self.base_url}/embeddings",
                        json=payload,
                        headers=headers,
                    )
'''


def main() -> None:
    target = BACKEND / "app" / "services" / "embeddings" / "openai_compatible.py"
    patch(
        target,
        [
            (MODULE_HEAD, MODULE_HEAD_NEW),
            ("class OpenAICompatibleEmbeddingService:", HELPER + "class OpenAICompatibleEmbeddingService:"),
            (POST_OLD, POST_NEW),
        ],
    )


if __name__ == "__main__":
    sys.exit(main())

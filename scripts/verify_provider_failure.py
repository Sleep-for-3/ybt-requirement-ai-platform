#!/usr/bin/env python3
"""Assert that an unavailable configured real provider fails and never becomes Mock."""

import httpx


def main() -> None:
    base = "http://127.0.0.1:8000/api"
    with httpx.Client(timeout=15, trust_env=False) as client:
        login = client.post(
            f"{base}/auth/login",
            json={"username": "smoke_admin", "password": "smoke-only-platform-admin-password"},
        )
        login.raise_for_status()
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        status = client.get(f"{base}/ai-runtime/status", headers=headers)
        status.raise_for_status()
        if status.json()["llm"]["is_mock"]:
            raise AssertionError("Configured real provider was reported as Mock after connectivity loss")
        response = client.post(f"{base}/ai-runtime/test-chat", headers=headers, json={})
        if response.status_code != 503:
            raise AssertionError(f"Unavailable provider must return 503, got {response.status_code}: {response.text}")


if __name__ == "__main__":
    main()

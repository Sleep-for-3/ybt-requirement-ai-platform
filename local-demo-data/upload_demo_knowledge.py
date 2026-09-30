from pathlib import Path

import httpx


BASE_URL = "http://localhost:18000/api"
PROJECT_ID = 1
CREDENTIALS_PATH = Path(r"\\wsl.localhost\Ubuntu\home\lrw\.config\ybt-platform\admin-credentials.txt")
KNOWLEDGE_PATH = Path(__file__).with_name("demo_knowledge.txt")


def load_credentials() -> tuple[str, str]:
    values = {}
    for raw_line in CREDENTIALS_PATH.read_text(encoding="utf-8").splitlines():
        if "=" in raw_line:
            key, value = raw_line.split("=", 1)
            values[key.strip().lower()] = value.strip()
    username = values.get("username", "")
    password = values.get("password", "")
    if not username or not password:
        raise RuntimeError("Local demo credentials are incomplete")
    return username, password


username, password = load_credentials()
with httpx.Client(base_url=BASE_URL, trust_env=False, timeout=30) as client:
    login = client.post("/auth/login", json={"username": username, "password": password})
    login.raise_for_status()
    token = login.json()["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"

    documents = client.get(f"/projects/{PROJECT_ID}/knowledge/documents")
    documents.raise_for_status()
    document = next(
        (item for item in documents.json() if item.get("file_name") == KNOWLEDGE_PATH.name),
        None,
    )
    if document is None:
        with KNOWLEDGE_PATH.open("rb") as stream:
            uploaded = client.post(
                f"/projects/{PROJECT_ID}/knowledge/documents/upload",
                data={
                    "knowledge_type": "field_explanation",
                    "knowledge_scope": "project",
                    "confidentiality_level": "internal",
                    "change_note": "完全合成的本地 Mock 验收材料",
                },
                files={"file": (KNOWLEDGE_PATH.name, stream, "text/plain")},
            )
        uploaded.raise_for_status()
        document = uploaded.json()

print(
    {
        "document_id": document.get("id"),
        "file_name": document.get("file_name"),
        "document_status": document.get("document_status"),
        "knowledge_scope": document.get("knowledge_scope"),
        "confidentiality_level": document.get("confidentiality_level"),
    }
)

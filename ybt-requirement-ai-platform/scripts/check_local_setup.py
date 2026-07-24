#!/usr/bin/env python3
"""Secret-safe local environment preflight for Windows, Linux, and macOS."""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / "backend" / ".env"
FAILURES = 0


def report(level: str, name: str, message: str) -> None:
    global FAILURES
    if level == "FAIL":
        FAILURES += 1
    print(f"{level:<4} {name}: {message}")


def env_values() -> dict[str, str]:
    if not ENV_FILE.is_file():
        return {}
    values: dict[str, str] = {}
    for raw_line in ENV_FILE.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("\"'")
    return values


def command_available(name: str, args: list[str]) -> None:
    executable = shutil.which(name)
    if not executable:
        report("FAIL", name, "command is not available on PATH")
        return
    try:
        subprocess.run([executable, *args], capture_output=True, check=True, timeout=10, text=True)
    except (subprocess.SubprocessError, OSError):
        report("FAIL", name, "command is installed but unavailable")
    else:
        report("PASS", name, "available")


def check_port(port: int) -> None:
    with socket.socket() as sock:
        sock.settimeout(0.2)
        in_use = sock.connect_ex(("127.0.0.1", port)) == 0
    report("WARN" if in_use else "PASS", f"port {port}", "already in use" if in_use else "available")


def value(values: dict[str, str], key: str, default: str = "") -> str:
    return os.getenv(key, values.get(key, default)).strip()


def check_runtime(values: dict[str, str]) -> None:
    llm_provider = value(values, "LLM_PROVIDER", "mock").lower()
    llm_model = value(values, "LLM_MODEL")
    llm_env_name = value(values, "LLM_API_KEY_ENV_NAME", "OPENAI_API_KEY")
    local = llm_provider in {"local_vllm", "vllm", "local_ollama_compatible", "ollama"}
    report("PASS", "LLM provider", f"{llm_provider} selected")
    if llm_provider != "mock" and not llm_model:
        report("FAIL", "LLM model", "LLM_MODEL is required for a real or local provider")
    else:
        report("PASS", "LLM model", "configured or not required in Mock mode")
    if llm_provider not in {"mock"} and not local and not value(values, llm_env_name):
        report("FAIL", "LLM API key", f"{llm_env_name} is not set")
    else:
        report("PASS", "LLM API key", "present or not required")

    embedding_provider = value(values, "EMBEDDING_PROVIDER", "mock").lower()
    embedding_model = value(values, "EMBEDDING_MODEL")
    embedding_env_name = value(values, "EMBEDDING_API_KEY_ENV_NAME", "EMBEDDING_API_KEY")
    embedding_local = embedding_provider in {"local_vllm", "vllm", "local_ollama_compatible", "ollama"}
    report("PASS", "Embedding provider", f"{embedding_provider} selected")
    if embedding_provider != "mock" and not embedding_model:
        report("FAIL", "Embedding model", "EMBEDDING_MODEL is required")
    if embedding_provider != "mock" and not embedding_local and not value(values, embedding_env_name):
        report("FAIL", "Embedding API key", f"{embedding_env_name} is not set")
    else:
        report("PASS", "Embedding API key", "present or not required")


def check_application(values: dict[str, str]) -> None:
    for key in ("DATABASE_URL", "STORAGE_DIR", "AUTH_MODE", "CORS_ORIGINS"):
        if value(values, key):
            report("PASS", key, "configured")
        else:
            report("FAIL", key, "missing")
    storage_dir = value(values, "STORAGE_DIR")
    if storage_dir and not storage_dir.startswith("/app/"):
        path = Path(storage_dir)
        target = path if path.is_absolute() else ROOT / path
        report("PASS" if target.parent.exists() else "WARN", "storage directory", "parent directory is available" if target.parent.exists() else "parent directory will need to be created")


def check_git_safety() -> None:
    try:
        tracked = subprocess.run(
            ["git", "ls-files", "--", "backend/.env", "*.pem", "*.key"],
            cwd=ROOT,
            capture_output=True,
            check=True,
            text=True,
            timeout=10,
        ).stdout.strip()
    except (subprocess.SubprocessError, OSError):
        report("WARN", "Git secret check", "could not inspect tracked files")
        return
    report("FAIL" if tracked else "PASS", "Git secret check", "sensitive runtime file is tracked" if tracked else "no runtime .env or key file is tracked")


def main() -> int:
    command_available("docker", ["version"])
    command_available("docker", ["compose", "version"])
    if ENV_FILE.is_file():
        report("PASS", "backend/.env", "private runtime file exists")
    else:
        report("FAIL", "backend/.env", "missing; copy backend/.env.example manually, then review and edit it")
    for directory in (ROOT / "backend", ROOT / "frontend", ROOT / "scripts"):
        report("PASS" if directory.is_dir() else "FAIL", str(directory.relative_to(ROOT)), "directory exists" if directory.is_dir() else "directory is missing")
    check_port(3000)
    check_port(8000)
    values = env_values()
    check_runtime(values)
    check_application(values)
    check_git_safety()
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())

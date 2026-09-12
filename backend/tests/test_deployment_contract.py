"""Production Compose topology contract.

``docker-compose.yml`` is the only supported production topology (Linux +
Docker).  These assertions replace "someone reads the YAML carefully" with a
gate: a release must not quietly lose the migration gate, a healthcheck, or leak
a dependency port onto the host.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import yaml


ROOT = Path(__file__).resolve().parents[2]
COMPOSE_PATH = ROOT / "docker-compose.yml"
ENV_TEMPLATE_PATH = ROOT / ".env.production.example"

LONG_RUNNING_SERVICES = ("backend", "worker", "beat", "frontend")
MIGRATION_DEPENDENTS = ("backend", "worker", "beat")
INTERNAL_ONLY_SERVICES = ("postgres", "redis", "milvus")
REQUIRED_COMPOSE_VARIABLES = (
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "POSTGRES_DB",
    "APP_SECRET_KEY",
    "JWT_SECRET_KEY",
    "PRODUCTION_DATABASE_URL",
)
SECRET_NAME_TOKENS = ("KEY", "PASSWORD", "SECRET", "TOKEN")
# Suffixes that merely mention a credential (a variable *name*, a lifetime in
# minutes) instead of holding one.
NON_SECRET_SUFFIXES = ("_ENV_NAME", "_MINUTES", "_DAYS", "_COUNT", "_URL", "_URI")


@pytest.fixture(scope="module")
def compose_text() -> str:
    return COMPOSE_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def compose(compose_text: str) -> dict:
    return yaml.safe_load(compose_text)


def test_migration_gate_blocks_every_long_running_service(compose: dict) -> None:
    services = compose["services"]
    migrate = services["migrate"]

    assert str(migrate["restart"]) == "no", "the migration service must not restart on failure"
    command = " ".join(str(part) for part in migrate["command"])
    assert "alembic" in command and "upgrade" in command and "head" in command

    for name in MIGRATION_DEPENDENTS:
        depends_on = services[name]["depends_on"]
        assert depends_on["migrate"]["condition"] == "service_completed_successfully", (
            f"{name} must wait for the migration gate to complete"
        )


def test_every_long_running_service_has_a_healthcheck(compose: dict) -> None:
    for name in LONG_RUNNING_SERVICES:
        healthcheck = compose["services"][name].get("healthcheck")
        assert healthcheck, f"{name} has no healthcheck"
        assert healthcheck.get("test"), f"{name} healthcheck has no test command"
        for key in ("interval", "timeout", "retries"):
            assert healthcheck.get(key), f"{name} healthcheck is missing {key}"


def test_dependency_ports_are_never_published_on_the_host(compose: dict) -> None:
    for name in INTERNAL_ONLY_SERVICES:
        assert "ports" not in compose["services"][name], (
            f"{name} must stay on the internal network; use docker-compose.dev-ports.yml locally"
        )


def test_api_worker_beat_and_migrate_share_one_environment_contract(compose: dict) -> None:
    services = compose["services"]
    reference = services["backend"]["environment"]

    assert services["migrate"]["environment"] == reference
    for name in ("worker", "beat"):
        assert services[name]["environment"] == reference

    assert reference["AUTH_MODE"] == "required"
    assert reference["TASK_QUEUE_PROVIDER"] == "celery"
    assert str(reference["DATABASE_URL"]).startswith("${PRODUCTION_DATABASE_URL")


def test_services_read_the_private_env_file_not_the_public_template(
    compose: dict, compose_text: str
) -> None:
    assert ".env.production.example" not in compose_text, (
        "the checked-in template is documentation; services must read the private .env"
    )
    for name in ("migrate", "backend", "worker", "beat"):
        env_file = compose["services"][name]["env_file"]
        entries = [env_file] if isinstance(env_file, str) else list(env_file)
        assert "./.env" in entries, f"{name} must read the private root .env"


def test_required_variables_fail_fast_when_missing(compose_text: str) -> None:
    for name in REQUIRED_COMPOSE_VARIABLES:
        assert f"${{{name}:?" in compose_text, (
            f"{name} must use the ${{VAR:?message}} form so compose refuses to start without it"
        )


def test_env_template_covers_every_compose_variable(compose_text: str) -> None:
    referenced = set(re.findall(r"\$\{([A-Z_][A-Z0-9_]*)", compose_text))
    declared = _env_template_variables()
    assert referenced - declared == set(), (
        "these variables are used by docker-compose.yml but missing from .env.production.example: "
        f"{sorted(referenced - declared)}"
    )


def test_env_template_declares_the_production_contract() -> None:
    declared = _env_template_variables()
    for name in (
        "ENVIRONMENT",
        "AUTH_MODE",
        "TASK_QUEUE_PROVIDER",
        "CELERY_BROKER_URL",
        "CELERY_RESULT_BACKEND",
        "STORAGE_PROVIDER",
        "VECTOR_STORE_PROVIDER",
        "LLM_PROVIDER",
        "BACKEND_BIND_ADDRESS",
        "FRONTEND_BIND_ADDRESS",
    ):
        assert name in declared, f"{name} must be documented in .env.production.example"

    values = _env_template_values()
    assert values["ENVIRONMENT"] == "production"
    assert values["AUTH_MODE"] == "required"
    assert values["TASK_QUEUE_PROVIDER"] == "celery"


def test_env_template_contains_placeholders_not_real_secrets() -> None:
    for name, value in _env_template_values().items():
        if not _is_secret_name(name):
            continue
        assert value == "" or value.startswith("change-me"), (
            f"{name} must stay an obvious placeholder in the template"
        )


def _is_secret_name(name: str) -> bool:
    if name.endswith(NON_SECRET_SUFFIXES):
        return False
    return any(token in name for token in SECRET_NAME_TOKENS)


def test_backend_dockerignore_does_not_shadow_source_packages() -> None:
    """An unanchored ``storage/`` pattern silently emptied the production image.

    Docker matches a bare directory pattern against **every** path segment, so
    ``storage/`` also removed ``app/services/storage/`` and the API crashed on
    ``ModuleNotFoundError``.  Runtime directories therefore need a leading
    slash, and no ignore rule may collide with a real ``app/services`` package.
    """

    backend_root = ROOT / "backend"
    patterns = [
        line.strip()
        for line in (backend_root / ".dockerignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    packages = {
        path.name
        for path in (backend_root / "app" / "services").iterdir()
        if path.is_dir() and (path / "__init__.py").exists()
    }
    offenders = sorted(pattern for pattern in patterns if pattern.rstrip("/") in packages)
    assert offenders == [], f"这些 .dockerignore 规则会连源码包一起排除：{offenders}"
    assert "/storage/" in patterns


def _env_template_variables() -> set[str]:
    return {line.split("=", 1)[0].strip() for line in _env_template_lines() if "=" in line}


def _env_template_values() -> dict[str, str]:
    values: dict[str, str] = {}
    for line in _env_template_lines():
        if "=" in line:
            name, value = line.split("=", 1)
            values[name.strip()] = value.strip()
    return values


def _env_template_lines() -> list[str]:
    return [
        line.strip()
        for line in ENV_TEMPLATE_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]

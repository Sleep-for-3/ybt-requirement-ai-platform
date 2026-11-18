"""Read-only login dependency diagnosis; never print credentials or reset users."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import socket
import sys
from urllib.parse import urlsplit

from dotenv import dotenv_values
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url


def listening(host, port):
    try:
        with socket.create_connection((host, port), timeout=2):
            return True
    except OSError:
        return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    backend = Path(__file__).resolve().parents[1]
    config = dotenv_values(backend / ".env")
    frontend = dotenv_values(backend.parent / "frontend" / ".env.local")
    url = make_url(config["DATABASE_URL"])
    parsed = urlsplit(frontend.get("NEXT_PUBLIC_API_BASE_URL", "http://localhost:8000/api"))
    result = {"checked_at": datetime.now(timezone.utc).isoformat(), "mode": "read_only",
        "frontend_api": {"host": parsed.hostname, "port": parsed.port or 80,
                         "listening": listening(parsed.hostname, parsed.port or 80)},
        "database_config": {"dialect": url.get_backend_name(), "host": url.host,
                            "port": url.port or 5432}, "database_probes": []}
    if url.host not in {"127.0.0.1", "localhost"} or url.get_backend_name() != "postgresql":
        raise ValueError("This diagnostic only probes the existing local PostgreSQL configuration")
    for port in dict.fromkeys([url.port or 5432, 5433]):
        engine = create_engine(url.set(port=port), connect_args={"connect_timeout": 2})
        row = {"port": port, "tcp_listening": listening(url.host, port)}
        try:
            with engine.connect() as connection:
                row.update(database_query="passed", revision=connection.scalar(text("select version_num from alembic_version")))
        except Exception as error:
            row.update(database_query="failed", error_type=type(error).__name__)
        finally:
            engine.dispose()
        result["database_probes"].append(row)
    result["historical_incident_attribution"] = "unproven_without_original_request_trace"
    result["confirmed_current_findings"] = []
    if not result["frontend_api"]["listening"]:
        result["confirmed_current_findings"].append("configured_frontend_api_not_running")
    first = result["database_probes"][0]
    if first["database_query"] == "failed" and any(r["database_query"] == "passed" for r in result["database_probes"][1:]):
        result["confirmed_current_findings"].append("dotenv_database_port_differs_from_working_wsl_postgres_port")
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()

"""Create a fresh local Milvus/etcd/MinIO stack without touching shared data."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import time
from urllib.request import urlopen


PREFIX = "rag-p0-r45"
NETWORK = f"{PREFIX}-net"
PORT = 19531
IMAGES = {
    "etcd": "rancher/mirrored-coreos-etcd:v3.5.18",
    "minio": "minio/minio:RELEASE.2024-12-18T13-15-44Z",
    "milvus": "milvusdb/milvus:v2.5.4",
}
SHARED_MILVUS = "ybt-dev-milvus-1"


def ensure_absent(inventory: dict[str, set[str]]) -> None:
    collisions = {
        kind: sorted(names)
        for kind, names in inventory.items()
        if names
    }
    if collisions:
        raise ValueError(f"Existing isolated runtime resources: {collisions}")


def run(args: list[str], *, check: bool = True, timeout: int = 60) -> str:
    result = subprocess.run(
        args,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if check and result.returncode:
        raise RuntimeError(f"command_failed:{result.returncode}")
    return result.stdout.strip()


def digest_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def docker_resources(prefix: str = PREFIX) -> dict[str, set[str]]:
    containers = set(run(["docker", "ps", "-a", "--format", "{{.Names}}"]).splitlines())
    networks = set(run(["docker", "network", "ls", "--format", "{{.Name}}"]).splitlines())
    volumes = set(run(["docker", "volume", "ls", "--format", "{{.Name}}"]).splitlines())
    expected_containers = {
        f"{prefix}-etcd",
        f"{prefix}-minio",
        f"{prefix}-milvus",
    }
    expected_volumes = {
        f"{prefix}-etcd-data",
        f"{prefix}-minio-data",
        f"{prefix}-milvus-data",
    }
    return {
        "containers": containers & expected_containers,
        "networks": networks & {f"{prefix}-net"},
        "volumes": volumes & expected_volumes,
    }


def container_identity(name: str) -> tuple[str, str]:
    value = run([
        "docker", "inspect", "--format", "{{.Id}}|{{.State.StartedAt}}", name
    ])
    identity, started_at = value.split("|", 1)
    return identity, started_at


def write_report(path: Path, report: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError("Refusing to overwrite isolated runtime evidence")
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def wait_healthy(prefix: str, seconds: int = 240) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            result = subprocess.run(
                [
                    "docker", "exec", f"{prefix}-milvus",
                    "curl", "-fsS", "--max-time", "3",
                    "http://127.0.0.1:9091/healthz",
                ],
                check=False,
                capture_output=True,
                timeout=20,
            )
            if result.returncode == 0:
                return
        except subprocess.TimeoutExpired:
            pass
        time.sleep(2)
    raise TimeoutError("isolated_milvus_health_timeout")


def create_runtime(report_path: Path, *, prefix: str = PREFIX, port: int = PORT) -> dict:
    if report_path.exists():
        raise FileExistsError("Refusing to overwrite isolated runtime evidence")
    if not prefix.replace("-", "").isalnum() or not 1 <= port <= 65535:
        raise ValueError("Invalid isolated runtime prefix or port")
    network = f"{prefix}-net"
    report = {
        "runtime": prefix,
        "status": "preflight",
        "container_names": [f"{prefix}-{name}" for name in ("etcd", "minio", "milvus")],
        "network": network,
        "named_volumes": [f"{prefix}-{name}-data" for name in ("etcd", "minio", "milvus")],
        "milvus_host_binding": f"127.0.0.1:{port}->19530",
        "images": dict(IMAGES),
        "mutations_to_existing_resources": 0,
        "collections_created": 0,
        "provider_requests": 0,
        "secret_values_recorded": False,
    }
    try:
        present = docker_resources(prefix)
        resource_count = sum(map(len, present.values()))
        if resource_count not in (0, 7):
            raise ValueError("Partial isolated runtime exists; inspect and preserve it")
        resume_existing = resource_count == 7
        if not resume_existing and shutil.disk_usage(Path.home()).free < 5 * 1024**3:
            raise OSError("insufficient_free_disk")
        if not resume_existing:
            with socket.socket() as probe:
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
                probe.bind(("127.0.0.1", port))
        old_identity = container_identity(SHARED_MILVUS)
        image_ids = {
            service: run(["docker", "image", "inspect", "--format", "{{.Id}}", image])
            for service, image in IMAGES.items()
        }
        report["shared_milvus_identity_before"] = {
            "container_id": old_identity[0],
            "started_at": old_identity[1],
        }
        report["image_ids"] = image_ids
        if resume_existing:
            report["resumed_existing_isolated_runtime"] = True
        else:
            secret_home = Path.home() / ".local" / "share" / prefix
            secret_home.mkdir(parents=True, mode=0o700, exist_ok=False)
            os.chmod(secret_home, 0o700)
            secret_file = secret_home / "minio.env"
            username = "ragp0" + secrets.token_hex(8)
            password = secrets.token_urlsafe(36)
            env_content = (
                f"MINIO_ROOT_USER={username}\n"
                f"MINIO_ROOT_PASSWORD={password}\n"
                f"MINIO_ACCESS_KEY_ID={username}\n"
                f"MINIO_SECRET_ACCESS_KEY={password}\n"
            )
            secret_file.write_text(env_content, encoding="utf-8")
            os.chmod(secret_file, 0o600)
            del password, username, env_content

            run(["docker", "network", "create", "--driver", "bridge", network])
            for volume in report["named_volumes"]:
                run(["docker", "volume", "create", volume])

            run([
                "docker", "run", "-d", "--name", f"{prefix}-etcd",
                "--network", network, "--network-alias", "etcd",
                "--mount", f"type=volume,src={prefix}-etcd-data,dst=/etcd",
                "-e", "ETCD_AUTO_COMPACTION_MODE=revision",
                "-e", "ETCD_AUTO_COMPACTION_RETENTION=1000",
                IMAGES["etcd"],
                "etcd",
                "-advertise-client-urls=http://etcd:2379",
                "-listen-client-urls=http://0.0.0.0:2379",
                "--data-dir=/etcd",
            ])
            run([
                "docker", "run", "-d", "--name", f"{prefix}-minio",
                "--network", network, "--network-alias", "milvus-minio",
                "--mount", f"type=volume,src={prefix}-minio-data,dst=/minio_data",
                "--env-file", str(secret_file),
                IMAGES["minio"], "minio", "server", "/minio_data",
            ])
            run([
                "docker", "run", "-d", "--name", f"{prefix}-milvus",
                "--network", network,
                "--publish", f"127.0.0.1:{port}:19530",
                "--mount", f"type=volume,src={prefix}-milvus-data,dst=/var/lib/milvus",
                "--env-file", str(secret_file),
                "-e", "ETCD_ENDPOINTS=etcd:2379",
                "-e", "MINIO_ADDRESS=milvus-minio:9000",
                IMAGES["milvus"], "milvus", "run", "standalone",
            ])
        report["status"] = "starting"
        wait_healthy(prefix)
        new_shared_identity = container_identity(SHARED_MILVUS)
        if new_shared_identity != old_identity:
            raise RuntimeError("shared_milvus_identity_changed")
        report["shared_milvus_unchanged"] = True
        report["isolated_milvus_health"] = "healthy"
        report["status"] = "ready_for_read_only_verification"
    except Exception as error:
        report["status"] = "failed_inspect_without_cleanup"
        report["error_type"] = type(error).__name__
        report["error_code"] = str(error)[:120] if type(error) in (OSError, ValueError, TimeoutError) else "runtime_step_failed"
    write_report(report_path, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--prefix", default=PREFIX)
    parser.add_argument("--port", default=PORT, type=int)
    args = parser.parse_args()
    report = create_runtime(args.report.resolve(), prefix=args.prefix, port=args.port)
    print(json.dumps({
        "status": report["status"],
        "milvus_host_binding": report["milvus_host_binding"],
        "isolated_milvus_health": report.get("isolated_milvus_health", "not_verified"),
        "shared_milvus_unchanged": report.get("shared_milvus_unchanged", False),
        "provider_requests": 0,
    }))
    return 0 if report["status"] == "ready_for_read_only_verification" else 1


if __name__ == "__main__":
    raise SystemExit(main())

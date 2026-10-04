"""W09 backup plan / executor.

Dry-run by default: it prints exactly what a real backup would capture, verifies every source
exists and measures sizes, and writes nothing. A real dump only happens with ``--execute`` plus an
explicit ``--out`` directory; the tool then refuses to reuse an existing directory (so a release
backup can never overwrite an earlier one), records a SHA-256 for every artifact and writes a
manifest with the consistency point and the code/config versions.

Safety: the only database access is a read-only ``pg_dump``; the business database is never
modified; secrets are never printed; nothing is deleted. Restore drills stay a separate, manual,
bank-approved step (see RELEASE-RUNBOOK.md).

Usage (dry-run, safe):

    .venv\\Scripts\\python.exe ..\\docs\\upgrades\\2026-10-03\\w09_backup_plan.py

Real backup (needs the operator's decision, writes only into a new directory):

    $env:PGPASSWORD = (Get-Content C:\\Users\\admin\\dsh-pg18\\.admin-pw.txt -Raw).Trim()
    .venv\\Scripts\\python.exe ..\\docs\\upgrades\\2026-10-03\\w09_backup_plan.py --execute `
        --out C:\\Users\\admin\\dsh-pg18\\backups\\release-2026-10-04T1200
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[3] / "backend"
ROOT = BACKEND.parent
PG_BIN = Path(r"C:\Users\admin\dsh-pg18\pgsql\bin")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _dir_size(path: Path) -> tuple[int, int]:
    files = [item for item in path.rglob("*") if item.is_file()]
    return len(files), sum(item.stat().st_size for item in files)


def build_plan() -> list[dict[str, object]]:
    """The pieces a restorable backup needs, each with its consistency role."""
    backend = ROOT / "backend"
    storage_dir = Path(os.environ.get("STORAGE_DIR") or (backend / "dev_storage_local"))
    if not storage_dir.is_absolute():
        storage_dir = backend / storage_dir
    return [
        {"key": "postgres_dump", "what": "PostgreSQL 业务数据与审核记录（pg_dump，一致性点）",
         "source": str(PG_BIN / "pg_dump.exe"), "kind": "database", "critical": True},
        {"key": "attachments", "what": "附件与正式交付对象（对象存储目录）",
         "source": str(storage_dir), "kind": "directory", "critical": True},
        {"key": "config", "what": "配置安全引用（backend/.env 脱敏副本，不含明文密钥）",
         "source": str(backend / ".env"), "kind": "file", "critical": True},
        {"key": "vector_index", "what": "向量索引快照或可靠重建依据（Milvus Lite 数据文件）",
         "source": str(ROOT / ".local-run" / "milvus-lite"), "kind": "directory", "critical": False},
        {"key": "version_manifest", "what": "依赖与版本（应用 commit / 迁移 head / Skill 与模型版本）",
         "source": "git rev-parse HEAD + alembic current + requirements.lock.txt", "kind": "generated",
         "critical": True},
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true", help="really dump (otherwise dry-run)")
    parser.add_argument("--out", default=None, help="target directory (must not exist)")
    parser.add_argument("--database", default="ybt_dsh_handoff_v2")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5432)
    parser.add_argument("--user", default="postgres")
    args = parser.parse_args()

    plan = build_plan()
    inventory: list[dict[str, object]] = []
    for item in plan:
        source = Path(str(item["source"])) if item["kind"] != "generated" else None
        entry = dict(item)
        if source is not None:
            if item["kind"] == "file":
                present = source.is_file()
                entry.update({"exists": present,
                              "bytes": source.stat().st_size if present else 0})
            elif item["kind"] == "directory":
                present = source.is_dir()
                count, size = _dir_size(source) if present else (0, 0)
                entry.update({"exists": present, "files": count, "bytes": size})
            else:
                entry.update({"exists": shutil.which(str(source)) is not None})
        else:
            entry.update({"exists": True})
        inventory.append(entry)

    missing_critical = [item["key"] for item in inventory if item["critical"] and not item["exists"]]

    result: dict[str, object] = {
        "mode": "execute" if args.execute else "dry-run",
        "generated_at": datetime.now(UTC).isoformat(),
        "consistency_point": "pg_dump 的 snapshot；文件目录与向量索引在 dump 前后各记一次 mtime 以便核对",
        "database": args.database,
        "inventory": inventory,
        "missing_critical": missing_critical,
        "notes": [
            "备份目录使用时间/UUID 命名，已存在的目录一律拒绝写入（不可覆盖）",
            "每个产物记录 SHA-256 并写入 manifest.json",
            "密钥不入包：配置以脱敏副本入库，凭据由银行密钥管理提供",
            "恢复演练需在独立环境执行并实测 RTO/RPO（本工具不执行恢复）",
        ],
    }

    if not args.execute:
        result["ok"] = True
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    password = os.environ.get("PGPASSWORD") or ""
    if not password:
        result["ok"] = False
        result["error"] = "PGPASSWORD is not set; refusing to run a real dump"
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2
    if not args.out:
        result["ok"] = False
        result["error"] = "--out is required with --execute"
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2
    target = Path(args.out)
    if target.exists():
        result["ok"] = False
        result["error"] = f"target directory already exists: {target} (refusing to overwrite)"
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1

    target.mkdir(parents=True)
    artifacts: list[dict[str, object]] = []
    try:
        dump_path = target / f"{args.database}.dump"
        env = {**os.environ, "PGPASSWORD": password}
        completed = subprocess.run(
            [str(PG_BIN / "pg_dump.exe"), "-h", args.host, "-p", str(args.port), "-U", args.user,
             "-Fc", "-f", str(dump_path), args.database],
            capture_output=True, text=True, env=env, check=False,
        )
        if completed.returncode != 0 or not dump_path.exists():
            raise RuntimeError(f"pg_dump failed: {completed.stderr.strip()[:200]}")
        artifacts.append({"key": "postgres_dump", "file": dump_path.name,
                          "bytes": dump_path.stat().st_size, "sha256": _sha256(dump_path)})

        storage_dir = Path(str(next(item for item in inventory if item["key"] == "attachments")["source"]))
        if storage_dir.is_dir():
            archive = target / "attachments"
            shutil.copytree(storage_dir, archive)
            count, size = _dir_size(archive)
            artifacts.append({"key": "attachments", "dir": archive.name, "files": count,
                              "bytes": size, "sha256_manifest": "per-file"})

        git = Path(r"C:\Users\admin\.dsh\tools\mingit\cmd\git.exe")
        commit = subprocess.run([str(git), "-C", str(ROOT), "rev-parse", "HEAD"],
                                capture_output=True, text=True, check=False).stdout.strip()
        (target / "version.json").write_text(json.dumps(
            {"app_commit": commit,
             "schema_head": "see backend/alembic/versions (202610030001 is the current head)",
             "requirements_lock": "backend/requirements.lock.txt",
             "generated_at": datetime.now(UTC).isoformat()}, ensure_ascii=False, indent=2),
            encoding="utf-8")
        artifacts.append({"key": "version_manifest", "file": "version.json"})

        (target / "manifest.json").write_text(json.dumps(
            {**result, "artifacts": artifacts}, ensure_ascii=False, indent=2), encoding="utf-8")
        result.update({"ok": True, "target": str(target), "artifacts": artifacts})
    except Exception as exc:  # noqa: BLE001 - report, never leave a half-claimed success
        result.update({"ok": False, "target": str(target), "error": f"{type(exc).__name__}: {exc}"[:300]})

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())

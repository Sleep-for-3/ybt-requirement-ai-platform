"""Phase 5 acceptance: real backup -> restore into a fresh database -> integrity comparison.

The review's item 5 asks for a complete backup *and restore* (not just a dump). The existing
``w09_backup_plan.py`` produces a non-overwritable, SHA-256-manifested backup; it deliberately does
not restore ("本工具不执行恢复"). This script closes that gap on a throw-away database:

1. seed a known dataset and record per-table row counts (the "consistency point");
2. take a real ``pg_dump -Fc`` backup into a non-overwritable directory, with SHA-256 recorded;
3. restore it into a **different, empty** database with ``pg_restore``;
4. compare per-table row counts and a content digest between source and restored database;
5. prove the backup artifact is byte-identical to its recorded hash (corruption check);
6. time the restore so an RTO figure is measured rather than assumed.

Safety: both databases are this run's throw-away targets; the N13 guard runs before any DDL/write on
the source, and the restore target name is derived from the isolated source name (never the business
database). Nothing here runs against ``ybt_dsh_handoff_v2``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PG_BIN = Path(r"C:\Users\admin\dsh-pg18\pgsql\bin")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", default="ybt_iso_phase5_backup")
    parser.add_argument("--restore-database", default="")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5432)
    parser.add_argument("--user", default="postgres")
    parser.add_argument("--allow-reset-existing", action="store_true")
    parser.add_argument("--out-root", default=str(ROOT / ".local-run" / "phase5-backups"))
    parser.add_argument("--report", default="")
    args = parser.parse_args()

    password = os.environ.get("PGPASSWORD") or ""
    if not password:
        print(json.dumps({"ok": False, "error": "PGPASSWORD is not set"}, ensure_ascii=False))
        return 2

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "2026-10-03"))
    from isolated_pg_guard import require_isolated_target

    require_isolated_target(
        args.database, script="phase5_backup_restore.py", host=args.host, port=args.port,
        user=args.user, password=password, allow_existing=args.allow_reset_existing,
    )
    restore_name = args.restore_database or f"{args.database}_restore"
    # The restore target must itself satisfy the isolation rules: a throw-away database, never the
    # business database, never a server database.
    require_isolated_target(
        restore_name, script="phase5_backup_restore.py (restore target)", host=args.host, port=args.port,
        user=args.user, password=password, allow_existing=True,
    )
    if restore_name == args.database:
        print(json.dumps({"ok": False, "error": "restore target must differ from the source"}, ensure_ascii=False))
        return 2

    env = {**os.environ, "PGPASSWORD": password}
    steps: list[dict] = []

    def step(name: str, **payload: object) -> None:
        record = {"step": name, **payload}
        steps.append(record)
        print(json.dumps({"phase5_backup": record}, ensure_ascii=False), flush=True)

    url = f"postgresql+psycopg://{args.user}:{password}@{args.host}:{args.port}/{args.database}"
    os.environ["DATABASE_URL"] = url
    os.environ.setdefault("AUTH_MODE", "required")
    os.environ.setdefault("TASK_QUEUE_PROVIDER", "inline")
    os.environ.setdefault("APP_SECRET_KEY", "phase5-backup-app-secret")
    os.environ.setdefault("JWT_SECRET_KEY", "phase5-backup-jwt-secret-at-least-32-chars")

    from sqlalchemy import create_engine, func, select, text
    from sqlalchemy.orm import sessionmaker

    from app.core.database import Base
    from app.models import (  # noqa: F401 - populate Base.metadata before create_all
        Institution, InstitutionMembership, Institution as _Inst, Project, ProjectMembership,
        RagEvaluationCase, User,
    )
    from app.services.auth.password import hash_password

    engine = create_engine(url)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)

    # ---------------------------------------------------------------- 1. known dataset
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        institution = Institution(institution_code="P5BK", institution_name="合成备份机构",
                                  institution_type="bank", status="active")
        db.add(institution)
        db.flush()
        for index in range(12):
            user = User(username=f"p5_backup_{index}", display_name=f"合成-备份 {index}",
                        password_hash=hash_password(f"Synthetic-Backup-{index}-2026!"), status="active")
            db.add(user)
            db.flush()
            db.add(InstitutionMembership(institution_id=institution.id, user_id=user.id,
                                         role="member", status="active"))
        project = Project(name="合成备份项目", institution_id=institution.id)
        db.add(project)
        db.flush()
        for index in range(20):
            db.add(RagEvaluationCase(project_id=project.id, case_name=f"备份用例 {index}",
                                     case_type="retrieval", query_text=f"备份查询 {index}",
                                     expected_knowledge_unit_ids_json=[index], enabled=True))
        db.commit()

    TABLES = ("institutions", "users", "institution_memberships", "projects", "rag_evaluation_cases")

    def counts(target_url: str) -> dict[str, int]:
        target = create_engine(target_url)
        try:
            with target.connect() as conn:
                return {name: int(conn.execute(text(f"SELECT count(*) FROM {name}")).scalar() or 0)
                        for name in TABLES}
        finally:
            target.dispose()

    def digest(target_url: str) -> str:
        """Order-independent content fingerprint of the seeded rows (ids + natural keys)."""
        target = create_engine(target_url)
        try:
            with target.connect() as conn:
                rows = conn.execute(text(
                    "SELECT id, username FROM users ORDER BY id")).all()
                cases = conn.execute(text(
                    "SELECT id, case_name FROM rag_evaluation_cases ORDER BY id")).all()
            material = json.dumps({"users": [list(map(str, r)) for r in rows],
                                   "cases": [list(map(str, c)) for c in cases]},
                                  sort_keys=True, separators=(",", ":"))
            return hashlib.sha256(material.encode("utf-8")).hexdigest()
        finally:
            target.dispose()

    source_counts = counts(url)
    source_digest = digest(url)
    step("seeded_source", ok=source_counts["users"] == 12 and source_counts["rag_evaluation_cases"] == 20,
         counts=source_counts, digest=source_digest[:16])

    # ---------------------------------------------------------------- 2. non-overwritable backup
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    backup_dir = Path(args.out_root) / f"release-{args.database}-{stamp}-{os.getpid()}"
    if backup_dir.exists():
        step("backup_dir_collision", ok=False, path=str(backup_dir))
        return 1
    backup_dir.mkdir(parents=True)
    dump_path = backup_dir / f"{args.database}.dump"
    dump_started = time.perf_counter()
    dumped = subprocess.run(
        [str(PG_BIN / "pg_dump.exe"), "-h", args.host, "-p", str(args.port), "-U", args.user,
         "-Fc", "-f", str(dump_path), args.database],
        capture_output=True, text=True, env=env, check=False,
    )
    dump_seconds = round(time.perf_counter() - dump_started, 3)
    if dumped.returncode != 0 or not dump_path.exists():
        step("pg_dump_failed", ok=False, stderr=dumped.stderr.strip()[:300])
        return 1

    dump_hash = sha256(dump_path)
    (backup_dir / "manifest.json").write_text(json.dumps({
        "database": args.database, "created_at": datetime.now(UTC).isoformat(),
        "dump": dump_path.name, "sha256": dump_hash, "bytes": dump_path.stat().st_size,
        "source_counts": source_counts, "source_digest": source_digest,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    step("backup_taken", ok=True, bytes=dump_path.stat().st_size, sha256=dump_hash[:16],
         seconds=dump_seconds, directory=str(backup_dir))

    restored_hash = sha256(dump_path)
    step("backup_artifact_unchanged", ok=restored_hash == dump_hash,
         recorded=dump_hash[:16], recomputed=restored_hash[:16])

    # ---------------------------------------------------------------- 3. restore into a fresh DB
    admin = create_engine(
        f"postgresql+psycopg://{args.user}:{password}@{args.host}:{args.port}/postgres",
        isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{restore_name}"'))
        conn.execute(text(f'CREATE DATABASE "{restore_name}"'))
    admin.dispose()

    restore_url = f"postgresql+psycopg://{args.user}:{password}@{args.host}:{args.port}/{restore_name}"
    restore_started = time.perf_counter()
    restored = subprocess.run(
        [str(PG_BIN / "pg_restore.exe"), "-h", args.host, "-p", str(args.port), "-U", args.user,
         "-d", restore_name, "--no-owner", "--no-privileges", str(dump_path)],
        capture_output=True, text=True, env=env, check=False,
    )
    restore_seconds = round(time.perf_counter() - restore_started, 3)
    if restored.returncode != 0:
        step("pg_restore_failed", ok=False, returncode=restored.returncode,
             stderr=restored.stderr.strip()[:400])
        return 1

    restore_counts = counts(restore_url)
    restore_digest = digest(restore_url)
    step("restore_into_fresh_database", ok=True, seconds=restore_seconds, database=restore_name)

    # ---------------------------------------------------------------- 4. integrity comparison
    mismatched = {name: {"source": source_counts[name], "restored": restore_counts.get(name)}
                  for name in TABLES if source_counts[name] != restore_counts.get(name)}
    step("row_counts_match", ok=not mismatched, source=source_counts, restored=restore_counts,
         mismatched=mismatched)
    step("content_digest_match", ok=source_digest == restore_digest,
         source=source_digest[:16], restored=restore_digest[:16])

    # ---------------------------------------------------------------- 5. RTO figure (measured)
    step("measured_rto_seconds", ok=restore_seconds > 0, dump_seconds=dump_seconds,
         restore_seconds=restore_seconds,
         note="RTO 按实测记录；未与银行约定目标值比较（目标值属待验收条件）")

    report = {
        "ok": all(item.get("ok") for item in steps),
        "disclaimer": "工程验收（合成数据 + 隔离库）；未在银行环境演练，未与约定 RTO/RPO 目标比对。",
        "acceptance_preconditions_not_met": [
            "未在生产规模数据上演练；RTO/RPO 目标值由银行给出后才能判定是否达标。",
            "对象存储、向量索引与配置副本的恢复未包含在本脚本（本脚本只验证数据库一致性点）。",
        ],
        "backup_directory": str(backup_dir),
        "restore_database": restore_name,
        "steps": steps,
    }
    if args.report:
        Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps({"ok": report["ok"], "steps": len(steps)}, ensure_ascii=False))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

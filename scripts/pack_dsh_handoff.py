"""Package the live project tree, excluding credentials, caches, runtime data.

Old duplicate deployments/offline installers are excluded. This is not a
content-level secret audit and does not include Git object history.
Run --dry-run to inspect counts; --output chooses a new archive path.
"""
import argparse
import ast
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import zipfile


ROOT = Path(__file__).resolve().parents[1]
# Include the live project tree by default. Exclusions below name runtime data,
# duplicate distributions, generated files, and private configuration only.
SKIP_ROOT_DIRS = {
    ".git", ".claude", ".idea", ".gsd", ".local-run", ".demo_runtime",
    ".tmp-migration-probe", "handoff-packages", "codex-offline-bundle-20260908-091318",
    "appendonlydir",
    "deploy_package_20260904-124932", "项目部署包_20260904",
    "myservers-install", "ybt-requirement-ai-platform",
}
SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache", ".smoke-run",
             ".local-run", ".demo_runtime", "dev_storage_local", "smoke_storage"}
SKIP_RUNTIME_PATHS = {"backend/backend", "backend/storage", "backend/dev_storage_local", "backend/smoke_storage",
                      "backend/.smoke-run", "backend/.pytest-basetemp", "backend/uat_local_packs"}
SKIP_SUFFIXES = {".pyc", ".pyo", ".db", ".sqlite", ".sqlite3", ".rdb", ".pem",
                 ".key", ".pfx", ".p12", ".tsbuildinfo", ".zip", ".gz", ".7z",
                 ".tar", ".exe", ".msi", ".dll"}


def allowed(path):
    if path.is_symlink() or getattr(path, "is_junction", lambda: False)():
        return False
    relative = path.relative_to(ROOT)
    if relative.parts[0] in SKIP_ROOT_DIRS:
        return False
    if any(relative.as_posix() == prefix or relative.as_posix().startswith(prefix + "/")
           for prefix in SKIP_RUNTIME_PATHS):
        return False
    if any(part.lower() in SKIP_DIRS or part.lower().startswith((".next", ".pytest", ".mypy", ".ruff")) for part in relative.parts):
        return False
    if not path.resolve().is_relative_to(ROOT):
        return False
    name = path.name.lower()
    if name.startswith(".env") and name not in {".env.example", ".env.production.example"}:
        return False
    if name.endswith(".env"):
        return False
    if path.suffix.lower() in SKIP_SUFFIXES or any(mark in name for mark in (".db-", ".sqlite-", ".sqlite3-")):
        return False
    if name in {"celerybeat-schedule", "credentials.json", "auth.json", "id_rsa", "id_ed25519"}:
        return False
    if path.suffix.lower() == ".log" and not relative.as_posix().startswith(("docs/evaluation/", "docs/ux/acceptance/")):
        return False
    return True


def candidates():
    selected = set()
    for parent, children, names in os.walk(ROOT, followlinks=False):
        children[:] = [name for name in children if allowed(Path(parent) / name)]
        selected.update(Path(parent) / name for name in names)
    return sorted((path for path in selected if path.is_file() and allowed(path)), key=lambda p: p.relative_to(ROOT).as_posix())


def validate_source_closure(paths):
    """Catch a source package omitted by packaging rules before any archive is made."""
    selected = set(paths)
    missing_imports = set()
    checked = 0
    for path in paths:
        if path.suffix != ".py" or ROOT / "backend" / "app" not in path.parents:
            continue
        checked += 1
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (UnicodeError, SyntaxError) as exc:
            raise SystemExit(f"Cannot parse application module {path}: {exc}") from exc
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules = [item.name for item in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                modules = [node.module]
            else:
                continue
            for module in modules:
                if module is None or not (module == "app" or module.startswith("app.")):
                    continue
                target = ROOT / "backend" / module.replace(".", "/")
                if target.with_suffix(".py") not in selected and target / "__init__.py" not in selected:
                    missing_imports.add((str(path.relative_to(ROOT)), module))
    if missing_imports:
        raise SystemExit(f"Omitted internal Python imports: {sorted(missing_imports)[:20]}")
    return checked


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    paths = candidates()
    required = ("backend/app/main.py", "frontend/package-lock.json",
        "docs/handoff/DSH接手提示词-20260930.md",
        "backend/app/services/storage/__init__.py", "backend/app/services/storage/base.py",
        "backend/app/services/storage/factory.py", "backend/app/services/storage/local.py",
        "backend/app/services/storage/s3.py")
    missing = [name for name in required if ROOT / name not in paths]
    if missing:
        raise SystemExit(f"Missing required source files: {missing}")
    checked_importers = validate_source_closure(paths)
    try:
        tracked = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).split(b"\0")
        omitted_tracked = [item.decode("utf-8", "surrogateescape") for item in tracked if item and
                           (ROOT / item.decode("utf-8", "surrogateescape")).is_file() and
                           ROOT / item.decode("utf-8", "surrogateescape") not in paths]
    except (OSError, subprocess.CalledProcessError):
        omitted_tracked = None
    if omitted_tracked:
        raise SystemExit(f"Tracked files omitted from handoff: {omitted_tracked[:20]}")
    summary = {"files": len(paths), "source_bytes": sum(p.stat().st_size for p in paths),
               "internal_python_modules_checked": checked_importers,
               "tracked_files_omitted": len(omitted_tracked) if omitted_tracked is not None else None,
               "includes_untracked_source": True, "includes_git_history": False,
               "content_secret_audit": False}
    if args.dry_run:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return
    output = (args.output or ROOT / "handoff-packages" / f"ai-platform-dsh-{datetime.now():%Y%m%d-%H%M%S}.zip").resolve()
    if output.exists():
        raise SystemExit("Output already exists; choose a new archive name.")
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        head = None
    manifest = {**summary, "created_at": datetime.now().astimezone().isoformat(), "git_head": head,
                "note": "Working files include uncommitted changes. Rebuild dependencies; no runtime DB/config/history included. Review business content before uploading.", "entries": []}
    with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in paths:
            data = path.read_bytes()
            relative = path.relative_to(ROOT).as_posix()
            archive.writestr("ai-platform/" + relative, data)
            manifest["entries"].append({"path": relative, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
        archive.writestr("ai-platform/HANDOFF-MANIFEST.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    with zipfile.ZipFile(output) as archive:
        if archive.testzip() is not None:
            raise SystemExit("Archive verification failed; do not use this archive.")
    with output.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    print(json.dumps({"archive": str(output), "files": len(paths), "zip_bytes": output.stat().st_size,
                      "sha256": digest, "verified_crc": True}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

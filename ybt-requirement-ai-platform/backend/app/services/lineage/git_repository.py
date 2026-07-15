from __future__ import annotations

import os
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from app.services.lineage.archive_ingestion import ArchivedScript
from app.services.lineage.ingestion import ALLOWED_SCRIPT_EXTENSIONS, validate_script_path


@dataclass(frozen=True)
class GitRepositorySnapshot:
    commit_sha: str
    files: tuple[ArchivedScript, ...]


def read_git_repository_scripts(
    repository_url: str,
    *,
    branch: str = "main",
    max_repository_bytes: int = 500 * 1024 * 1024,
    max_file_count: int = 10000,
    max_file_bytes: int = 10 * 1024 * 1024,
) -> GitRepositorySnapshot:
    """Read Git objects from a bare clone without checking out or executing code."""

    if not repository_url or repository_url.startswith("-"):
        raise ValueError("Invalid repository URL")
    if not re.fullmatch(r"[A-Za-z0-9._/-]+", branch) or branch.startswith(('-', '/')) or ".." in branch:
        raise ValueError("Invalid Git branch")
    env = {
        "PATH": os.environ.get("PATH", ""),
        "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
    }
    with tempfile.TemporaryDirectory(prefix="ybt-lineage-git-") as root:
        bare = Path(root) / "repository.git"
        _git([
            "-c", "protocol.file.allow=always", "-c", f"core.hooksPath={os.devnull}",
            "clone", "--bare", "--no-local", "--depth", "1", "--branch", branch,
            "--", repository_url, str(bare),
        ], env=env)
        size = sum(item.stat().st_size for item in bare.rglob("*") if item.is_file())
        if size > max_repository_bytes:
            raise ValueError("Git repository exceeds the size limit")
        commit = _git(["--git-dir", str(bare), "rev-parse", "HEAD"], env=env).decode().strip()
        if not re.fullmatch(r"[0-9a-fA-F]{40,64}", commit):
            raise ValueError("Git repository returned an invalid commit")
        tree = _git(["--git-dir", str(bare), "ls-tree", "-r", "-z", "--long", commit], env=env)
        entries = [item for item in tree.split(b"\0") if item]
        if len(entries) > max_file_count:
            raise ValueError("Git repository contains too many files")
        files: list[ArchivedScript] = []
        for raw in entries:
            metadata, raw_path = raw.split(b"\t", 1)
            mode, object_type, _object_id, raw_size = metadata.decode("ascii").split(maxsplit=3)
            path_text = raw_path.decode("utf-8")
            if mode in {"120000", "160000"}:
                raise ValueError(f"Git symbolic links and submodules are not allowed: {path_text}")
            if object_type != "blob":
                continue
            try:
                safe_path = validate_script_path(path_text)
            except ValueError as exc:
                raise ValueError(f"Git entry has an unsafe path: {path_text}") from exc
            suffix = PurePosixPath(safe_path).suffix.lower()
            if suffix not in ALLOWED_SCRIPT_EXTENSIONS:
                continue
            file_size = int(raw_size)
            if file_size > max_file_bytes:
                raise ValueError(f"Git file exceeds the size limit: {path_text}")
            content = _git(["--git-dir", str(bare), "cat-file", "blob", f"{commit}:{safe_path}"], env=env)
            if len(content) != file_size:
                raise ValueError(f"Git object size mismatch: {path_text}")
            files.append(ArchivedScript(safe_path, PurePosixPath(safe_path).name, content))
        return GitRepositorySnapshot(commit, tuple(files))


def _git(arguments: list[str], *, env: dict[str, str]) -> bytes:
    try:
        completed = subprocess.run(
            ["git", *arguments], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, check=False, timeout=120, env=env,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        raise ValueError("Git is unavailable or the operation timed out") from exc
    if completed.returncode != 0:
        # Do not expose URLs, credentials or repository-controlled output.
        raise ValueError(f"Git operation failed with exit code {completed.returncode}")
    return completed.stdout

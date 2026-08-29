from io import BytesIO
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import zipfile

import pytest

from app.core.settings import Settings
from app.services.uat.packs import _read_zip


ROOT = Path(__file__).resolve().parents[2]
REPOSITORY_ROOT = ROOT


def test_uat_zip_file_count_limit_is_enforced_before_extraction() -> None:
    content = BytesIO()
    with zipfile.ZipFile(content, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("one.sql", "select 1")
        archive.writestr("two.sql", "select 2")
        archive.writestr("three.sql", "select 3")

    with pytest.raises(ValueError, match="too many files"):
        _read_zip(content.getvalue(), Settings(uat_zip_max_file_count=2))


def test_performance_baseline_declares_required_full_and_ci_scales() -> None:
    source = (ROOT / "scripts" / "performance_baseline.py").read_text(encoding="utf-8")

    for expected in (
        '"tables": 5',
        '"fields_per_table": 200',
        '"scenarios": 20',
        '"business_mappings": 2000',
        '"technical_mappings": 1000',
        '"double_layer_mappings": 1000',
        '"knowledge_units": 5000',
        '"lineage_edges": 5000',
        '"impacts": 500',
        'parser.add_argument("--small"',
    ):
        assert expected in source
    assert "build_project_readiness" in source
    assert "_render_formal_workbook" in source
    assert "InlineTaskQueue().enqueue" in source
    assert "peak_memory_bytes" in source


def test_smoke_enables_governance_workflow_explicitly() -> None:
    smoke_source = (ROOT / "scripts" / "smoke_test.py").read_text(encoding="utf-8")
    assert '"governance_workflow_enabled": True' in smoke_source


def test_windows_lifecycle_script_and_chinese_document_index_are_present() -> None:
    lifecycle_source = (ROOT / "scripts" / "项目启停.ps1").read_text(encoding="utf-8")
    for expected in (
        'ValidateSet("start", "stop", "restart", "status")',
        'ValidateSet("production", "sqlite")',
        "python.exe",
        "postgres.exe",
        "redis-server.exe",
        '"celery"',
        'TASK_QUEUE_PROVIDER = "celery"',
        "postgresql+psycopg://",
        "PGPASSFILE",
        "icacls.exe",
        '& icacls.exe $Path "/reset"',
        '& icacls.exe $Path "/inheritance:r" "/grant:r" "${identity}:(F)"',
        "$LASTEXITCODE -ne 0",
        "$acl.AreAccessRulesProtected",
        "$acl.Access.Count -ne 1",
        "backendStarterPid",
        "inspect-target",
        "alembic upgrade head",
        "Test-ManagedOwner",
        "health/ready",
        "Start-InteractiveConsole",
        "总体状态：完整运行",
        "操作菜单：",
        "退出窗口（不会停止已运行的项目）",
        "Show-RecentErrorLogs",
        ".local-run",
        "sqlite-migration-complete",
    ):
        assert expected in lifecycle_source
    assert "postgresql+psycopg://$DatabaseUser`:" not in lifecycle_source
    assert "postgresql+psycopg://postgres`:" not in lifecycle_source

    expected_documents = (
        "docs/说明文档索引.md",
        "docs/ai-runtime/本地启动.md",
        "docs/ai-runtime/模型调用流程.md",
        "docs/ai-runtime/模型供应商配置.md",
        "docs/ai-runtime/AI运行环境故障排查.md",
        "docs/deployment/部署架构.md",
        "docs/deployment/Docker编排部署.md",
        "docs/deployment/UAT验收指南.md",
    )
    assert all((ROOT / path).is_file() for path in expected_documents)
    assert not (ROOT / "docs" / "ai-runtime" / "local-start.md").exists()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows ACL behavior")
def test_windows_secret_acl_commands_remove_explicit_extra_access_and_are_idempotent(
    tmp_path: Path,
) -> None:
    secret_path = tmp_path / "secret.json"
    secret_path.write_text("{}", encoding="utf-8")

    def run_icacls(*arguments: str) -> None:
        result = subprocess.run(
            ["icacls.exe", str(secret_path), *arguments],
            check=False,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stdout + result.stderr

    run_icacls("/grant", "*S-1-1-0:(R)")
    for _ in range(2):
        run_icacls("/reset")
        identity = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-Command",
                "[System.Security.Principal.WindowsIdentity]::GetCurrent().Name",
            ],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        run_icacls("/inheritance:r", "/grant:r", f"{identity}:(F)")

    acl_result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-Command",
            (
                "[Console]::OutputEncoding=[Text.Encoding]::UTF8;"
                "$acl=Get-Acl -LiteralPath $env:YBT_ACL_TEST_PATH;"
                "[pscustomobject]@{"
                "Protected=$acl.AreAccessRulesProtected;"
                "Rules=@($acl.Access | ForEach-Object {"
                "[pscustomobject]@{"
                "Rights=$_.FileSystemRights.ToString();"
                "Type=$_.AccessControlType.ToString();"
                "Inherited=$_.IsInherited"
                "}})"
                "}|ConvertTo-Json -Depth 4 -Compress"
            ),
        ],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
            # PowerShell 7 prepends its module path in the parent process. Passing
            # that value into Windows PowerShell 5.1 prevents the Security module
            # (and therefore Get-Acl) from auto-loading on some hosts.
            env={
                **{key: value for key, value in os.environ.items() if key.upper() != "PSMODULEPATH"},
                "YBT_ACL_TEST_PATH": str(secret_path),
            },
    )
    acl = json.loads(acl_result.stdout)
    assert acl["Protected"] is True
    assert len(acl["Rules"]) == 1
    assert acl["Rules"][0] == {
        "Rights": "FullControl",
        "Type": "Allow",
        "Inherited": False,
    }


@pytest.mark.skipif(sys.platform != "win32", reason="Windows interactive launcher behavior")
def test_windows_lifecycle_script_without_action_keeps_control_console_open() -> None:
    process = subprocess.Popen(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(ROOT / "scripts" / "项目启停.ps1"),
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    try:
        time.sleep(4)
        assert process.poll() is None, "bare script invocation exited instead of waiting for a menu choice"
        assert process.stdin is not None
        process.stdin.write(b"0\r\n")
        process.stdin.flush()
        _, stderr = process.communicate(timeout=10)
        assert process.returncode == 0, stderr.decode(errors="replace")
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows lifecycle status behavior")
def test_windows_lifecycle_status_reports_semantic_runtime_and_docker_engine() -> None:
    result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(ROOT / "scripts" / "项目启停.ps1"),
            "status",
        ],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    assert "Docker 引擎：" in result.stdout
    assert "Milvus：" in result.stdout
    assert "Embedding：" in result.stdout


def test_windows_lifecycle_production_does_not_force_ai_runtime_back_to_mock() -> None:
    lifecycle_source = (ROOT / "scripts" / "项目启停.ps1").read_text(encoding="utf-8")

    assert '$env:LLM_PROVIDER = "mock"' not in lifecycle_source
    assert '$env:EMBEDDING_PROVIDER = "mock"' not in lifecycle_source
    assert '$env:VECTOR_STORE_PROVIDER = "mock"' not in lifecycle_source


def test_windows_lifecycle_manages_persistent_milvus_without_deleting_volumes() -> None:
    lifecycle_source = (ROOT / "scripts" / "项目启停.ps1").read_text(encoding="utf-8")

    for expected in (
        "Start-SemanticInfrastructure",
        "Stop-SemanticInfrastructure",
        '"--project-name", "ybt-requirement-ai-platform"',
        '"etcd", "milvus-minio", "milvus"',
        "semantic-compose.env",
        '$env:VECTOR_STORE_PROVIDER = "milvus"',
        '$env:MILVUS_URI = "http://127.0.0.1:19530"',
    ):
        assert expected in lifecycle_source
    for forbidden in ("docker compose down -v", "docker volume rm", "docker system prune"):
        assert forbidden not in lifecycle_source.lower()


def test_windows_lifecycle_provides_real_local_embedding_when_none_is_configured() -> None:
    lifecycle_source = (ROOT / "scripts" / "项目启停.ps1").read_text(encoding="utf-8")
    compose_source = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    requirements_source = (ROOT / "backend" / "requirements.txt").read_text(encoding="utf-8")

    for expected in (
        "Start-LocalEmbeddingInfrastructure",
        '$env:EMBEDDING_PROVIDER = "local_vllm"',
        '$env:EMBEDDING_BASE_URL = "http://127.0.0.1:11434/v1"',
        '$env:EMBEDDING_MODEL = "BAAI/bge-small-zh-v1.5"',
        '$env:EMBEDDING_DIMENSION = "512"',
        "app.local_embedding_server:app",
        "FASTEMBED_CACHE_PATH",
    ):
        assert expected in lifecycle_source
    assert "fastembed==0.8.0" in requirements_source
    assert "\n  ollama:" not in compose_source
    assert 'http://127.0.0.1:11434/v1/embeddings' in lifecycle_source
    assert "Embedding 向量生成自检失败" in lifecycle_source


def test_windows_lifecycle_uses_bounded_retry_for_transient_docker_pulls() -> None:
    lifecycle_source = (ROOT / "scripts" / "项目启停.ps1").read_text(encoding="utf-8")

    assert "Invoke-DockerCommandWithRetry" in lifecycle_source
    assert "[int]$Attempts = 5" in lifecycle_source
    assert "Docker 命令连续失败" in lifecycle_source


def test_windows_lifecycle_failed_start_cleans_verified_listener_children() -> None:
    lifecycle_source = (ROOT / "scripts" / "项目启停.ps1").read_text(encoding="utf-8")

    assert "Stop-FailedLaunchPortOwner" in lifecycle_source
    assert 'Stop-FailedLaunchPortOwner -Service "frontend"' in lifecycle_source
    assert 'Stop-FailedLaunchPortOwner -Service "backend"' in lifecycle_source
    assert "taskkill" not in lifecycle_source.lower()


def test_windows_lifecycle_keeps_wsl_docker_alive_for_running_services() -> None:
    lifecycle_source = (ROOT / "scripts" / "项目启停.ps1").read_text(encoding="utf-8")

    assert "Start-DockerKeepAlive" in lifecycle_source
    assert "Stop-DockerKeepAlive" in lifecycle_source
    assert '"sleep", "infinity"' in lifecycle_source
    assert "dockerKeepAlivePid" in lifecycle_source


def test_windows_lifecycle_migration_marker_allows_new_postgres_projects_safely() -> None:
    lifecycle_source = (ROOT / "scripts" / "项目启停.ps1").read_text(encoding="utf-8")

    assert "$targetProjectCount -ge $markerSourceProjectCount" in lifecycle_source
    assert "sourceProjectCount = $sourceProjectCount" in lifecycle_source
    assert "sourceLength" in lifecycle_source
    assert "sourceLastWriteTime" in lifecycle_source
    assert "SQLite 源文件已变化" in lifecycle_source


def test_windows_lifecycle_preserves_existing_postgres_as_authoritative() -> None:
    lifecycle_source = (ROOT / "scripts" / "项目启停.ps1").read_text(encoding="utf-8")

    assert "$targetProjectCount -gt 0 -or $protectedTables.Count -gt 0" in lifecycle_source
    assert "PostgreSQL 作为权威数据源" in lifecycle_source
    assert "跳过 SQLite 自动迁移" in lifecycle_source


def test_windows_lifecycle_recovers_only_verified_stale_postgres_pid() -> None:
    lifecycle_source = (ROOT / "scripts" / "项目启停.ps1").read_text(encoding="utf-8")

    assert "Move-StalePostgresPidFile" in lifecycle_source
    assert "Get-PortOwner -Port $PostgresPort" in lifecycle_source
    assert "PostgreSQL 陈旧 PID 文件已移至备份" in lifecycle_source


def test_windows_lifecycle_treats_missing_managed_process_as_already_stopped() -> None:
    lifecycle_source = (ROOT / "scripts" / "项目启停.ps1").read_text(encoding="utf-8")

    assert "$existingProcess = Get-Process -Id $candidate -ErrorAction SilentlyContinue" in lifecycle_source
    assert "$Name 已停止（PID $candidate 不存在）。" in lifecycle_source
    assert "记录的 PID 已不属于此项目，按已停止处理）。" in lifecycle_source
    assert "Test-ManagedOwner -ProcessId ([int]$state.workerPid) -Service \"worker\"" in lifecycle_source


def test_full_smoke_workflow_is_manual_scheduled_and_uploads_sanitized_evidence() -> None:
    workflow = (REPOSITORY_ROOT / ".github" / "workflows" / "smoke.yml").read_text(encoding="utf-8")

    for expected in (
        "workflow_dispatch:",
        "schedule:",
        "python -m pytest -q",
        "python -m alembic downgrade -1",
        "npm run build",
        "scripts/generate_demo_uat_pack.py",
        "scripts/smoke_test.py",
        "scripts/performance_baseline.py --small",
        "actions/upload-artifact@v4",
        "Verify artifact safety",
    ):
        assert expected in workflow
    assert "AUTH_MODE: required" in workflow
    assert "HEALTH_DETAILS_PUBLIC: \"false\"" in workflow

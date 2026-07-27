from io import BytesIO
from pathlib import Path
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
        "python.exe",
        "alembic upgrade head",
        "Test-ManagedOwner",
        "health/ready",
        ".local-run",
    ):
        assert expected in lifecycle_source

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

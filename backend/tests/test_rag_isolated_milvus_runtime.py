import pytest

from scripts.rag_isolated_milvus_runtime import create_runtime, ensure_absent


def test_isolated_runtime_preflight_rejects_existing_resources():
    with pytest.raises(ValueError, match="Existing isolated runtime resources"):
        ensure_absent({
            "containers": {"rag-p0-r45-milvus"},
            "networks": set(),
            "volumes": set(),
        })


def test_isolated_runtime_preflight_accepts_clean_namespace():
    ensure_absent({"containers": set(), "networks": set(), "volumes": set()})


def test_existing_evidence_path_is_rejected_before_any_docker_operation(tmp_path):
    evidence = tmp_path / "report.json"
    evidence.write_text("keep", encoding="utf-8")

    with pytest.raises(FileExistsError, match="Refusing to overwrite"):
        create_runtime(evidence)

    assert evidence.read_text(encoding="utf-8") == "keep"


def test_invalid_runtime_identity_is_rejected_before_any_docker_operation(tmp_path, monkeypatch):
    def fail_if_called(*args, **kwargs):
        raise AssertionError("Docker must not run for invalid runtime identity")

    monkeypatch.setattr("scripts.rag_isolated_milvus_runtime.docker_resources", fail_if_called)
    with pytest.raises(ValueError, match="Invalid isolated runtime prefix or port"):
        create_runtime(tmp_path / "report.json", prefix="round53/unsafe", port=65536)

import pytest

from app.models import AuditLog, Project
from app.services.embeddings.observability import embed_with_observability
from app.services.llm.base import ModelCallMetadata


class RecordingExternalEmbedding:
    local_only = False

    def __init__(self):
        self.called_with = None
        self.last_call = ModelCallMetadata(provider="openai_compatible", model="safe-test")

    def embed_texts(self, texts):
        self.called_with = texts
        return [[1.0, 0.0] for _ in texts]


def test_restricted_external_embedding_is_denied_and_audited_before_transmission(db_session):
    project = Project(name="安全策略")
    db_session.add(project)
    db_session.commit()
    service = RecordingExternalEmbedding()

    with pytest.raises(ValueError, match="restricted"):
        embed_with_observability(
            db_session,
            project.id,
            service,
            ["绝不能外发的模拟材料"],
            ["restricted"],
        )

    assert service.called_with is None
    audit = db_session.query(AuditLog).filter_by(
        project_id=project.id,
        action="external_embedding_data_denied",
    ).one()
    assert audit.result == "denied"
    assert "绝不能外发" not in str(audit.after_summary_json)


def test_external_embedding_receives_masked_content_and_logs_no_original_secret(db_session):
    project = Project(name="脱敏策略")
    db_session.add(project)
    db_session.commit()
    service = RecordingExternalEmbedding()
    raw = "联系电话 13800138000，password=plain-secret"

    vectors = embed_with_observability(
        db_session,
        project.id,
        service,
        [raw],
        ["internal"],
    )

    assert vectors == [[1.0, 0.0]]
    assert "13800138000" not in service.called_with[0]
    assert "plain-secret" not in service.called_with[0]

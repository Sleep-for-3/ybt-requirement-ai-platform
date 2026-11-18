"""Historical audit access must not silently present withdrawn text as current."""
import pytest
from fastapi import HTTPException

from app.services.auth.dependencies import Principal
from app.services.rag import document_preview_service as preview
from resources_data_fixtures import seed_resources


@pytest.mark.parametrize('status,expected', [
    ('withdrawn', '撤回'), ('superseded', '历史'),
    ('draft', '尚未生效'), ('pending_review', '尚未生效'), ('approved', '尚未生效'),
])
def test_explicit_authorized_audit_version_keeps_lifecycle_warning(db_session, status, expected):
    resources = seed_resources(db_session)
    doc = resources.documents['policy.pdf']
    principal = Principal(None, 'synthetic', None, True)
    _, version = preview.authorized_version(db_session, principal, resources.project.id, doc.id)
    version.lifecycle_status = status
    db_session.commit()
    selected_doc, selected = preview.authorized_version(
        db_session, principal, resources.project.id, doc.id, version.id)
    result = preview.preview_document(db_session, selected_doc, selected)
    assert result['lifecycle_status'] == status
    assert any(expected in warning for warning in result['warnings'])
    assert any('现行依据' in warning for warning in result['warnings'])


def test_active_preview_has_no_false_withdrawal_warning(db_session):
    resources = seed_resources(db_session)
    doc, version = preview.authorized_version(
        db_session, Principal(None, 'synthetic', None, True),
        resources.project.id, resources.documents['policy.pdf'].id)
    version.lifecycle_status = 'active'
    result = preview.preview_document(db_session, doc, version)
    assert result['lifecycle_status'] == 'active'
    assert not any('撤回' in warning or '尚未生效' in warning for warning in result['warnings'])


def test_unavailable_original_content_returns_sanitized_not_found(monkeypatch):
    class MissingStorage:
        def read(self, _storage_path):
            raise OSError("private storage path /srv/secret/source.pdf is unavailable")

    monkeypatch.setattr(preview, 'get_storage_service', lambda: MissingStorage())
    version = type("Version", (), {
        "storage_path": "/srv/secret/source.pdf",
        "file_name": "policy.pdf",
    })()

    with pytest.raises(HTTPException) as missing:
        preview.original_content(version)

    assert missing.value.status_code == 404
    assert "/srv/secret" not in str(missing.value.detail)

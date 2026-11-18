"""Prepare reversible governance probes only on the isolated synthetic document."""
import json
import subprocess
import sys

operation = sys.argv[1]
assert operation in {'viewer', 'missing', 'restore', 'withdraw', 'restore-withdraw'}
script = '''import json, os, secrets
from pathlib import Path
from sqlalchemy import select
from app.core.database import SessionLocal
from app.models import (KnowledgeDocument, KnowledgeDocumentVersion, Project,
    ProjectMembership, InstitutionMembership, User)
from app.services.auth.password import hash_password
operation = OPERATION
assert os.environ['APP_COMMIT'].endswith('d181c0a38083')
root = Path('/candidate-private')
with SessionLocal() as db:
    project = db.get(Project, 34)
    doc = db.get(KnowledgeDocument, 45)
    version = db.get(KnowledgeDocumentVersion, 45)
    assert project.name.startswith('Remote P0 synthetic lifecycle')
    assert doc.project_id == 34 and doc.file_name == 'lifecycle-policy.md'
    assert version.document_id == 45 and version.project_id == 34
    assert version.regulatory_version == 'LIFECYCLE-V1'
    if operation == 'viewer':
        path = root / 'viewer-account.private.json'
        assert not path.exists()
        account = {'username': 'rag_viewer_20261116_28', 'password': secrets.token_urlsafe(32)}
        assert db.scalar(select(User).where(User.username == account['username'])) is None
        user = User(username=account['username'], password_hash=hash_password(account['password']),
                    display_name='Read-only acceptance', status='active')
        db.add(user)
        db.flush()
        db.add(InstitutionMembership(user_id=user.id, institution_id=project.institution_id,
            role='member', status='active'))
        db.add(ProjectMembership(project_id=34, user_id=user.id, project_role='viewer', status='active'))
        db.add(ProjectMembership(project_id=35, user_id=user.id, project_role='viewer', status='active'))
        db.commit()
        path.write_text(json.dumps(account))
    elif operation in {'withdraw', 'restore-withdraw'}:
        path = root / 'withdrawn-version-28.private.json'
        if operation == 'withdraw':
            assert not path.exists()
            assert version.lifecycle_status == 'superseded'
            path.write_text(json.dumps({'version_id': version.id, 'lifecycle_status': version.lifecycle_status}))
            version.lifecycle_status = 'withdrawn'
        else:
            saved = json.loads(path.read_text())
            assert saved['version_id'] == version.id
            assert version.lifecycle_status == 'withdrawn'
            version.lifecycle_status = saved['lifecycle_status']
        db.commit()
    else:
        path = root / 'missing-original-28.private.json'
        if operation == 'missing':
            assert not path.exists()
            path.write_text(json.dumps({'version_id': version.id, 'original_storage_path': version.storage_path}))
            version.storage_path = 'rag-acceptance-missing-original-20261116-28'
        else:
            saved = json.loads(path.read_text())
            assert saved['version_id'] == version.id
            assert version.storage_path == 'rag-acceptance-missing-original-20261116-28'
            version.storage_path = saved['original_storage_path']
        db.commit()
print(json.dumps({'operation': operation, 'synthetic_project_id': 34,
    'model_calls': 0, 'storage_objects_deleted_or_modified': 0}))
'''.replace('OPERATION', repr(operation))
result = subprocess.run(['docker', 'exec', '-i', 'rag-candidate28-api', 'python', '-'],
    input=script.encode(), stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
if result.returncode:
    sys.stderr.buffer.write(result.stderr)
    raise SystemExit(result.returncode)
print(result.stdout.decode().strip())

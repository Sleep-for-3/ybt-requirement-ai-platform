"""Package source allowlists, excluding credentials, runtime state and data."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import tarfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from rag_review_environment import source_identity

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output', required=True, type=Path)
args = parser.parse_args()
root = Path(__file__).resolve().parents[2]
out = args.output.resolve()
out.mkdir(parents=True, exist_ok=False)
identity = source_identity()
names = []
for prefix in ('backend/app', 'backend/scripts', 'backend/alembic', 'frontend/app',
               'frontend/components', 'frontend/lib', 'frontend/hooks', 'frontend/public'):
    names.extend(p.relative_to(root).as_posix() for p in (root / prefix).rglob('*')
                 if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc')
names.extend(('backend/requirements.txt', 'backend/requirements.lock.txt', 'backend/alembic.ini',
              'backend/Dockerfile', 'frontend/package.json', 'frontend/package-lock.json',
              'frontend/next.config.mjs', 'frontend/next-env.d.ts', 'frontend/tsconfig.json',
              'frontend/postcss.config.js', 'frontend/tailwind.config.ts', 'frontend/.eslintrc.json',
              'frontend/Dockerfile'))
files = {}
for name in sorted(set(names)):
    path = root / name
    if path.is_symlink() or not path.is_file() or any(part.startswith('.env') for part in path.parts):
        raise ValueError('Unexpected release input: ' + name)
    files[name] = hashlib.sha256(path.read_bytes()).hexdigest()
if not all(files.get(name) == digest for name, digest in identity['code_files'].items()):
    raise ValueError('Release omitted frozen application source')
archive = out / 'source.tar.gz'
with tarfile.open(archive, 'x:gz') as target:
    for name in files:
        target.add(root / name, arcname=name, recursive=False)
manifest = {'source_hash': identity['code_hash'], 'git_head': identity['git_head'],
            'source_files': files, 'archive_sha256': hashlib.sha256(archive.read_bytes()).hexdigest(),
            'archive_bytes': archive.stat().st_size, 'credentials_included': False,
            'database_or_uploads_included': False}
(out / 'release-manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
print(json.dumps({key: manifest[key] for key in ('source_hash', 'archive_sha256', 'archive_bytes')}))

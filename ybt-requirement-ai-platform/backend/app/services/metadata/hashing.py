import hashlib
import json
from dataclasses import asdict, is_dataclass

def metadata_hash(value: object) -> str:
    payload = asdict(value) if is_dataclass(value) else value
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()

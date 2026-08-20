---
schema_version: 1
open_count: 1
waived_count: 0
fixed_count: 0
total_count: 1
last_updated: 2026-08-20T10:59:28.682Z
---

# Broken Windows Ledger

> Cross-phase defect register. With `workflow.windows_enforce` enabled, `/gsd-ship` blocks while `open_count > 0`.
> Waive with `gsd-tools windows waive <id> "<reason>"` (reason required).
> Mark fixed with `gsd-tools windows fixed <id>`.

| id | phase | kind | file | line | description | status | reason | recorded_at | resolved_at |
|----|-------|------|------|------|-------------|--------|--------|-------------|-------------|
| 1 | 09 | unrun-verify | backend/app/services/semantic/version_service.py |  | PostgreSQL row-lock concurrent confirmation staging qualification was not run; SQLite and portable-query tests passed | open |  | 2026-08-20T10:59:28.682Z |  |

````json
[
  {
    "id": 1,
    "kind": "unrun-verify",
    "phase": "09",
    "file": "backend/app/services/semantic/version_service.py",
    "line": null,
    "description": "PostgreSQL row-lock concurrent confirmation staging qualification was not run; SQLite and portable-query tests passed",
    "status": "open",
    "reason": "",
    "recorded_at": "2026-08-20T10:59:28.682Z",
    "resolved_at": null
  }
]
````

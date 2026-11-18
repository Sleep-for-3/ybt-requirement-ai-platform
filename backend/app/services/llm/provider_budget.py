"""Opt-in, cross-process provider-attempt accounting for bounded acceptance runs."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
import uuid

from app.services.llm.base import LLMProviderError


def _error(message, kind='budget_accounting_error'):
    return LLMProviderError(message, error_type=kind)


def reservation_tokens(payload: dict) -> int:
    # Text-only compatible APIs: UTF-8 bytes conservatively bound text tokens;
    # reserve additional framing overhead plus the full requested output cap.
    if 'messages' in payload:
        messages = payload['messages']
        if not isinstance(messages, list) or not all(
                isinstance(m, dict) and isinstance(m.get('content'), str) for m in messages):
            raise _error('Budget guard accepts text-only messages')
        output = payload.get('max_tokens')
        if type(output) is not int or output < 1:
            raise _error('A positive explicit output token cap is required')
    elif isinstance(payload.get('input'), list) and all(isinstance(v, str) for v in payload['input']):
        output = 0
    else:
        raise _error('Unsupported budgeted provider payload')
    return len(json.dumps(payload, ensure_ascii=False).encode('utf-8')) + 4096 + output


class ProviderBudget:
    def __init__(self, summary: str | Path, state: str | Path):
        self.summary = Path(summary).resolve()
        self.state = Path(state).resolve()

    @classmethod
    def from_environment(cls):
        summary = os.environ.get('RAG_MODEL_BUDGET_PATH', '')
        state = os.environ.get('RAG_MODEL_BUDGET_STATE', '')
        if not summary and not state:
            required = os.environ.get('RAG_MODEL_BUDGET_REQUIRED', '').strip().lower()
            if required in {'1', 'true', 'yes', 'on'}:
                raise _error('Provider budget is required but no budget paths are configured')
            return None
        if not summary or not state:
            raise _error('Both budget summary and durable state paths are required')
        return cls(summary, state)

    @contextmanager
    def _transaction(self):
        db = None
        try:
            # Never create a fresh accounting location implicitly after a typo.
            if not self.state.parent.is_dir():
                raise _error('Budget state parent must already exist')
            db = sqlite3.connect(self.state, timeout=15, isolation_level=None)
            db.execute('PRAGMA synchronous=FULL')
            db.execute('CREATE TABLE IF NOT EXISTS limits (scope TEXT, requests INTEGER, tokens INTEGER)')
            db.execute('CREATE TABLE IF NOT EXISTS attempts (id TEXT PRIMARY KEY, model TEXT, '
                       'reserved INTEGER, charged INTEGER, unknown INTEGER, created_at TEXT, finished_at TEXT)')
            db.execute('BEGIN IMMEDIATE')
            summary = json.loads(self.summary.read_text(encoding='utf-8-sig'))
            request_cap = summary['max_new_provider_requests']
            token_cap = summary['max_new_total_tokens']
            scope = summary['scope']
            if (type(request_cap) is not int or type(token_cap) is not int
                    or min(request_cap, token_cap) < 0 or not isinstance(scope, str) or not scope):
                raise _error('Invalid budget authorization')
            stored = db.execute('SELECT scope, requests, tokens FROM limits').fetchone()
            if stored is None:
                if any(summary.get(key, 0) != 0 for key in ('provider_requests_used',
                        'provider_requests_reserved', 'total_tokens_used', 'total_tokens_reserved',
                        'unknown_usage_requests')):
                    raise _error('Nonzero summary has no corresponding durable budget state')
                db.execute('INSERT INTO limits VALUES (?, ?, ?)', (scope, request_cap, token_cap))
            elif stored != (scope, request_cap, token_cap):
                raise _error('Budget authorization differs from durable state')
            yield db, summary
            # Keep the writer lock through export: concurrent processes must
            # never publish stale counters. A crash here cannot dispatch HTTP;
            # the next transaction rebuilds counters from the durable journal.
            self._export(db, summary)
            db.commit()
        except LLMProviderError:
            raise
        except (OSError, ValueError, KeyError, TypeError, sqlite3.Error) as exc:
            raise _error(f'Budget accounting unavailable: {type(exc).__name__}') from exc
        finally:
            if db is not None:
                if db.in_transaction:
                    db.rollback()
                db.close()

    @staticmethod
    def _totals(db):
        return db.execute('SELECT COUNT(*), COALESCE(SUM(COALESCE(charged, reserved)), 0), '
                          'COALESCE(SUM(charged > reserved), 0) FROM attempts').fetchone()

    def _export(self, db, summary):
        used, pending, tokens, reserved, unknown = db.execute(
            'SELECT COUNT(charged), COUNT(*)-COUNT(charged), COALESCE(SUM(charged),0), '
            'COALESCE(SUM(CASE WHEN charged IS NULL THEN reserved ELSE 0 END),0), '
            'COALESCE(SUM(unknown),0) FROM attempts').fetchone()
        summary.update(provider_requests_used=used, provider_requests_reserved=pending,
                       total_tokens_used=tokens, total_tokens_reserved=reserved,
                       unknown_usage_requests=unknown, updated_at=datetime.now(timezone.utc).isoformat())
        temporary = self.summary.with_name(self.summary.name + '.' + uuid.uuid4().hex + '.tmp')
        try:
            with temporary.open('w', encoding='utf-8', newline='\n') as handle:
                json.dump(summary, handle, ensure_ascii=False, indent=2)
                handle.write('\n')
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.summary)
        finally:
            temporary.unlink(missing_ok=True)

    def reserve(self, tokens: int, model: str) -> str:
        if type(tokens) is not int or tokens < 1:
            raise _error('Invalid token reservation')
        with self._transaction() as (db, summary):
            count, total, overrun = self._totals(db)
            if overrun:
                raise _error('Provider usage exceeded a reservation; manual reconciliation required')
            if count >= summary['max_new_provider_requests'] or total + tokens > summary['max_new_total_tokens']:
                raise _error('Cumulative real-model budget exhausted', 'budget_exhausted')
            identity = uuid.uuid4().hex
            db.execute('INSERT INTO attempts VALUES (?, ?, ?, NULL, NULL, ?, NULL)',
                (identity, model, tokens, datetime.now(timezone.utc).isoformat()))
        return identity

    def finish(self, identity: str, usage: dict | None):
        with self._transaction() as (db, _summary):
            row = db.execute('SELECT reserved, charged FROM attempts WHERE id=?', (identity,)).fetchone()
            if row is None or row[1] is not None:
                raise _error('Unknown or already settled provider attempt')
            total = usage.get('total_tokens') if isinstance(usage, dict) else None
            valid = type(total) is int and total > 0
            if valid:
                parts = [usage.get(key, 0) for key in ('prompt_tokens', 'completion_tokens')]
                valid = all(type(n) is int and n >= 0 for n in parts) and sum(parts) <= total
            charged = total if valid else row[0]
            db.execute('UPDATE attempts SET charged=?, unknown=?, finished_at=? WHERE id=?',
                (charged, int(not valid), datetime.now(timezone.utc).isoformat(), identity))

    def refresh(self):
        with self._transaction():
            pass

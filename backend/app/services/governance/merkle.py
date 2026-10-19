"""Merkle inclusion proofs over hashed audit entries (④).

Leaf and internal hashes use distinct domain prefixes so that an internal node
can never be replayed as a leaf.  The tree layout follows RFC 6962: an odd
level promotes its lone node instead of duplicating it, which avoids the
duplicate-leaf ambiguity behind CVE-2012-2459.

Everything here is pure :mod:`hashlib`.  No third-party Merkle library is
imported: the common Python candidate is GPL-licensed, which this repository
does not accept.
"""

from __future__ import annotations

import hashlib
import hmac
from typing import Any, Mapping, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AuditLog
from app.services.governance.audit import audit_chain_scope

DEFAULT_BLOCK_SIZE = 1024
_LEAF_PREFIX = b"\x00"
_NODE_PREFIX = b"\x01"
_HEX_DIGITS = frozenset("0123456789abcdef")


def leaf_hash(entry_hash: str) -> str:
    """Domain-separated leaf hash of one audit entry hash."""

    normalized = entry_hash.strip().lower()
    if len(normalized) != 64 or not set(normalized) <= _HEX_DIGITS:
        raise ValueError("entry hash must be 64 hexadecimal characters")
    return hashlib.sha256(_LEAF_PREFIX + normalized.encode("ascii")).hexdigest()


def node_hash(left: str, right: str) -> str:
    """Domain-separated internal node hash."""

    return hashlib.sha256(_NODE_PREFIX + bytes.fromhex(left) + bytes.fromhex(right)).hexdigest()


def _split(size: int) -> int:
    """Largest power of two strictly smaller than ``size`` (RFC 6962)."""

    split = 1
    while split * 2 < size:
        split *= 2
    return split


def _tree_hash(leaves: Sequence[str]) -> str:
    if len(leaves) == 1:
        return leaves[0]
    split = _split(len(leaves))
    return node_hash(_tree_hash(leaves[:split]), _tree_hash(leaves[split:]))


def merkle_root(entry_hashes: Sequence[str]) -> str | None:
    """Root over an ordered batch of audit entry hashes.

    The batch order is part of the commitment: the same entries in a different
    order produce a different root.  An empty batch has no root (``None``).
    """

    if not entry_hashes:
        return None
    return _tree_hash([leaf_hash(item) for item in entry_hashes])


def merkle_proof(entry_hashes: Sequence[str], index: int) -> list[dict[str, str]]:
    """Inclusion proof for ``index`` within ``entry_hashes``, bottom-up."""

    if not entry_hashes:
        raise ValueError("cannot build a proof for an empty batch")
    if index < 0 or index >= len(entry_hashes):
        raise IndexError(f"leaf index {index} is outside the batch of {len(entry_hashes)} entries")
    return _proof([leaf_hash(item) for item in entry_hashes], index)


def _proof(leaves: Sequence[str], index: int) -> list[dict[str, str]]:
    if len(leaves) == 1:
        return []
    split = _split(len(leaves))
    if index < split:
        return _proof(leaves[:split], index) + [{"side": "right", "hash": _tree_hash(leaves[split:])}]
    return _proof(leaves[split:], index - split) + [{"side": "left", "hash": _tree_hash(leaves[:split])}]


def verify_merkle_proof(entry_hash: str, proof: Sequence[Any], root: str | None) -> bool:
    """Replay one proof.  Only the leaf, the proof and the root are needed."""

    if not root:
        return False
    try:
        current = leaf_hash(entry_hash)
    except (AttributeError, ValueError):
        return False
    for step in proof:
        try:
            side = step["side"]
            sibling = step["hash"]
        except (TypeError, KeyError, IndexError):
            return False
        if side == "left":
            current = node_hash(sibling, current)
        elif side == "right":
            current = node_hash(current, sibling)
        else:
            return False
    return hmac.compare_digest(current, root)


def _load_chain_window(db: Session, target: AuditLog, block_size: int) -> list[tuple[int, str]]:
    """Newest ``block_size`` hashed entries of ``target``'s chain, oldest first."""

    statement = select(AuditLog.id, AuditLog.entry_hash).where(
        AuditLog.entry_hash.is_not(None), AuditLog.id <= target.id
    )
    if target.institution_id is None:
        statement = statement.where(AuditLog.institution_id.is_(None))
    else:
        statement = statement.where(AuditLog.institution_id == target.institution_id)
    statement = statement.order_by(AuditLog.id.desc()).limit(block_size)
    window = [(int(row[0]), str(row[1])) for row in db.execute(statement)]
    window.reverse()
    return window


def audit_merkle_root(db: Session, audit_log_ids: Sequence[int]) -> dict[str, Any]:
    """Root over an explicit batch of audit log ids."""

    ids = [int(item) for item in audit_log_ids]
    if not ids:
        return {"root": None, "leaf_count": 0, "ids": [], "entry_hashes": []}
    statement = select(AuditLog.id, AuditLog.entry_hash).where(AuditLog.id.in_(ids))
    found = {int(row[0]): row[1] for row in db.execute(statement)}
    missing = [item for item in ids if item not in found]
    if missing:
        raise LookupError(f"audit entries not found: {sorted(missing)}")
    unhashed = [item for item in ids if not found[item]]
    if unhashed:
        raise ValueError(f"audit entries have no hash recorded: {sorted(unhashed)}")
    ordered = sorted(found.items())
    entry_hashes = [str(value) for _, value in ordered]
    return {
        "root": merkle_root(entry_hashes),
        "leaf_count": len(ordered),
        "ids": [key for key, _ in ordered],
        "entry_hashes": entry_hashes,
    }


def audit_merkle_proof(db: Session, audit_log_id: int, *, block_size: int = DEFAULT_BLOCK_SIZE) -> dict[str, Any]:
    """Self-contained inclusion proof for one audit entry.

    The committed block is the newest ``block_size`` hashed entries of the
    entry's own institution chain (including the entry itself), so a proof
    stays verifiable without replaying the whole chain.
    """

    if block_size < 1:
        raise ValueError("block_size must be at least 1")
    target = db.get(AuditLog, int(audit_log_id))
    if target is None:
        raise LookupError(f"audit entry {audit_log_id} not found")
    if not target.entry_hash:
        raise ValueError(f"audit entry {audit_log_id} has no hash recorded")
    window = _load_chain_window(db, target, block_size)
    ids = [key for key, _ in window]
    entry_hashes = [value for _, value in window]
    index = ids.index(int(target.id))
    return {
        "audit_log_id": int(target.id),
        "institution_id": target.institution_id,
        "chain_scope": audit_chain_scope(target.institution_id),
        "leaf": target.entry_hash,
        "root": merkle_root(entry_hashes),
        "index": index,
        "tree_size": len(entry_hashes),
        "block_size": block_size,
        "proof": merkle_proof(entry_hashes, index),
    }


def verify_audit_merkle_proof(bundle: Mapping[str, Any]) -> bool:
    """Verify a bundle produced by :func:`audit_merkle_proof`."""

    try:
        return verify_merkle_proof(bundle["leaf"], bundle["proof"], bundle["root"])
    except (KeyError, TypeError):
        return False

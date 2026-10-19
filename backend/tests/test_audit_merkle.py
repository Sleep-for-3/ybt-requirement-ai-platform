"""④ Merkle root and inclusion proofs, pure hashlib."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app.services.governance import (
    merkle_proof,
    merkle_root,
    record_audit,
    verify_merkle_proof,
)
from app.services.governance.merkle import (
    audit_merkle_proof,
    audit_merkle_root,
    leaf_hash,
    verify_audit_merkle_proof,
)

HEXES = [f"{index:064x}" for index in range(1, 12)]


def test_empty_batch_has_no_root() -> None:
    assert merkle_root([]) is None
    with pytest.raises(ValueError):
        merkle_proof([], 0)


def test_single_leaf_root_is_the_leaf_hash() -> None:
    assert merkle_root([HEXES[0]]) == leaf_hash(HEXES[0])


def test_root_is_stable_and_order_sensitive() -> None:
    assert merkle_root(HEXES) == merkle_root(list(HEXES))
    assert merkle_root(HEXES) != merkle_root(list(reversed(HEXES)))


@pytest.mark.parametrize("size", [1, 2, 3, 4, 5, 7, 8, 11])
def test_every_position_verifies(size: int) -> None:
    batch = HEXES[:size]
    root = merkle_root(batch)
    for index in range(size):
        proof = merkle_proof(batch, index)
        assert verify_merkle_proof(batch[index], proof, root) is True
        # proof length is logarithmic, not linear
        assert len(proof) <= max(1, size.bit_length())


def test_a_foreign_leaf_is_rejected() -> None:
    batch = HEXES[:5]
    root = merkle_root(batch)
    proof = merkle_proof(batch, 2)
    assert verify_merkle_proof("f" * 64, proof, root) is False


def test_a_tampered_proof_step_is_rejected() -> None:
    batch = HEXES[:5]
    root = merkle_root(batch)
    proof = merkle_proof(batch, 2)
    tampered = [dict(step) for step in proof]
    tampered[0]["hash"] = "0" * 64
    assert verify_merkle_proof(batch[2], tampered, root) is False

    flipped = [dict(step) for step in proof]
    flipped[0]["side"] = "right" if flipped[0]["side"] == "left" else "left"
    assert verify_merkle_proof(batch[2], flipped, root) is False


def test_proof_against_the_wrong_root_is_rejected() -> None:
    batch = HEXES[:4]
    proof = merkle_proof(batch, 1)
    assert verify_merkle_proof(batch[1], proof, merkle_root(HEXES[:3])) is False


def test_malformed_inputs_are_rejected_without_raising() -> None:
    batch = HEXES[:3]
    root = merkle_root(batch)
    proof = merkle_proof(batch, 0)
    assert verify_merkle_proof("not-a-hash", proof, root) is False
    assert verify_merkle_proof(batch[0], proof, None) is False
    assert verify_merkle_proof(batch[0], [{"side": "middle", "hash": "0" * 64}], root) is False
    assert verify_merkle_proof(batch[0], [{"hash": "0" * 64}], root) is False
    with pytest.raises(ValueError):
        merkle_root(["zz"])
    with pytest.raises(IndexError):
        merkle_proof(batch, 3)


def test_leaves_and_nodes_are_domain_separated() -> None:
    """An internal node can never be replayed as a leaf."""

    batch = HEXES[:2]
    internal = merkle_root(batch)
    # The node digest is not itself a leaf digest, so an internal node cannot be
    # presented as the committed leaf.
    assert leaf_hash(internal) != internal
    assert verify_merkle_proof(internal, [], leaf_hash(internal)) is True
    assert verify_merkle_proof(internal, [], internal) is False


def _hashed_entries(db: Session, count: int, institution_id: int = 1) -> list[int]:
    rows = [
        record_audit(
            db,
            action=f"merkle_{index}",
            resource_type="document",
            institution_id=institution_id,
            after={"index": index},
        )
        for index in range(count)
    ]
    db.commit()
    return [row.id for row in rows]


def test_audit_root_over_an_explicit_batch(db_session: Session) -> None:
    ids = _hashed_entries(db_session, 5)
    bundle = audit_merkle_root(db_session, ids)

    assert bundle["leaf_count"] == 5
    assert bundle["ids"] == sorted(ids)
    assert bundle["root"] == merkle_root(bundle["entry_hashes"])
    assert audit_merkle_root(db_session, [])["root"] is None


def test_audit_bundle_verifies_and_detects_edits(db_session: Session) -> None:
    ids = _hashed_entries(db_session, 4)
    bundle = audit_merkle_proof(db_session, ids[2])

    assert bundle["audit_log_id"] == ids[2]
    # The committed block is the target's own prefix (all same-chain entries up
    # to and including it), so the proof stays reproducible as the chain grows.
    assert bundle["tree_size"] == 3
    assert bundle["index"] == 2
    assert verify_audit_merkle_proof(bundle) is True
    assert verify_audit_merkle_proof(audit_merkle_proof(db_session, ids[-1])) is True

    tampered = dict(bundle)
    tampered["leaf"] = "0" * 64
    assert verify_audit_merkle_proof(tampered) is False

    other = dict(bundle)
    other["root"] = merkle_root(["a" * 64, "b" * 64])
    assert verify_audit_merkle_proof(other) is False

    assert verify_audit_merkle_proof({}) is False


def test_proof_is_bounded_by_the_block_size(db_session: Session) -> None:
    ids = _hashed_entries(db_session, 6)
    bundle = audit_merkle_proof(db_session, ids[-1], block_size=3)

    assert bundle["tree_size"] == 3
    assert bundle["index"] == 2
    assert verify_audit_merkle_proof(bundle) is True


def test_unhashed_entries_cannot_be_committed(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.settings import get_settings

    monkeypatch.setenv("AUDIT_CHAIN_ENABLED", "false")
    get_settings.cache_clear()
    try:
        log = record_audit(db_session, action="disabled", resource_type="document", institution_id=1)
        db_session.commit()
    finally:
        # Drop the override before clearing the cache, so a disabled Settings
        # object cannot leak into later tests through the lru_cache.
        monkeypatch.delenv("AUDIT_CHAIN_ENABLED", raising=False)
        get_settings.cache_clear()

    with pytest.raises(ValueError):
        audit_merkle_root(db_session, [log.id])
    with pytest.raises(ValueError):
        audit_merkle_proof(db_session, log.id)
    with pytest.raises(LookupError):
        audit_merkle_proof(db_session, 987654)

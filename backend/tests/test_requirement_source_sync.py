"""P2-B 外部增量同步契约：重复/乱序/重放/权限变化/外部删除的隔离测试。"""

from __future__ import annotations

from app.services.requirement_source_sync import (
    ACTION_MARK_DELETED,
    ACTION_MARK_PERMISSION,
    ACTION_PENDING_REVIEW,
    ACTION_SKIP_DUPLICATE,
    ACTION_SKIP_OUT_OF_ORDER,
    ACTION_SKIP_REPLAY,
    SYNC_CONTRACT_VERSION,
    SyncEvent,
    assert_only_review_actions,
    plan_sync,
)


def event(**overrides):
    payload = {"table": "MART.LOAN", "columns": ["CUST_NO"]}
    values = {
        "source": "metadata-platform",
        "object_kind": "table",
        "object_key": "MART.LOAN",
        "source_version": 2,
        "cursor": 100,
        "payload": payload,
        "observed_at": "2026-10-23T18:00:00+08:00",
    }
    values.update(overrides)
    return SyncEvent(**values)


def test_new_version_only_requests_review_never_writes_requirement():
    plan = plan_sync([event()])
    assert plan.contract_version == SYNC_CONTRACT_VERSION
    assert len(plan.decisions) == 1
    decision = plan.decisions[0]
    assert decision.action == ACTION_PENDING_REVIEW
    assert "不自动改写" in decision.reason
    assert plan.review_required == (decision.identity,)
    assert plan.requires_review is True
    assert_only_review_actions(plan)


def test_duplicate_event_is_idempotent():
    first = event()
    plan = plan_sync([first], known_keys={first.identity()})
    assert plan.duplicates == 1
    assert plan.decisions[0].action == ACTION_SKIP_DUPLICATE
    assert plan.review_required == ()

    payload_prefix = f"{first.identity()}:{first.payload_hash()[:12]}"
    again = plan_sync([first], known_keys={payload_prefix})
    assert again.decisions[0].action == ACTION_SKIP_DUPLICATE


def test_batch_contains_duplicates_in_one_pass():
    first = event()
    plan = plan_sync([first, event()])
    assert plan.duplicates == 1
    assert len(plan.review_required) == 1


def test_out_of_order_version_is_skipped():
    plan = plan_sync([event(source_version=1, cursor=99)], known_versions={"metadata-platform:table:MART.LOAN": 2})
    assert plan.decisions[0].action == ACTION_SKIP_OUT_OF_ORDER
    assert plan.out_of_order == 1
    assert plan.review_required == ()


def test_replay_with_stale_cursor_and_version_is_skipped():
    plan = plan_sync(
        [event(source_version=2, cursor=100)],
        known_cursors={"metadata-platform": 120},
        known_versions={"metadata-platform:table:MART.LOAN": 2},
    )
    assert plan.decisions[0].action == ACTION_SKIP_REPLAY
    assert plan.replays == 1


def test_external_delete_and_permission_change_only_mark_review():
    plan = plan_sync([event(deleted=True), event(object_key="MART.CUSTOMER", permissions_changed=True)])
    actions = [decision.action for decision in plan.decisions]
    assert actions == [ACTION_MARK_DELETED, ACTION_MARK_PERMISSION]
    assert plan.deletions == 1
    assert plan.permission_changes == 1
    assert len(plan.review_required) == 2
    assert all("待复核" in decision.reason for decision in plan.decisions)


def test_invalid_events_are_reported_not_crashing():
    plan = plan_sync([event(object_key=""), event(source_version=-1)])
    assert plan.decisions == ()
    assert len(plan.issues) == 2
    assert plan.requires_review is False


def test_empty_batch_is_a_noop():
    plan = plan_sync([])
    assert plan.decisions == ()
    assert plan.as_dict()["requires_review"] is False

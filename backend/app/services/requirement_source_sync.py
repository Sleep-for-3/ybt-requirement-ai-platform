"""P2-B 外部系统增量同步：适配契约与"只产生待复核状态"的裁决规则。

真实的外部系统（元数据平台 / 调度平台 / 脚本版本库）接口当前不可得，所以本模块
交付的是**适配契约 + 确定性裁决**，而不是联调结论：

* 每个来源必须有稳定的 ``source`` 标识、单调递增的 ``source_version`` 与 ``cursor``；
* 同一 ``(source, object_key, source_version)`` 重放必须幂等；
* 乱序事件不能覆盖更新的版本，只记录为 ``out_of_order``；
* 外部删除与权限变化只把对象标成待复核，**不改写**任何既有需求或正式交付；
* 任何应用动作的状态一律是 ``pending_review``，不存在"直接生效到需求"的路径。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

SYNC_CONTRACT_VERSION = "external-source-sync-v1"

ACTION_PENDING_REVIEW = "pending_review"
ACTION_SKIP_DUPLICATE = "skip_duplicate"
ACTION_SKIP_OUT_OF_ORDER = "skip_out_of_order"
ACTION_SKIP_REPLAY = "skip_replay"
ACTION_MARK_DELETED = "mark_deleted_pending_review"
ACTION_MARK_PERMISSION = "mark_permission_pending_review"

_ACTIONS = (
    ACTION_PENDING_REVIEW,
    ACTION_SKIP_DUPLICATE,
    ACTION_SKIP_OUT_OF_ORDER,
    ACTION_SKIP_REPLAY,
    ACTION_MARK_DELETED,
    ACTION_MARK_PERMISSION,
)


@dataclass(frozen=True)
class SyncEvent:
    source: str
    object_kind: str
    object_key: str
    source_version: int
    cursor: int
    payload: Mapping[str, Any] = field(default_factory=dict)
    deleted: bool = False
    permissions_changed: bool = False
    observed_at: str = ""

    def identity(self) -> str:
        return f"{self.source}:{self.object_kind}:{self.object_key}:{self.source_version}"

    def payload_hash(self) -> str:
        material = json.dumps(self.payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(material.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class SyncDecision:
    identity: str
    action: str
    reason: str
    source: str
    object_key: str
    source_version: int
    cursor: int
    payload_hash: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "identity": self.identity,
            "action": self.action,
            "reason": self.reason,
            "source": self.source,
            "object_key": self.object_key,
            "source_version": self.source_version,
            "cursor": self.cursor,
            "payload_hash": self.payload_hash,
        }


@dataclass(frozen=True)
class SyncPlan:
    contract_version: str
    decisions: tuple[SyncDecision, ...]
    review_required: tuple[str, ...]
    duplicates: int
    out_of_order: int
    replays: int
    deletions: int
    permission_changes: int
    issues: tuple[str, ...] = ()

    @property
    def requires_review(self) -> bool:
        return bool(self.review_required)

    def as_dict(self) -> dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "decisions": [decision.as_dict() for decision in self.decisions],
            "review_required": list(self.review_required),
            "duplicates": self.duplicates,
            "out_of_order": self.out_of_order,
            "replays": self.replays,
            "deletions": self.deletions,
            "permission_changes": self.permission_changes,
            "issues": list(self.issues),
            "requires_review": self.requires_review,
        }


def _validate(event: SyncEvent, issues: list[str]) -> bool:
    if not event.source or not event.object_kind or not event.object_key:
        issues.append(f"事件 {event.identity()} 缺少 source/object_kind/object_key，已忽略")
        return False
    if not isinstance(event.source_version, int) or event.source_version < 0:
        issues.append(f"事件 {event.identity()} 的 source_version 必须是非负整数，已忽略")
        return False
    if not isinstance(event.cursor, int) or event.cursor < 0:
        issues.append(f"事件 {event.identity()} 的 cursor 必须是非负整数，已忽略")
        return False
    return True


def plan_sync(
    events: Iterable[SyncEvent],
    *,
    known_keys: Iterable[str] = (),
    known_cursors: Mapping[str, int] | None = None,
    known_versions: Mapping[str, int] | None = None,
) -> SyncPlan:
    """把一批外部事件裁决成"是否需要人工复核"，不做任何写库动作。

    ``known_keys`` 是已入库的事件身份（含 payload hash 前缀），用于幂等；
    ``known_cursors`` / ``known_versions`` 是每个来源已处理到的游标与对象版本，
    用于识别乱序与重放。调用方负责真正落库，本函数只做确定性判断。
    """

    known = set(known_keys)
    cursors = dict(known_cursors or {})
    versions = dict(known_versions or {})
    decisions: list[SyncDecision] = []
    review: list[str] = []
    issues: list[str] = []
    duplicates = out_of_order = replays = deletions = permission_changes = 0

    for event in events:
        if not _validate(event, issues):
            continue
        identity = event.identity()
        object_identity = f"{event.source}:{event.object_kind}:{event.object_key}"
        payload_hash = event.payload_hash()
        if identity in known or f"{identity}:{payload_hash[:12]}" in known:
            duplicates += 1
            decisions.append(SyncDecision(identity, ACTION_SKIP_DUPLICATE, "同一来源版本已处理", event.source, event.object_key, event.source_version, event.cursor, payload_hash))
            continue
        last_cursor = cursors.get(event.source)
        if last_cursor is not None and event.cursor <= last_cursor and event.source_version <= versions.get(object_identity, -1):
            replays += 1
            decisions.append(SyncDecision(identity, ACTION_SKIP_REPLAY, "游标与版本均未前进，视为重放", event.source, event.object_key, event.source_version, event.cursor, payload_hash))
            continue
        current_version = versions.get(object_identity)
        if current_version is not None and event.source_version < current_version:
            out_of_order += 1
            decisions.append(SyncDecision(identity, ACTION_SKIP_OUT_OF_ORDER, f"事件版本 {event.source_version} 旧于已知版本 {current_version}", event.source, event.object_key, event.source_version, event.cursor, payload_hash))
            continue

        if event.deleted:
            deletions += 1
            action, reason = ACTION_MARK_DELETED, "外部已删除：只标待复核，既有需求与正式交付保持不变"
        elif event.permissions_changed:
            permission_changes += 1
            action, reason = ACTION_MARK_PERMISSION, "来源权限变化：只标待复核，不继续使用旧授权"
        else:
            action, reason = ACTION_PENDING_REVIEW, "新版本只产生待复核状态，不自动改写需求"

        decisions.append(SyncDecision(identity, action, reason, event.source, event.object_key, event.source_version, event.cursor, payload_hash))
        review.append(identity)
        known.add(identity)
        # 必须按 (source, object_kind, object_key) 记版本：只用裸 object_key 时，
        # 同批内同一对象的旧版本事件会因为查不到复合键而被当成新版本。
        versions[object_identity] = max(versions.get(object_identity, -1), event.source_version)
        cursors[event.source] = max(cursors.get(event.source, 0), event.cursor)

    return SyncPlan(
        contract_version=SYNC_CONTRACT_VERSION,
        decisions=tuple(decisions),
        review_required=tuple(review),
        duplicates=duplicates,
        out_of_order=out_of_order,
        replays=replays,
        deletions=deletions,
        permission_changes=permission_changes,
        issues=tuple(issues),
    )


def assert_only_review_actions(plan: SyncPlan) -> None:
    """兜底断言：任何同步结果都不得声称"已直接生效到需求"。"""

    for decision in plan.decisions:
        if decision.action not in _ACTIONS:
            raise ValueError(f"未知同步动作 {decision.action!r}")
        if decision.action == ACTION_PENDING_REVIEW and "自动改写" not in decision.reason:
            raise ValueError("新版本动作必须说明不自动改写需求")

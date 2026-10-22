"""冻结需求版本 → 引用版本钉扎（C10）。

需求快照记录的是**当次交付时**所依据的制度版本；知识库可能已经启用了更新的版本。
引用裁判如果按“当前最新版本”判定，就会出现两种错误：

* 旧版本需求被新制度静默替换（历史结论被追认为合规）；
* 新制度下的答案引用旧版本制度仍被判 supported。

因此裁判需要一条来自**冻结快照**的钉扎：``{来源标题: 监管版本}``。
本模块只做确定性抽取，不调用模型、不修改任何冻结内容：

1. 递归扫描 ``RequirementRevision.content_json`` 中的证据条目
   （含 ``title``/``source_name`` 等标题键 + ``regulatory_version``）；
2. 同一标题出现多个版本时按“后出现者不覆盖先出现者”保守处理，并额外保留
   ``_conflicting`` 标记，让上层知道该标题本身存在版本歧义；
3. 版本必须是字符串且非空，空值/占位值不参与钉扎（否则会把 unknown 误判为违规）。
"""

from __future__ import annotations

from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import RequirementRevision
from app.services.requirement_revisions import load_revision

#: 证据条目里可能承载“来源标题”的键，按优先级排列。
TITLE_KEYS = ("title", "source_name", "document_title", "document_name", "name")

#: 版本字段名。
VERSION_KEYS = ("regulatory_version", "version")

_PLACEHOLDERS = {"", "n/a", "na", "none", "null", "unknown", "未标注", "未知", "无"}


def _clean(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text or text.lower() in _PLACEHOLDERS:
        return None
    return text


def _iter_dicts(value: Any) -> Iterable[dict]:
    if isinstance(value, dict):
        yield value
        for item in value.values():
            yield from _iter_dicts(item)
    elif isinstance(value, list):
        for item in value:
            yield from _iter_dicts(item)


def pinned_versions_from_content(content: dict) -> dict[str, str]:
    """From a frozen requirement snapshot, build ``{source title: regulatory version}``.

    Entries without a usable title or version are skipped: a missing pin must stay
    "unknown" instead of becoming a false version violation.
    """

    pins: dict[str, str] = {}
    conflicting: set[str] = set()
    for entry in _iter_dicts(content or {}):
        version = None
        for key in VERSION_KEYS:
            version = _clean(entry.get(key))
            if version:
                break
        if version is None:
            continue
        title = None
        for key in TITLE_KEYS:
            title = _clean(entry.get(key))
            if title:
                break
        if title is None:
            continue
        existing = pins.get(title)
        if existing is None:
            pins[title] = version
        elif existing != version:
            # 同一标题在快照里出现两个版本：保留先出现者（保守），标记歧义。
            conflicting.add(title)
    for title in conflicting:
        pins.setdefault(f"_conflicting:{title}", "1")
    return pins


def pinned_versions_for_revision(
    db: Session,
    project_id: int,
    requirement_id: int,
    content_version: int,
) -> dict[str, str]:
    """Read the frozen revision and return its pinned versions.

    Reuses ``load_revision`` so the digest integrity check and the 404/409 semantics
    are identical to every other requirement-revision read path.
    """

    revision = load_revision(db, project_id, requirement_id, content_version)
    return pinned_versions_from_content(revision.content_json)


def revision_has_version_pins(db: Session, project_id: int, requirement_id: int) -> list[int]:
    """Content versions of a requirement that actually carry version pins."""

    rows = db.scalars(
        select(RequirementRevision)
        .where(
            RequirementRevision.project_id == project_id,
            RequirementRevision.requirement_id == requirement_id,
        )
        .order_by(RequirementRevision.content_version)
    ).all()
    return [row.content_version for row in rows if pinned_versions_from_content(row.content_json)]

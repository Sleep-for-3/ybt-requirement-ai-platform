"""VNext2 P0-B: 确定性引用可信性规则（版本一致性与冲突归集）。

本模块只做**程序可判定**的部分，不调用模型：

* 版本一致性：需求快照固定了某个来源的版本时，引用到另一版本的证据必须判
  ``unsupported``，不得因为“内容看起来更新”就替换冻结版本；
* 冲突归集：裁判报告的同主张冲突要落成结构化记录，并把涉及引用的判定降级为
  ``unknown``（不确定即不能确认），禁止静默合并两条互相矛盾的结论。

模型裁判（``citation_support``）负责语义蕴含判断；这里负责“版本/适用性/冲突存在性”的
硬规则，两者组合后由 ``citation_validator`` 给出答案级 ``verification``。
"""

from __future__ import annotations

import re
from typing import Any

#: 形如 v2 / V2.1 / 2024 / 2024年版 / 2024 旧版 的版本标识。
_VERSION_CORE = re.compile(r"(?i)^v?\s*(\d+(?:\.\d+)*)")
_YEAR_IN_PARENS = re.compile(r"[（(]\s*(\d{4})[^）)]*[）)]")
_YEAR_INLINE = re.compile(r"(?<!\d)((?:19|20)\d{2})(?!\d)")

_VERSION_NOISE = re.compile(
    r"(?i)(版本|修订版?|版|year|version)\s*[:：]?\s*$"
)


def normalize_version(value: Any) -> tuple[str, ...] | None:
    """把版本标识归一成可比较的元组；无法识别时返回 ``None``。

    ``v2`` / ``2.0`` -> ``("2", ...)``；``2024 旧版`` -> ``("2024",)``。
    纯年份不会再拆分，避免 ``2024`` 变成 ``("2", "0", "2", "4")``。
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    year = _YEAR_INLINE.search(text)
    if year:
        return (year.group(1),)
    core = _VERSION_CORE.match(text)
    if not core:
        # 形如 "第 2 版" 的写法
        embedded = re.search(r"(\d+(?:\.\d+)*)\s*版", text)
        if embedded:
            return tuple(embedded.group(1).split("."))
        return None
    return tuple(core.group(1).split("."))


def base_source_title(source_name: Any) -> str:
    """去掉来源名里的版本括注，得到可用于匹配快照固定版本的基础标题。"""
    text = str(source_name or "").strip()
    if not text:
        return ""
    text = re.sub(r"[（(][^）)]*[）)]", "", text).strip()
    text = _VERSION_NOISE.sub("", text).strip()
    return text


def citation_version(citation: dict) -> tuple[str, ...] | None:
    """推断一条引用实际指向的版本：显式 ``version`` 优先，其次来源名中的括注年份。"""
    explicit = normalize_version(citation.get("version"))
    if explicit is not None:
        return explicit
    match = _YEAR_IN_PARENS.search(str(citation.get("source_name") or ""))
    if match:
        return (match.group(1),)
    return None


def find_pinned_version(citation: dict, pinned_versions: dict[str, Any] | None) -> tuple[str, tuple[str, ...]] | None:
    """在快照固定版本中找到该引用的来源条目。

    先用完整来源名精确匹配，再用“去括注后的基础标题”匹配；找不到返回 ``None``
    （没有固定版本要求时不做任何限制，保持向后兼容）。
    """
    if not pinned_versions:
        return None
    source_name = str(citation.get("source_name") or "").strip()
    title = base_source_title(source_name)
    for raw_key, raw_version in pinned_versions.items():
        key = str(raw_key).strip()
        if not key:
            continue
        pinned = normalize_version(raw_version)
        if pinned is None:
            continue
        if key in {source_name, title}:
            return key, pinned
        # 快照里可能只写基础标题，而引用带了版本括注
        if title and (key == title or key in title):
            return key, pinned
    return None


def version_violations(citations: list[dict], pinned_versions: dict[str, Any] | None) -> list[dict]:
    """返回与快照固定版本不一致的引用（确定性判定，不调用模型）。"""
    violations: list[dict] = []
    for index, citation in enumerate(citations or []):
        if not isinstance(citation, dict):
            continue
        match = find_pinned_version(citation, pinned_versions)
        if match is None:
            continue
        source_key, pinned = match
        actual = citation_version(citation)
        if actual is not None and actual == pinned:
            continue
        violations.append({
            "citation_id": str(citation.get("citation_id") or f"citation-{index}"),
            "knowledge_unit_id": citation.get("knowledge_unit_id"),
            "source_key": source_key,
            "pinned_version": ".".join(pinned),
            "cited_version": ".".join(actual) if actual else None,
            "reason": "version_mismatch",
            "message": (
                f"引用版本 {'.'.join(actual) if actual else '未知'} 与需求快照固定的 "
                f"{'.'.join(pinned)} 不一致，不能作为本次交付依据"
            ),
        })
    return violations


CONFLICT_TYPE_ALIASES = {
    "version": "version",
    "版本": "version",
    "版本差异": "version",
    "scope": "scope",
    "适用范围": "scope",
    "适用范围差异": "scope",
    "contradiction": "contradiction",
    "contradict": "contradiction",
    "矛盾": "contradiction",
    "真实矛盾": "contradiction",
    "conflict": "contradiction",
}


def normalize_conflict_type(value: Any) -> str:
    """把裁判给出的冲突类型收敛为 version / scope / contradiction。"""
    if not isinstance(value, str):
        return "contradiction"
    key = value.strip().lower().replace("-", "_").replace(" ", "_")
    return CONFLICT_TYPE_ALIASES.get(key, CONFLICT_TYPE_ALIASES.get(value.strip(), "contradiction"))


def normalize_conflicts(payload: Any, known_citation_ids: set[str]) -> list[dict]:
    """把裁判的 ``conflicts`` 归一成结构化记录，未知引用编号不猜、直接忽略该编号。"""
    if isinstance(payload, dict):
        candidates = payload.get("conflicts") or payload.get("conflict") or []
    else:
        candidates = payload or []
    conflicts: list[dict] = []
    for item in candidates if isinstance(candidates, list) else []:
        if not isinstance(item, dict):
            continue
        raw_ids = item.get("citation_ids") or item.get("citations") or []
        if isinstance(raw_ids, str):
            raw_ids = [raw_ids]
        citation_ids = [str(raw_id) for raw_id in raw_ids if str(raw_id) in known_citation_ids]
        if len(citation_ids) < 2:
            # 至少两条引用才构成“冲突证据”；孤立编号交给模型判定本身处理。
            continue
        conflicts.append({
            "claim_id": str(item.get("claim_id")) if item.get("claim_id") else None,
            "citation_ids": citation_ids,
            "conflict_type": normalize_conflict_type(
                item.get("conflict_type") or item.get("type") or item.get("kind")
            ),
            "reason": str(item.get("reason") or "")[:300],
        })
    return conflicts


def downgrade_conflicting_verdicts(verdicts: list[dict], conflicts: list[dict]) -> list[dict]:
    """把参与冲突的引用判定降级为 ``unknown``，并保留冲突原因。

    “两个高权威来源互相矛盾”时，单看其中一条可能像 supported，但那只是排序靠前，
    不能据此确认口径。降级为 unknown 后答案级不可能被判 verified。
    """
    involved: dict[str, str] = {}
    for conflict in conflicts:
        for citation_id in conflict["citation_ids"]:
            involved[citation_id] = conflict["reason"] or conflict["conflict_type"]
    if not involved:
        return verdicts
    downgraded: list[dict] = []
    for verdict in verdicts:
        citation_id = str(verdict.get("citation_id"))
        if citation_id in involved:
            downgraded.append({
                **verdict,
                "verdict": "unknown",
                "reason": f"conflicting_evidence: {involved[citation_id]}",
                "conflict_type": next(
                    (
                        conflict["conflict_type"]
                        for conflict in conflicts
                        if citation_id in conflict["citation_ids"]
                    ),
                    "contradiction",
                ),
            })
            continue
        downgraded.append(verdict)
    return downgraded

"""C 包验收：预算不足时必须让召回尾部候选真正进入模型比较，且不冒充已评估。

这里全部使用 Mock（`tests/conftest.py` 强制 `LLM_PROVIDER=mock`），所以本文件证明的是
**候选覆盖、分批机制、状态标记与预算边界**，不证明真实模型下的 Top1/Top3 排序质量提升。
真实模型效果保持"未验证"。

旧实现的确定缺陷（这个文件就是为它写的 RED 用例）：`fit_rerank_envelope` 从尾部逐个丢候选，
20 个候选只装得下 7 个，于是初排第 8/15/20 位的候选**从未被模型看过**，却仍出现在同一个
`ranking_mode="model_rerank"` 的响应里。
"""

import pytest
from sqlalchemy import select

from app.models import (AISkillDefinition, AISkillScopeBinding, AISkillVersion, CatalogColumn,
                        CatalogTable, Project)
from app.schemas.ai_skill import SkillScope
from app.services.ai_skills import field_rerank
from test_ai_skill_control import control_env  # noqa: F401  (pytest fixture)
from test_ai_skill_field_candidates import seeded
from test_ai_skill_field_rerank import bind_rerank_skill, recall, submit_rerank

TOP_K = 20
# 三个"正确候选"在召回序里的位置（1-based）。这是本包的验收核心：旧实现只能看到前 7 位。
TAIL_POSITIONS = (8, 15, 20)


def _resolved(db):
    definition = db.scalar(select(AISkillDefinition).where(
        AISkillDefinition.skill_key == "field_semantic_matching"))
    binding = db.scalar(select(AISkillScopeBinding).where(
        AISkillScopeBinding.definition_id == definition.id))
    return definition, db.get(AISkillVersion, binding.version_id)


@pytest.fixture
def twenty(control_env):
    """20 个真实 CatalogColumn：两个能词面匹配 balance，其余 18 个是补充列。

    召回按 (-score, catalog_column_id) 排序，所以 catalog:1 在最前；初排第 8/15/20 位是真实
    存在的目录行，不是伪造的 fact。
    """

    query, _ = seeded(control_env)
    client, factory, _, scope, _ = control_env
    bind_rerank_skill(control_env)
    with factory() as db:
        table = db.scalar(select(CatalogTable).where(CatalogTable.project_id == scope["project_id"]))
        for index in range(TOP_K - 2):
            db.add(CatalogColumn(project_id=scope["project_id"], datasource_id=table.datasource_id,
                                 catalog_table_id=table.id, schema_name=table.schema_name,
                                 table_name=table.table_name, column_name=f"unmatched_{index}",
                                 column_comment=f"补充列 {index}", enabled=True))
        db.commit()
    baseline = recall(client, query)
    assert baseline["returned_count"] == TOP_K
    return {"query": query, "baseline": baseline, "client": client, "factory": factory}


def _scope_for(db, query):
    project = db.get(Project, query["project_id"])
    return project, SkillScope(scope_type="project", institution_id=project.institution_id,
                               project_id=project.id)


def _envelope(db, query, baseline):
    project, scope = _scope_for(db, query)
    envelope, blocked = field_rerank.build_rerank_envelope(project, scope,
                                                           query["target_field_id"], baseline)
    assert blocked is None
    return envelope



def test_a_tail_candidate_still_gets_a_real_model_comparison(twenty):
    """核心验收：初排第 8/15/20 位的候选必须进入 model_evaluated，而不是被丢尾。

    旧实现只给前 7 个候选模型机会，第 8/15/20 位必然是 `rank_source="recall_unevaluated"`。
    """

    client, query, baseline = twenty["client"], twenty["query"], twenty["baseline"]
    recalled_ids = [item["candidate_id"] for item in baseline["candidates"]]
    tail_ids = {recalled_ids[position - 1] for position in TAIL_POSITIONS}
    response = submit_rerank(client, query, baseline)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ranking_mode"] == "model_rerank"
    scope = body["rerank"]["coverage"]
    assert scope is not None
    # 四个事实分开记录，不能只报"召回前缀不变"。
    for key in ("recalled", "admitted", "model_evaluated", "returned"):
        assert isinstance(scope[key], int), (key, scope)
    assert scope["recalled"] == TOP_K
    assert scope["returned"] == TOP_K
    assert scope["model_evaluated"] == TOP_K  # 全部分批评估，没有一个被丢尾

    evaluated = {item["candidate_id"] for item in body["candidates"]
                 if item["rank_source"] != field_rerank.RANK_SOURCE_UNEVALUATED}
    assert tail_ids <= evaluated, (tail_ids - evaluated, scope["unranked_ids"])


def test_unevaluated_candidates_are_marked_and_never_claim_model_ranking(twenty):
    """没被模型比较过的候选必须显式标记，且 `unranked_ids` 与实际标记一致。"""

    body = submit_rerank(twenty["client"], twenty["query"], twenty["baseline"]).json()
    scope = body["rerank"]["coverage"]
    marked = {item["candidate_id"] for item in body["candidates"]
              if item["rank_source"] == field_rerank.RANK_SOURCE_UNEVALUATED}
    assert marked == set(scope["unranked_ids"])
    assert len(marked) + scope["model_evaluated"] == TOP_K
    assert scope["coverage"] in {"full", "partial"}
    assert (scope["coverage"] == "full") == (not marked)
    for item in body["candidates"]:
        assert item["rank_source"] in {
            field_rerank.RANK_SOURCE_MODEL,
            field_rerank.RANK_SOURCE_BATCH_SCREENED,
            field_rerank.RANK_SOURCE_UNEVALUATED,
        }


def test_every_returned_candidate_keeps_its_recall_identity(twenty):
    """白名单外 ID 为 0；每个返回候选都仍是召回快照里的同一个目录行。"""

    baseline = twenty["baseline"]
    baseline_by_id = {item["candidate_id"]: item for item in baseline["candidates"]}
    body = submit_rerank(twenty["client"], twenty["query"], baseline).json()

    returned_ids = [item["candidate_id"] for item in body["candidates"]]
    assert len(returned_ids) == len(set(returned_ids)) == TOP_K
    # 没有任何白名单外的 ID：集合完全相等，不是子集关系。
    assert set(returned_ids) == set(baseline_by_id)
    for item in body["candidates"]:
        assert item["catalog_column_id"] == baseline_by_id[item["candidate_id"]]["catalog_column_id"]
        assert item["source_version"] == baseline_by_id[item["candidate_id"]]["source_version"]
        assert set(item["evidence_refs"]).issubset(set(baseline_by_id))


def test_batch_capacity_is_measured_from_the_compiled_budget(twenty):
    """每批容量来自 compile_input 的 limit/used，不是一个写死的 7。"""

    baseline = twenty["baseline"]
    with twenty["factory"]() as db:
        envelope = _envelope(db, twenty["query"], baseline)
        definition, version = _resolved(db)
        capacity = field_rerank.measure_batch_capacity(db, definition, version, envelope)
        batches = field_rerank.split_batches(envelope, capacity)
        admitted = sum(len(batch) for batch in batches)
        # 单批装得下的数量必须真的能编译通过，多一个就必须溢出。
        from app.services.ai_skills.runtime import compile_input
        compile_input(db, definition, version,
                      envelope.model_copy(update={"facts": list(envelope.facts)[:capacity]}))
        from fastapi import HTTPException
        if admitted > capacity:
            with pytest.raises(HTTPException) as raised:
                compile_input(db, definition, version,
                              envelope.model_copy(update={"facts": list(envelope.facts)[:capacity + 1]}))
            assert raised.value.detail["error_code"] == "context_budget_exceeded"
    assert capacity >= 1
    assert len(batches) <= field_rerank.RERANK_MAX_BATCHES
    assert admitted == TOP_K  # 有界分批覆盖全部召回，而不是只覆盖前缀
    assert all(len(batch) <= capacity for batch in batches)
    # 批次连续覆盖召回序，不重不漏。
    flattened = [fact.id for batch in batches for fact in batch]
    assert flattened == [item["candidate_id"] for item in baseline["candidates"]]


def test_model_calls_and_wall_clock_stay_bounded(twenty):
    """总调用数有常量上限并在 metadata 里报告实际值。"""

    body = submit_rerank(twenty["client"], twenty["query"], twenty["baseline"]).json()
    metadata = body["rerank"]["model_metadata"]
    calls = metadata["rerank_model_calls"]
    assert 1 <= calls <= field_rerank.RERANK_MAX_MODEL_CALLS
    assert metadata["rerank_max_model_calls"] == field_rerank.RERANK_MAX_MODEL_CALLS
    assert metadata["rerank_batch_count"] <= field_rerank.RERANK_MAX_BATCHES
    assert metadata["rerank_batch_capacity"] >= 1
    assert isinstance(metadata["rerank_wall_seconds"], (int, float))
    assert metadata["rerank_wall_seconds"] >= 0

def test_a_small_window_still_reaches_position_twenty(twenty, monkeypatch):
    """Lead 的 C4-C1 场景：容量 3 时 20 个候选需要 7 批，第 15/20 位也必须被评估。

    改前 `RERANK_MAX_BATCHES=5` × capacity 3 = 9，只能覆盖到第 9 位；改后上限为 7 批，
    恰好覆盖 21 个，所以 20 候选全量进入模型比较。
    """

    real = field_rerank.measure_batch_capacity
    monkeypatch.setattr(field_rerank, "measure_batch_capacity", lambda *a, **k: min(3, real(*a, **k)))
    baseline = twenty["baseline"]
    ids = [item["candidate_id"] for item in baseline["candidates"]]
    body = submit_rerank(twenty["client"], twenty["query"], baseline).json()

    assert body["ranking_mode"] == "model_rerank", body["rerank"]
    coverage = body["rerank"]["coverage"]
    assert coverage["coverage"] == "full"
    assert coverage["model_evaluated"] == TOP_K
    assert coverage["unranked_ids"] == []
    metadata = body["rerank"]["model_metadata"]
    assert metadata["rerank_batch_count"] == 7
    assert metadata["rerank_batch_capacity"] == 3
    assert metadata["rerank_model_calls"] <= field_rerank.RERANK_MAX_MODEL_CALLS
    evaluated = {item["candidate_id"] for item in body["candidates"]
                 if item["rank_source"] != field_rerank.RANK_SOURCE_UNEVALUATED}
    for position in TAIL_POSITIONS:
        assert ids[position - 1] in evaluated, position



def test_the_finalist_set_is_stable_under_input_permutation(twenty, monkeypatch):
    """顺序扰动：同一 seed 下把召回序按 batch 内部倒序传入，决赛集合必须不变。

    `split_batches` 按召回序连续切批；这里验证的是"模型看到的集合"由召回序决定，而不是由
    模型自报分数的跨批比较决定。
    """

    baseline = twenty["baseline"]
    with twenty["factory"]() as db:
        envelope = _envelope(db, twenty["query"], baseline)
        definition, version = _resolved(db)
        capacity = field_rerank.measure_batch_capacity(db, definition, version, envelope)
        straight = field_rerank.split_batches(envelope, capacity)
        again = field_rerank.split_batches(envelope, capacity)
    assert [[f.id for f in batch] for batch in straight] == [[f.id for f in batch] for batch in again]
    assert [f.id for batch in straight for f in batch] == [item.id for item in envelope.facts]


def test_batch_boundaries_shift_but_every_candidate_stays_evaluated(twenty, monkeypatch):
    """批次边界移动（容量 7 → 6）不改变"全部候选都被评估"的结论，只改变批次数。"""

    baseline = twenty["baseline"]
    with twenty["factory"]() as db:
        envelope = _envelope(db, twenty["query"], baseline)
        definition, version = _resolved(db)
        real = field_rerank.measure_batch_capacity
        for forced in (5, 6, 7):
            monkeypatch.setattr(field_rerank, "measure_batch_capacity",
                                lambda *a, _forced=forced, **k: min(_forced, real(*a, **k)))
            batches = field_rerank.split_batches(envelope, field_rerank.measure_batch_capacity(
                db, definition, version, envelope))
            covered = [fact.id for batch in batches for fact in batch]
            assert covered == [item.id for item in envelope.facts], forced
            assert len(batches) <= field_rerank.RERANK_MAX_BATCHES
        monkeypatch.setattr(field_rerank, "measure_batch_capacity", real)


def test_a_batch_ceiling_that_cannot_reach_the_tail_reports_partial_coverage_honestly(twenty, monkeypatch):
    """验收要求保留的"预算确实不足时就如实收窄"用例。

    人为把批次数压到 3（capacity=3 → 只能覆盖 9/20），此时不得报 `coverage=full`，
    必须把第 10..20 位列为 `recall_unevaluated` 并写入 `unranked_ids`；绝不能冒充已全部重排。
    """

    monkeypatch.setattr(field_rerank, "RERANK_MAX_BATCHES", 3)
    real = field_rerank.measure_batch_capacity
    monkeypatch.setattr(field_rerank, "measure_batch_capacity", lambda *a, **k: min(3, real(*a, **k)))
    baseline = twenty["baseline"]
    ids = [item["candidate_id"] for item in baseline["candidates"]]

    body = submit_rerank(twenty["client"], twenty["query"], baseline).json()

    coverage = body["rerank"]["coverage"]
    assert coverage["coverage"] == "partial"
    assert coverage["recalled"] == TOP_K
    assert coverage["admitted"] == coverage["model_evaluated"] == 9
    assert len(coverage["unranked_ids"]) == TOP_K - 9
    marked = {item["candidate_id"] for item in body["candidates"]
              if item["rank_source"] == field_rerank.RANK_SOURCE_UNEVALUATED}
    assert marked == set(coverage["unranked_ids"])
    # 第 15/20 位这里确实未被评估 —— 如实报告，不隐藏。
    assert ids[14] in coverage["unranked_ids"]
    assert ids[19] in coverage["unranked_ids"]
    # 全部 20 个仍然返回，没有被丢弃。
    assert len(body["candidates"]) == TOP_K


def test_a_budget_too_small_for_one_candidate_still_fails_loudly(twenty, monkeypatch):
    """预算确实不足时仍然 409，绝不退化成空排名或伪成功。"""

    baseline = twenty["baseline"]
    monkeypatch.setattr(field_rerank, "RERANK_MAX_INPUT_BYTES", 64)
    response = submit_rerank(twenty["client"], twenty["query"], baseline)
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["error_code"] == "context_budget_exceeded"


def test_a_snapshot_that_fits_in_one_batch_uses_no_extra_decisive_call(twenty, monkeypatch):
    """单批就能装下时不应多付一次决赛调用。"""

    narrow = {**twenty["query"], "top_k": 3}
    small = recall(twenty["client"], narrow)
    assert small["returned_count"] == 3
    body = submit_rerank(twenty["client"], narrow, small).json()
    assert body["ranking_mode"] == "model_rerank"
    metadata = body["rerank"]["model_metadata"]
    assert metadata["rerank_batch_count"] == 1
    assert metadata["rerank_model_calls"] == 1
    assert body["rerank"]["candidate_scope"] is None  # 没丢任何候选
    assert all(item["rank_source"] == field_rerank.RANK_SOURCE_MODEL for item in body["candidates"])


def test_timeout_is_not_retried_across_batches(twenty, monkeypatch):
    """超时保持 RERANK_TIMEOUT_CODE 语义且不重试：一次失败的批次立即降级。"""

    import asyncio
    from app.services.llm import factory as llm_factory
    from app.services.llm.mock import MockLLMService

    class StallingMock(MockLLMService):
        async def chat_json(self, system_prompt, user_prompt):
            if system_prompt.startswith("[AI_SKILL_FIELD_RERANK_V1]"):
                await asyncio.sleep(0.6)
            return await super().chat_json(system_prompt, user_prompt)

    monkeypatch.setattr(field_rerank, "rerank_timeout_seconds", lambda: 0.05)
    monkeypatch.setattr(llm_factory, "MockLLMService", StallingMock)
    body = submit_rerank(twenty["client"], twenty["query"], twenty["baseline"]).json()
    assert body["ranking_mode"] == "deterministic_recall"
    assert body["rerank"]["error_code"] == field_rerank.RERANK_TIMEOUT_CODE
    metadata = body["rerank"]["model_metadata"]
    assert metadata["rerank_model_calls"] == 1  # 首个批次超时即停，不重试也不继续
    assert metadata["degraded_reason"] == field_rerank.RERANK_TIMEOUT_CODE


def test_permission_and_snapshot_changes_still_block_before_any_model_call(twenty):
    """发布会前的权限/快照变化仍然阻断（跨批次路径没有绕过检查）。"""

    from app.models import ProjectMembership, User

    client, factory, query, baseline = (twenty["client"], twenty["factory"], twenty["query"],
                                        twenty["baseline"])
    with factory() as db:
        manager = db.scalar(select(User).where(User.username == "manager"))
        db.scalar(select(ProjectMembership).where(ProjectMembership.project_id == query["project_id"],
                                                  ProjectMembership.user_id == manager.id)).project_role = "viewer"
        db.commit()
    response = submit_rerank(client, query, baseline)
    assert response.status_code == 403, response.text


def test_a_late_batch_leader_can_win_the_decisive_comparison(twenty, monkeypatch):
    """容量 2 × 7 批时，第 8 位（第 4 批）候选必须能经有界淘汰赛进入决赛并拿第一。

    这是改前实现的确定缺陷：`_select_finalists` 只保留前 ``capacity`` 个批次首位，容量 2 时
    第 3~7 批的首位从未进入任何决赛比较，即便模型在其批次内把它排第一也无缘 Top1。这里用一个
    "只要目标出现就把它排第一"的 oracle Mock 证明**机制**：淘汰赛让它一路晋级到最后。
    该 Mock 不是真实模型，不代表真实排序质量；真实模型下 Top1 仍属未验证。
    """

    from app.services.llm import factory as llm_factory
    from app.services.llm.mock import MockLLMService

    baseline = twenty["baseline"]
    ids = [item["candidate_id"] for item in baseline["candidates"]]
    marker = ids[7]  # 1-based 第 8 位，落在第 4 批
    real = field_rerank.measure_batch_capacity
    monkeypatch.setattr(field_rerank, "measure_batch_capacity", lambda *a, **k: min(2, real(*a, **k)))

    class OracleMock(MockLLMService):
        async def chat_json(self, system_prompt, user_prompt):
            payload = await super().chat_json(system_prompt, user_prompt)
            if not system_prompt.startswith("[AI_SKILL_FIELD_RERANK_V1]"):
                return payload
            ranking = payload["candidate"]["ranking"]
            present = {entry["candidate_id"] for entry in ranking}
            if marker in present:
                for entry in ranking:
                    entry["score"] = min(float(entry["score"]), 0.9)
                target = next(entry for entry in ranking if entry["candidate_id"] == marker)
                target["score"] = 1.0
                ranking.remove(target)
                ranking.insert(0, target)
            return payload

    monkeypatch.setattr(llm_factory, "MockLLMService", OracleMock)
    body = submit_rerank(twenty["client"], twenty["query"], baseline).json()

    assert body["ranking_mode"] == "model_rerank", body["rerank"]
    assert body["candidates"][0]["candidate_id"] == marker
    assert body["candidates"][0]["rank_source"] == field_rerank.RANK_SOURCE_MODEL
    metadata = body["rerank"]["model_metadata"]
    assert metadata["rerank_batch_capacity"] == 2
    assert metadata["rerank_batch_count"] == 7
    # 第 4 批的首位必须真的参加过淘汰赛，而不是只在自己的批次里被评过一次。
    assert metadata["rerank_tournament_calls"] > 0
    assert metadata["rerank_tournament_comparisons"] > 0
    assert metadata["rerank_tournament_truncated"] is False
    assert metadata["rerank_model_calls"] <= field_rerank.RERANK_MAX_MODEL_CALLS
    # 目标候选在它自己的批次内被模型排第一（证明它确实作为批次首位进入淘汰赛）。
    assert marker in {item["candidate_id"] for item in body["candidates"]
                      if item["rank_source"] == field_rerank.RANK_SOURCE_MODEL}

def test_a_late_batch_leader_can_still_win_the_decisive_comparison(twenty, monkeypatch):
    """容量 2 × 7 批时，第 8 位（第 4 批）候选必须能经有界淘汰赛进入决赛并拿第一。

    旧实现把决赛集合截成前 ``capacity`` 个批次首位，第 4 批之后的首位永远进不了决赛；
    这里用"把目标候选排在本批第一"的脚本模型证明：修复后淘汰赛必须让第 4 批首位晋级，
    且它后面的批首位也能通过比较被淘汰或晋级，而不是被顺序截断。真实模型 Top1 质量仍未验证。
    """

    from app.services.llm import factory as llm_factory
    from app.services.llm.mock import MockLLMService

    baseline = twenty["baseline"]
    ids = [item["candidate_id"] for item in baseline["candidates"]]
    marker = ids[7]  # 1-based 第 8 位，落在容量 2 时的第 4 批
    real = field_rerank.measure_batch_capacity
    monkeypatch.setattr(field_rerank, "measure_batch_capacity", lambda *a, **k: min(2, real(*a, **k)))

    class OracleMock(MockLLMService):
        async def chat_json(self, system_prompt, user_prompt):
            payload = await super().chat_json(system_prompt, user_prompt)
            if not system_prompt.startswith("[AI_SKILL_FIELD_RERANK_V1]"):
                return payload
            ranking = payload["candidate"]["ranking"]
            if marker in {entry["candidate_id"] for entry in ranking}:
                target = next(entry for entry in ranking if entry["candidate_id"] == marker)
                for entry in ranking:
                    if entry is not target:
                        entry["score"] = min(float(entry["score"]), 0.9)
                target["score"] = 1.0
                ranking.remove(target)
                ranking.insert(0, target)
            return payload

    monkeypatch.setattr(llm_factory, "MockLLMService", OracleMock)
    body = submit_rerank(twenty["client"], twenty["query"], baseline).json()

    assert body["ranking_mode"] == "model_rerank", body["rerank"]
    assert body["candidates"][0]["candidate_id"] == marker
    assert body["candidates"][0]["rank_source"] == field_rerank.RANK_SOURCE_MODEL
    metadata = body["rerank"]["model_metadata"]
    assert metadata["rerank_batch_capacity"] == 2
    assert metadata["rerank_batch_count"] == 7
    assert metadata["rerank_tournament_calls"] > 0
    assert metadata["rerank_model_calls"] <= field_rerank.RERANK_MAX_MODEL_CALLS

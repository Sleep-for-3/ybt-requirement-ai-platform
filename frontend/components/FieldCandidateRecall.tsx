"use client";

import { useEffect, useRef, useState } from "react";
import { apiPost, CandidateSourceRecommendation } from "@/lib/api";

type Candidate = {
  candidate_id: string; datasource_id: number; database_name: string | null;
  schema_name: string; table_name: string; column_name: string;
  column_comment: string | null; table_comment: string | null; data_type: string | null;
  nullable: boolean | null; source_version: string; score: number; rationale: string;
  recall_score?: number; recall_rationale?: string; evidence_refs?: string[]; rank_source?: "model" | "recall";
};
type Query = { project_id: number; target_field_id: number; query: string; top_k: number; datasource_ids: number[] };
type Recall = { context_hash: string; candidates: Candidate[]; scanned_count: number; returned_count: number };
type Rerank = {
  context_hash: string; candidates: Candidate[];
  ranking_mode: "model_rerank" | "deterministic_recall";
  execution_metadata: { execution_kind?: string; model_name?: string | null; provider_type?: string };
  rerank: {
    status: "applied" | "failed"; error_code: string | null; message: string;
    skill_key?: string; skill_version?: { id: number; version_no: number; content_hash: string } | null;
    binding_scope?: string | null; run_id?: number | null; snapshot_recheck?: string;
    model_metadata?: Record<string, unknown> | null;
  };
};

// Mock and deterministic runs must never read as real-model quality validation.
const EXECUTION_LABELS: Record<string, string> = {
  real_model: "真实模型", mock_model: "Mock 模型（仅流程验证）", deterministic: "确定性规则", degraded: "模型调用降级",
};

function executionLabel(kind?: string) {
  if (!kind) return "未记录";
  return EXECUTION_LABELS[kind] || kind;
}

function rankingLabel(result: Rerank | null) {
  if (!result) return "确定性召回排序（本次未调用模型）";
  if (result.ranking_mode === "model_rerank") return `模型重排（${executionLabel(result.execution_metadata?.execution_kind)}）`;
  return `确定性召回排序（模型重排未成功：${result.rerank.error_code || "未知原因"}）`;
}

export function FieldCandidateRecall({ projectId, fieldId, scenarioId, onPrepared }: {
  projectId: number; fieldId: number; scenarioId: number | null; onPrepared: (item: CandidateSourceRecommendation) => void;
}) {
  const [query, setQuery] = useState("");
  const [datasources, setDatasources] = useState("");
  const [limit, setLimit] = useState("20");
  const [snapshot, setSnapshot] = useState<{ input: Query; result: Recall } | null>(null);
  const [rerank, setRerank] = useState<Rerank | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [verified, setVerified] = useState(false);
  const [prepared, setPrepared] = useState<string[]>([]);
  const alive = useRef(false);
  const flight = useRef(false);
  const sequence = useRef(0);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  useEffect(() => {
    // A different project, target field or scenario invalidates every prior response.
    sequence.current += 1;
    setSnapshot(null); setRerank(null); setVerified(false); setError(""); setPrepared([]);
  }, [projectId, fieldId, scenarioId]);

  function invalidate() {
    sequence.current += 1;
    setSnapshot(null); setRerank(null); setVerified(false); setError(""); setPrepared([]);
  }
  async function prepare(candidateId: string) {
    if (flight.current || !snapshot || !scenarioId) return;
    flight.current = true; setBusy(true); setError("");
    try {
      const result = await apiPost<{ recommendation: CandidateSourceRecommendation }>("/ai-skills/field-candidates/prepare", {
        input: snapshot.input, context_hash: snapshot.result.context_hash, candidate_id: candidateId, scenario_id: scenarioId,
      });
      if (alive.current) {setPrepared(old => [...old, candidateId]);onPrepared(result.recommendation);}
    } catch (failure) {
      if (alive.current) {setRerank(null);setSnapshot(null);setVerified(false);setError(failure instanceof Error ? failure.message : "加入候选失败，请重新检索。");}
    } finally {flight.current = false;if (alive.current) setBusy(false);}
  }
  async function modelRerank() {
    if (flight.current || !snapshot) return;
    const request = ++sequence.current;
    flight.current = true; setBusy(true); setError(""); setRerank(null);
    try {
      const result = await apiPost<Rerank>("/ai-skills/field-candidates/model-rerank", {
        input: snapshot.input, context_hash: snapshot.result.context_hash,
      });
      if (alive.current && request === sequence.current) setRerank(result);
    } catch (failure) {
      if (alive.current && request === sequence.current) {
        setRerank(null);
        setError(failure instanceof Error ? failure.message : "模型重排未成功，当前仍为确定性召回排序。");
      }
    } finally {flight.current = false;if (alive.current) setBusy(false);}
  }
  async function run(recheck: boolean) {
    if (flight.current) return;
    flight.current = true; setBusy(true); setError(""); setVerified(false);
    try {
      if (recheck && snapshot) {
        await apiPost("/ai-skills/field-candidates/validate-ranking", {
          input: snapshot.input, context_hash: snapshot.result.context_hash,
          ranking: snapshot.result.candidates.map(({ candidate_id, score, rationale }) => ({ candidate_id, score, rationale })),
        });
        if (alive.current) setVerified(true);
      } else {
        setSnapshot(null); setRerank(null); setPrepared([]); sequence.current += 1;
        const parts = datasources.trim() ? datasources.split(/[,，\s]+/).filter(Boolean) : [];
        if (parts.some(value => !/^[1-9]\d*$/.test(value) || !Number.isSafeInteger(Number(value)))) {
          throw new Error("数据源编号须为正整数，多个编号用逗号分隔。");
        }
        const ids = Array.from(new Set(parts.map(Number)));
        if (ids.length > 30) throw new Error("每次最多指定 30 个数据源。");
        const input = { project_id: projectId, target_field_id: fieldId, query: query.trim(), top_k: Number(limit), datasource_ids: ids };
        const result = await apiPost<Recall>("/ai-skills/field-candidates", input);
        if (alive.current) setSnapshot({ input, result });
      }
    } catch (failure) {
      if (alive.current) { setSnapshot(null); setRerank(null); setError(failure instanceof Error ? failure.message : "候选检索失败，请重试。"); }
    } finally {
      flight.current = false;
      if (alive.current) setBusy(false);
    }
  }

  const displayed = rerank ? rerank.candidates : snapshot?.result.candidates || [];
  return <section aria-label="目录字段候选核验" className="panel mt-5 p-4">
    <h2 className="text-[15px] font-semibold text-ink">目录字段候选核验</h2>
    <p className="mt-1 text-xs text-slate-600">按当前字段与检索词进行词面匹配，未调用模型。仅查询本项目已启用的目录，不连接源库，也不写入映射。采用仍需在来源推荐流程中完成人工选择与安全探查。</p>
    <div className="mt-3 grid items-end gap-3 md:grid-cols-[2fr_1fr_auto_auto]">
      <label className="text-xs">补充检索词<input className="control mt-1 w-full" value={query} maxLength={2000} disabled={busy}
        onChange={event => { setQuery(event.target.value); invalidate(); }} placeholder="如余额、account balance" /></label>
      <label className="text-xs">限定数据源编号<input className="control mt-1 w-full" value={datasources} disabled={busy}
        onChange={event => { setDatasources(event.target.value); invalidate(); }} placeholder="留空检索本项目全部目录" /></label>
      <label className="text-xs">候选上限<select className="control mt-1 w-full" value={limit} disabled={busy}
        onChange={event => { setLimit(event.target.value); invalidate(); }}>
        {[10, 20, 50].map(value => <option key={value} value={value}>{value}</option>)}
      </select></label>
      <button className="button-secondary" disabled={busy} onClick={() => void run(false)}>{busy ? "正在核验…" : "检索目录候选"}</button>
    </div>
    {error && <p role="alert" className="mt-3 text-sm text-red-700">{error}</p>}
    {snapshot && <div className="mt-3 space-y-3">
      <div className="flex flex-wrap items-center gap-3 text-xs">
        <p role="status">扫描 {snapshot.result.scanned_count} 个目录字段，返回 {snapshot.result.returned_count} 个候选。分数表示词面相似度，不代表业务正确率。</p>
        <button className="button-secondary" disabled={busy} onClick={() => void run(true)}>复核目录快照</button>
        <button className="button-secondary" disabled={busy} onClick={() => void modelRerank()}>模型重排（显式请求）</button>
        {verified && <span role="status">本次复核通过，仍需人工确认。</span>}
      </div>
      <p className="text-xs text-slate-600">模型重排只有在点击后才会调用固定发布的 Skill；它只重排上方候选，不新增目录字段、不选择、不探查、不写入映射。</p>
      <div role="status" className="rounded border border-line p-2 text-xs">
        <p>当前列表来源：{rankingLabel(rerank)}</p>
        {rerank?.rerank.status === "applied" && <p className="mt-1">
          固定 Skill：{rerank.rerank.skill_key} v{rerank.rerank.skill_version?.version_no} · 作用域 {rerank.rerank.binding_scope}
          {" · "}运行编号 {rerank.rerank.run_id} · 模型 {rerank.execution_metadata?.model_name || "未记录"}
        </p>}
        {rerank && <p className="mt-1">{rerank.rerank.message}</p>}
      </div>
      <details className="text-xs"><summary>查看检索快照</summary><p className="mt-1 break-all">{snapshot.result.context_hash}</p></details>
      {!displayed.length && <p className="text-sm text-slate-600">当前范围没有可用目录字段，请检查数据源及目录是否启用。</p>}
      <div className="grid gap-3 lg:grid-cols-2">{displayed.map(item => <article key={item.candidate_id} className="rounded border border-line p-3 text-xs">
        <h3 className="break-all font-semibold">{[item.database_name, item.schema_name, item.table_name, item.column_name].filter(Boolean).join(".")}</h3>
        <p className="mt-1">{item.column_comment || "无字段说明"} · {item.data_type || "类型未记录"} · {item.nullable === true ? "可空" : item.nullable === false ? "非空" : "空值约束未知"}</p>
        <p className="mt-1">{item.rank_source === "model" ? "模型排序分" : "召回排序分"} {item.score.toFixed(3)}（非置信度） · {item.rationale}</p>
        {item.rank_source === "model" && <p className="mt-1">原始召回排序分 {item.recall_score?.toFixed(3)} · 引用 {item.evidence_refs?.length ? item.evidence_refs.join("、") : "无"}</p>}
        <button className="button-secondary mt-2" disabled={busy || !scenarioId || prepared.includes(item.candidate_id)}
          onClick={() => void prepare(item.candidate_id)}>{prepared.includes(item.candidate_id) ? "已加入来源候选" : "加入来源候选"}</button>
        <details className="mt-2"><summary>查看目录出处</summary><div className="mt-1 space-y-1 break-all">
          <p>候选编号：{item.candidate_id} · 数据源编号：{item.datasource_id}</p>
          <p>表说明：{item.table_comment || "未记录"}</p><p>目录版本：{item.source_version}</p>
        </div></details>
      </article>)}</div>
    </div>}
  </section>;
}

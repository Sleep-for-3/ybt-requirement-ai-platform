"use client";
import { useState } from "react";
import { apiPost } from "@/lib/api";

type Evidence = { id: string; kind: string; value: unknown; source: { source_type: string; source_id: string; source_version: string; locator: string } };
export type SkillResult = {
  facts: Evidence[];
  policy_evidence: Evidence[];
  claims: { claim_type: string; text: string; fact_ids: string[]; policy_clause_ids: string[] }[];
  policy_comparisons?: { status: "matched" | "conflict" | "missing_implementation" | "pending"; fact_ids: string[]; policy_clause_ids: string[]; rationale: string; difference: string }[];
  gaps: { code: string; message: string }[];
  execution_metadata: { skill_key?: string; skill_version_no?: number; run_id?: number; context_hash?: string; model_name?: string; execution_kind?: string };
};

function EvidenceList({ items }: { items: Evidence[] }) {
  return <div className="mt-2 space-y-2">{items.map(item => <details key={item.id} className="rounded border bg-white p-2">
    <summary className="cursor-pointer break-all">{item.kind} · {item.source.source_type} #{item.source.source_id}</summary>
    <p className="mt-1 break-all text-[10px] text-slate-500">来源版本 {item.source.source_version} · 证据 {item.id}</p>
    <pre className="mt-2 max-h-48 overflow-auto whitespace-pre-wrap break-all text-[11px]">{typeof item.value === "string" ? item.value : JSON.stringify(item.value, null, 2)}</pre>
  </details>)}</div>;
}

export function SkillEvidenceLayers({ result, projectId, revisionId, regressionInput }: { result: SkillResult; projectId: number; revisionId: number | null; regressionInput?: unknown }) {
  const meta = result.execution_metadata;
  const [comment, setComment] = useState("");
  const [feedbackId, setFeedbackId] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [converted, setConverted] = useState(false);
  async function feedback(convert: boolean) {
    setBusy(true); setMessage("");
    try {
      if (convert && feedbackId) {
        await apiPost(`/ai-skills/${encodeURIComponent(meta.skill_key || "")}/feedback/${feedbackId}/test-case`, { name: `血缘反馈 #${feedbackId}`, input: regressionInput });
        setConverted(true); setMessage("已转为固定回归用例，相关版本发布前需要重新测试。");
      } else {
        const saved = await apiPost<{ id: number }>(`/projects/${projectId}/feedback`, { model_call_log_id: meta.run_id, feedback_type: "correction", target_type: "lineage_revision", target_id: revisionId, rating: "negative", comment });
        setFeedbackId(saved.id); setMessage("反馈已保存，尚未改变人工确认。");
      }
    } catch (error) { setMessage(error instanceof Error ? error.message : "反馈操作失败"); } finally { setBusy(false); }
  }
  return <section aria-label="Skill 分层证据" className="mt-4 space-y-3 border-t pt-3 text-xs">
    <p className="break-all text-slate-500">Skill {meta.skill_key} · v{meta.skill_version_no} · 运行 #{meta.run_id}</p>
    <div><h4 className="font-semibold">1. 固定版本事实</h4><EvidenceList items={result.facts}/></div>
    <div><h4 className="font-semibold">2. 有效制度条款</h4>{result.policy_evidence.length ? <EvidenceList items={result.policy_evidence}/> : <p className="mt-1 text-amber-800">缺少制度依据，不能据脚本现状推定监管要求。</p>}</div>
    <div><h4 className="font-semibold">3. AI 候选</h4>{result.claims.length ? result.claims.map((claim, index) => <div key={index} className="mt-2 rounded bg-sky-50 p-2"><p>{claim.text}</p><p className="mt-1 break-all text-[10px] text-slate-500">引用：{[...claim.fact_ids, ...claim.policy_clause_ids].join("、") || "待验证"}</p></div>) : <p className="mt-1 text-slate-500">本次没有可采纳的模型声明。</p>}</div>
    <div className="rounded bg-amber-50 p-2"><h4 className="font-semibold">4. 人工确认</h4><p className="mt-1">本次候选待人工确认；不会修改已有人工结论。</p></div>
    {!!result.policy_comparisons?.length && <div><h4 className="font-semibold">制度对照候选 · 待人工核验</h4>{result.policy_comparisons.map((item, index) => <details key={index} className="mt-2 rounded border border-amber-200 p-2"><summary className="cursor-pointer">{{ matched: "候选一致", conflict: "候选冲突", missing_implementation: "候选缺失实现", pending: "待确认" }[item.status] || "待确认"}：{item.rationale}</summary>{item.difference && <p className="mt-1">差异：{item.difference}</p>}<p className="mt-1 break-all text-[10px]">事实：{item.fact_ids.join("、")}；条款：{item.policy_clause_ids.join("、")}</p></details>)}</div>}
    {result.gaps.length > 0 && <div role="note"><h4 className="font-semibold">证据缺口</h4><ul className="mt-1 list-disc space-y-1 pl-4">{result.gaps.map((gap, index) => <li key={index}>{gap.message}</li>)}</ul></div>}
    <details><summary className="cursor-pointer text-slate-500">运行追溯</summary><p className="mt-1 break-all">输入哈希：{meta.context_hash}</p><p>{meta.model_name} · {meta.execution_kind}</p></details>
    {meta.run_id && revisionId && <div className="space-y-2 border-t pt-3"><label className="block">反馈说明<textarea className="mt-1 w-full rounded border p-2" rows={3} value={comment} disabled={busy || feedbackId !== null} onChange={event => setComment(event.target.value)}/></label>
      <button className="rounded border px-2 py-1 disabled:opacity-40" disabled={busy || !comment.trim() || feedbackId !== null} onClick={() => void feedback(false)}>保存本次运行反馈</button>
      {feedbackId && regressionInput != null && <button className="ml-2 rounded border px-2 py-1 disabled:opacity-40" disabled={busy || converted} onClick={() => void feedback(true)}>转为固定回归用例</button>}
      {message && <p role="status">{message}</p>}
    </div>}
  </section>;
}

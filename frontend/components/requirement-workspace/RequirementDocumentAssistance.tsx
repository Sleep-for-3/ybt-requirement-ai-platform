"use client";
import { useEffect, useRef, useState } from "react";
import { apiPost } from "@/lib/api";
import { SkillRunProvenance, type CandidateExecution } from "@/components/SkillRunProvenance";

const SECTIONS = { background: "背景", business_description: "业务说明", difference_analysis: "差异分析", missing_information: "缺失信息" };
type Result = { content_version: number; content_hash: string; execution_metadata: CandidateExecution;
  candidate: Record<keyof typeof SECTIONS, {text: string; fact_ids: string[]}[]> | null;
  gaps: {code: string; message: string}[]; facts: {id: string; value: unknown}[] };

export function RequirementDocumentAssistance({ projectId, requirementId, contentVersion, dirty }: {
  projectId: number; requirementId: number; contentVersion: number; dirty: boolean;
}) {
  const [result, setResult] = useState<Result | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const alive = useRef(true), flight = useRef(false);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  async function generate() {
    if (flight.current || dirty || !contentVersion) return;
    flight.current = true; setBusy(true); setError(""); setResult(null);
    try {
      const value = await apiPost<Result>(`/projects/${projectId}/requirements/${requirementId}/revisions/${contentVersion}/document-assistance`, {});
      if (alive.current) setResult(value);
    } catch (err) { if (alive.current) setError(err instanceof Error ? err.message : "生成失败，请核对权限、固定依据和 Skill 绑定。"); }
    finally { flight.current = false; if (alive.current) setBusy(false); }
  }
  return <section className="panel mb-3 space-y-3 p-4 text-xs" aria-label="固定版本文档辅助">
    <h2 className="text-sm font-semibold">固定版本文档辅助</h2>
    <p>基于内容 v{contentVersion || "待建立"} 整理背景、业务说明、差异分析和缺失信息。结果仅为候选，不改正文、人工判断或历史版本。</p>
    <p>需先固定采用文档辅助 Skill；当前仅支持本地模型配置。</p>
    <button className="button-secondary" disabled={busy || dirty || !contentVersion} onClick={() => void generate()}>{busy ? "正在整理候选…" : "生成文档辅助候选"}</button>
    {dirty && <p>请先保存修改，再选择固定版本生成。</p>}
    {error && <p role="alert" className="break-all text-red-700">{error}</p>}
    {result && <>
      <p className="break-all">依据：内容 v{result.content_version} · {result.content_hash}</p>
      <SkillRunProvenance metadata={result.execution_metadata}/>
      {Object.entries(SECTIONS).map(([key, label]) => <div key={key}><h3 className="font-semibold">{label}</h3>
        {result.candidate?.[key as keyof typeof SECTIONS]?.length ? result.candidate[key as keyof typeof SECTIONS].map((item, index) => <div key={index} className="my-2 rounded border p-2">
          <p className="whitespace-pre-wrap">{item.text}</p><p className="mt-1 break-all text-slate-500">引用：{item.fact_ids.join("、")}</p>
        </div>) : <p className="text-slate-500">未生成可用候选，请核对下方缺口。</p>}
      </div>)}
      <ul>{result.gaps.map((gap, index) => <li key={index} className="text-amber-800">{gap.message}</li>)}</ul>
      <details><summary>查看本次固定依据</summary>{result.facts.map(fact => <div key={fact.id} className="my-2"><p>{fact.id}</p><pre className="max-h-64 overflow-auto whitespace-pre-wrap break-all rounded bg-slate-50 p-2">{JSON.stringify(fact.value, null, 2)}</pre></div>)}</details>
    </>}
  </section>;
}

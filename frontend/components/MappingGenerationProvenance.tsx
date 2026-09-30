"use client";
import { useEffect, useState } from "react";
import { apiGet } from "@/lib/api";
import { SkillRunProvenance, type CandidateExecution } from "@/components/SkillRunProvenance";

type Provenance = { status: "unavailable" | "historical_unverified" | "current_text" | "text_changed";
  generated_at?: string; current_draft_hash?: string; displayed_matches?: boolean; execution_metadata: CandidateExecution | null };

export function MappingGenerationProvenance({ mappingType, mappingId, draftText }: {
  mappingType: "scenario_business" | "scenario_technical" | "source_to_mart" | "mart_to_ybt";
  mappingId: number; draftText?: string | null;
}) {
  const [data, setData] = useState<Provenance | null>(null);
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setData(null); setFailed(false);
    apiGet<Provenance>(`/mappings/${mappingType}/${mappingId}/generation-provenance`, { signal: controller.signal })
      .then(async value => {
        let displayedMatches = false;
        if (globalThis.crypto?.subtle && value.current_draft_hash) {
          const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(draftText || ""));
          displayedMatches = Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, "0")).join("") === value.current_draft_hash;
        }
        if (!controller.signal.aborted) setData({ ...value, displayed_matches: displayedMatches });
      })
      .catch(() => { if (!controller.signal.aborted) setFailed(true); });
    return () => controller.abort();
  }, [mappingType, mappingId, draftText, attempt]);
  if (failed) return <p className="text-xs text-amber-800">生成来源读取失败。<button className="ml-2 underline" onClick={() => setAttempt(value => value + 1)}>重试读取来源</button></p>;
  if (!data) return <p className="text-xs text-slate-500">正在读取生成来源…</p>;
  if (!data.execution_metadata) return <p className="text-xs text-slate-500">没有可核验的生成来源记录。</p>;
  return <div className="space-y-2">
    <p className="text-xs text-slate-600">最近成功生成记录{data.generated_at ? ` · ${new Date(data.generated_at).toLocaleString("zh-CN")}` : ""}</p>
    {data.status === "current_text" && data.displayed_matches ? <p className="text-xs text-emerald-800">当前 AI 草稿正文与此记录一致。</p> : <p className="text-xs text-amber-800">{data.status === "text_changed" ? "当前草稿正文已变化，此记录仅供历史追溯。" : data.status === "current_text" ? "尚未确认页面正文与服务端一致，请刷新草稿后核验。" : "历史记录未保存正文关联哈希，无法核验当前草稿来源。"}</p>}
    <SkillRunProvenance metadata={data.execution_metadata}/>
  </div>;
}

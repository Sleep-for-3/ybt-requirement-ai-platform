"use client";

import { aiExecutionPresentation } from "@/lib/ai-execution-label.mjs";

export type CandidateExecution = {
  runtime_mode?: string; execution_kind?: string; provider_type?: string; model_name?: string | null;
  skill_key?: string; skill_version_id?: number; skill_version_no?: number; run_id?: number;
  context_hash?: string; context_complete?: boolean;
};

export function SkillRunProvenance({ metadata }: { metadata?: CandidateExecution }) {
  const execution = aiExecutionPresentation({ ...metadata, provider: metadata?.provider_type });
  const skill = metadata?.runtime_mode === "skill";
  return <section aria-label="候选生成来源" className="rounded border border-slate-200 bg-slate-50 p-3 text-xs">
    <p className="font-semibold">{skill ? `Skill 固定版本 v${metadata?.skill_version_no ?? "待核验"}` : "Legacy 提示词"} · {execution.label}</p>
    <p className="mt-1 text-slate-600">{execution.detail} 生成结果仍是候选，采用与人工确认需分别完成。</p>
    {metadata?.context_complete === false && <p className="mt-1 text-amber-800">本次输入存在证据缺口，请结合下方说明核验。</p>}
    <details className="mt-2"><summary className="cursor-pointer">查看运行来源</summary>
      <dl className="mt-2 space-y-1 break-all"><div><dt className="inline text-slate-500">实际模型：</dt><dd className="inline">{metadata?.model_name || "未记录"}</dd></div>
        <div><dt className="inline text-slate-500">运行编号：</dt><dd className="inline">{metadata?.run_id ? `#${metadata.run_id}` : "未记录"}</dd></div>
        {skill && <div><dt className="inline text-slate-500">能力：</dt><dd className="inline">{metadata?.skill_key}</dd></div>}
        <div><dt className="inline text-slate-500">固定输入哈希：</dt><dd className="inline">{metadata?.context_hash || "未记录"}</dd></div>
      </dl>
    </details>
  </section>;
}

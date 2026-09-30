"use client";

import { useEffect, useState } from "react";
import { ScrollText } from "lucide-react";
import Link from "next/link";

import { WorkspaceHeader } from "@/components/WorkspaceHeader";
import { apiGet } from "@/lib/api";

type PromptVersion = {
  id: number;
  skill_version_id?: number | null;
  prompt_key: string;
  version_no: number;
  system_prompt: string;
  user_prompt_template: string;
  enabled: boolean;
  change_note?: string | null;
  created_at?: string;
  created_by?: string | null;
  runtime_binding?: {
    editable: boolean;
    activation: string;
    system_prompt: string;
    user_prompt_template: string;
    note: string;
  };
};

export default function Page() {
  const [items, setItems] = useState<PromptVersion[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    void apiGet<PromptVersion[]>("/prompt-versions").then(setItems).catch(() => setError("无法读取 Prompt 版本记录，请确认当前账号具有平台管理员权限。"));
  }, []);

  return (
    <main>
      <WorkspaceHeader title="Prompt 版本" meta="平台管理员 · 只读技术记录" />
      <div className="mx-auto max-w-5xl p-4 lg:p-6">
        <div className="mb-4 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
          <p className="font-semibold">当前页面不支持编辑、测试、发布或回滚。</p>
          <p className="mt-1">Legacy 调用读取最新启用版本的 system prompt，user prompt template 尚未参与渲染。已发布 Skill 记录是不可变兼容快照，由固定范围绑定决定生效，并渲染输入模板。</p>
          <Link href="/ai-control/skills" className="mt-2 inline-block underline">打开 AI Skill 配置中心</Link>
        </div>
        {error ? <div className="empty-state" role="alert"><ScrollText className="text-slate-300" size={28} /><p>{error}</p></div> : null}
        {items.length ? (
          <section className="space-y-3">
            <div className="panel-header">
              <h2 className="text-[15px] font-semibold text-ink">版本记录</h2>
            </div>
            {items.map((item) => <article className="panel overflow-hidden" key={item.id}>
              <header className="flex flex-wrap items-center gap-2 border-b border-line px-4 py-3">
                <strong className="text-sm text-ink">{item.prompt_key}</strong>
                <span className="badge-info">v{item.version_no}</span>
                <span className={item.enabled ? "badge-success" : "badge-muted"}>{item.skill_version_id ? "Skill 快照 · 依绑定生效" : item.enabled ? "Legacy · 已启用" : "Legacy · 未启用"}</span>
                <span className="ml-auto text-xs text-slate-500">{item.created_by || "未知创建人"}{item.created_at ? ` · ${new Date(item.created_at).toLocaleString("zh-CN")}` : ""}</span>
              </header>
              <div className="grid gap-3 p-4 text-xs lg:grid-cols-2">
                <div><p className="font-semibold text-slate-500">System prompt · {item.skill_version_id ? "发布快照" : "Legacy 版本记录"}</p><pre className="mt-1 max-h-64 overflow-auto whitespace-pre-wrap rounded bg-slate-50 p-3 text-slate-700">{item.system_prompt}</pre></div>
                <div><p className="font-semibold text-slate-500">User prompt template · {item.skill_version_id ? "Skill 运行时渲染" : "只读，尚未渲染"}</p><pre className="mt-1 max-h-64 overflow-auto whitespace-pre-wrap rounded bg-slate-50 p-3 text-slate-700">{item.user_prompt_template}</pre></div>
              </div>
              {item.change_note ? <p className="border-t border-line px-4 py-3 text-xs text-slate-500">变更说明：{item.change_note}</p> : null}
            </article>)}
          </section>
        ) : (
          !error ? <div className="empty-state">
            <ScrollText className="text-slate-300" size={28} />
            <p>暂无 Prompt 版本技术记录</p>
          </div> : null
        )}
      </div>
    </main>
  );
}

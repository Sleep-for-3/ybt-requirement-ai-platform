"use client";

import { FormEvent, useEffect, useState } from "react";
import { Plus } from "lucide-react";
import { useProjectWorkspace } from "@/components/ProjectContext";
import { WorkspaceHeader } from "@/components/WorkspaceHeader";
import { MartTable, apiGet, apiPost } from "@/lib/api";

export default function Page() {
  const { projectId } = useProjectWorkspace();
  const [items, setItems] = useState<MartTable[]>([]);
  const [message, setMessage] = useState("");
  async function reload() { if (projectId) setItems(await apiGet(`/projects/${projectId}/mart-tables`)); }
  useEffect(() => { void reload(); }, [projectId]);
  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!projectId) return; const form = new FormData(event.currentTarget);
    try { await apiPost(`/projects/${projectId}/mart-tables`, { table_code: form.get("code"), table_name: form.get("name"), subject_area: form.get("subject"), table_comment: form.get("comment"), is_existing: form.get("existing") === "on" }); event.currentTarget.reset(); setMessage("监管集市表已创建"); await reload(); }
    catch (error) { setMessage(error instanceof Error ? error.message : "创建失败"); }
  }
  return <main><WorkspaceHeader title="监管集市层" meta={`${items.length} 张集市表`} /><div className="mx-auto grid max-w-[1400px] gap-5 p-6 lg:grid-cols-[360px_1fr]"><form className="panel h-fit space-y-3 p-4" onSubmit={create}><h2 className="font-semibold">新增监管集市表</h2><input className="control" name="code" placeholder="表英文名" required /><input className="control" name="name" placeholder="表中文名" required /><input className="control" name="subject" placeholder="主题域" /><textarea className="control" name="comment" placeholder="表说明" /><label className="flex gap-2 text-sm"><input name="existing" type="checkbox" />已有集市表</label><button className="button-primary w-full"><Plus size={16} />新增</button>{message ? <p className="text-sm text-slate-600">{message}</p> : null}</form><section className="panel overflow-hidden">{items.map((item) => <div className="border-b border-line p-4 last:border-0" key={item.id}><div className="font-medium">{item.table_code} · {item.table_name}</div><div className="mt-1 text-sm text-slate-500">{item.subject_area || "主题待确认"} / {item.is_existing ? "已有" : "建议新增"}</div></div>)}</section></div></main>;
}

"use client";

import { FormEvent, useEffect, useState } from "react";
import { Plus } from "lucide-react";
import { useProjectWorkspace } from "@/components/ProjectContext";
import { WorkspaceHeader } from "@/components/WorkspaceHeader";
import { BusinessSystem, apiGet, apiPost } from "@/lib/api";

export default function Page() {
  const { projectId } = useProjectWorkspace();
  const [items, setItems] = useState<BusinessSystem[]>([]);
  const [message, setMessage] = useState("");
  async function reload() { if (projectId) setItems(await apiGet(`/projects/${projectId}/business-systems`)); }
  useEffect(() => { void reload(); }, [projectId]);
  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!projectId) return;
    const form = new FormData(event.currentTarget);
    try {
      await apiPost(`/projects/${projectId}/business-systems`, { system_code: form.get("code"), system_name: form.get("name"), owner_department: form.get("owner"), description: form.get("description"), enabled: true });
      event.currentTarget.reset(); setMessage("业务系统已创建"); await reload();
    } catch (error) { setMessage(error instanceof Error ? error.message : "创建失败"); }
  }
  return <main><WorkspaceHeader title="业务系统来源层" meta={`${items.length} 个业务系统`} /><div className="mx-auto grid max-w-[1400px] gap-5 p-6 lg:grid-cols-[360px_1fr]"><form className="panel h-fit space-y-3 p-4" onSubmit={create}><h2 className="font-semibold">新增业务系统</h2><input className="control" name="code" placeholder="系统代码" required /><input className="control" name="name" placeholder="系统名称" required /><input className="control" name="owner" placeholder="负责部门" /><textarea className="control" name="description" placeholder="脱敏说明" /><button className="button-primary w-full"><Plus size={16} />新增</button>{message ? <p className="text-sm text-slate-600">{message}</p> : null}</form><section className="panel overflow-hidden">{items.map((item) => <div className="border-b border-line p-4 last:border-0" key={item.id}><div className="font-medium">{item.system_code} · {item.system_name}</div><div className="mt-1 text-sm text-slate-500">{item.owner_department || "负责部门待确认"} / {item.enabled ? "启用" : "停用"}</div></div>)}</section></div></main>;
}

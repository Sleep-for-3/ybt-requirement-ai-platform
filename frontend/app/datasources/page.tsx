"use client";

import { FormEvent, useEffect, useState } from "react";
import { Database, Play } from "lucide-react";
import Link from "next/link";
import { useProjectWorkspace } from "@/components/ProjectContext";
import { WorkspaceHeader } from "@/components/WorkspaceHeader";
import { DataSource, apiGet, apiPost } from "@/lib/api";

export default function Page() {
  const { projectId } = useProjectWorkspace();
  const [items, setItems] = useState<DataSource[]>([]);
  const [message, setMessage] = useState("");
  async function reload() { if (projectId) setItems(await apiGet(`/projects/${projectId}/datasources`)); }
  useEffect(() => { void reload(); }, [projectId]);
  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!projectId) return; const form = new FormData(event.currentTarget);
    try { await apiPost(`/projects/${projectId}/datasources`, { name: form.get("name"), display_name: form.get("display"), db_type: "sqlite", database_name: form.get("database"), readonly_flag: true, enabled: true }); event.currentTarget.reset(); setMessage("只读 SQLite 数据源已创建"); await reload(); }
    catch (error) { setMessage(error instanceof Error ? error.message : "创建失败"); }
  }
  async function test(id: number) { try { const result = await apiPost<{ status: string; message: string }>(`/datasources/${id}/test`, {}); setMessage(`${result.status}: ${result.message}`); await reload(); } catch (error) { setMessage(error instanceof Error ? error.message : "连接失败"); } }
  return <main><WorkspaceHeader title="数据源" meta="只读连接、元数据同步与 SafeSqlExecutor" /><div className="mx-auto grid max-w-[1400px] gap-5 p-6 lg:grid-cols-[360px_1fr]"><form className="panel h-fit space-y-3 p-4" onSubmit={create}><h2 className="font-semibold">新增只读 SQLite 数据源</h2><input className="control" name="name" placeholder="连接名称" required /><input className="control" name="display" placeholder="显示名称" /><input className="control" name="database" placeholder="脱敏测试库路径" required /><button className="button-primary w-full"><Database size={16} />新增</button>{message ? <p className="text-sm text-slate-600">{message}</p> : null}</form><section className="panel overflow-hidden">{items.map((item) => <div className="flex items-center justify-between border-b border-line p-4 last:border-0" key={item.id}><div><div className="font-medium">{item.name} · {item.display_name || item.db_type}</div><div className="text-sm text-slate-500">只读 / {item.last_test_status || "未测试"}</div></div><div className="flex gap-2"><button className="button-secondary" onClick={() => test(item.id)}><Play size={16} />测试</button><Link className="button-primary" href={`/datasources/${item.id}/catalog`}>元数据目录</Link></div></div>)}</section></div></main>;
}

"use client";

import { FormEvent, useEffect, useState } from "react";
import { Play, Send } from "lucide-react";
import Link from "next/link";
import { useProjectWorkspace } from "@/components/ProjectContext";
import { WorkspaceHeader } from "@/components/WorkspaceHeader";
import { NaturalLanguageTask, NaturalLanguageTaskCreateResponse, apiGet, apiPost } from "@/lib/api";

export default function Page() {
  const { projectId } = useProjectWorkspace();
  const [items, setItems] = useState<NaturalLanguageTask[]>([]);
  const [message, setMessage] = useState("");
  const [reviewTasks, setReviewTasks] = useState<Array<{id:number;step_key:string;status:string;due_at?:string|null}>>([]);
  async function reload() { if (projectId) setItems(await apiGet(`/projects/${projectId}/nl-tasks`)); try { setReviewTasks(await apiGet("/me/tasks")); } catch { setReviewTasks([]); } }
  useEffect(() => { void reload(); }, [projectId]);
  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!projectId) return; const form = new FormData(event.currentTarget);
    try { const result = await apiPost<NaturalLanguageTaskCreateResponse>("/nl-tasks", { project_id: projectId, text: form.get("text") }); event.currentTarget.reset(); setMessage(result.message); await reload(); }
    catch (error) { setMessage(error instanceof Error ? error.message : "创建失败"); }
  }
  async function run(id: number) { try { await apiPost(`/nl-tasks/${id}/run`, {}); setMessage("安全查询任务已执行"); await reload(); } catch (error) { setMessage(error instanceof Error ? error.message : "执行失败"); } }
  return <main><WorkspaceHeader title="任务中心" meta="审核待办与自然语言安全查询" /><div className="mx-auto max-w-[1400px] space-y-5 p-6"><section className="panel"><div className="panel-header font-semibold">我的审核待办</div><div className="divide-y divide-line">{reviewTasks.map(item=><div className="flex items-center justify-between p-4" key={item.id}><div><b>{item.step_key}</b><div className="text-xs text-slate-500">{item.status} · {item.due_at||"未设置到期时间"}</div></div><Link className="button-primary" href={`/tasks/${item.id}`}>处理</Link></div>)}</div></section><div className="grid gap-5 lg:grid-cols-[420px_1fr]"><form className="panel h-fit p-4" onSubmit={create}><h2 className="mb-3 font-semibold">自然语言安全查询</h2><textarea className="control min-h-28" name="text" placeholder="例如：使用脱敏测试数据源查询客户表证件类型字段的空值率" required /><button className="button-primary mt-3 w-full"><Send size={16} />创建任务</button>{message ? <p className="mt-3 text-sm text-slate-600">{message}</p> : null}</form><section className="panel overflow-hidden">{items.map((item) => <div className="flex items-start justify-between gap-4 border-b border-line p-4 last:border-0" key={item.id}><div><div className="font-medium">{item.raw_text}</div><div className="mt-1 text-sm text-slate-500">{item.status} / {item.datasource_name || "数据源待识别"}</div></div><button className="button-secondary" disabled={item.status === "completed"} onClick={() => run(item.id)}><Play size={16} />执行</button></div>)}</section></div></div></main>;
}

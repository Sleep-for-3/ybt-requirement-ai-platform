"use client";

import { FormEvent, useEffect, useState } from "react";
import { Check, FileUp } from "lucide-react";
import { useProjectWorkspace } from "@/components/ProjectContext";
import { WorkspaceHeader } from "@/components/WorkspaceHeader";
import { TemplateDocument, TemplateUploadResponse, apiGet, apiPost, uploadForm } from "@/lib/api";

export default function Page() {
  const { projectId } = useProjectWorkspace();
  const [items, setItems] = useState<TemplateDocument[]>([]);
  const [message, setMessage] = useState("");
  async function reload() { if (projectId) setItems(await apiGet(`/projects/${projectId}/templates`)); }
  useEffect(() => { void reload(); }, [projectId]);
  async function upload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!projectId) return; const form = new FormData(event.currentTarget); form.set("project_id", String(projectId));
    try { const result = await uploadForm<TemplateUploadResponse>("/templates/upload", form); setMessage(`已解析 ${result.field_count} 个字段`); await reload(); }
    catch (error) { setMessage(error instanceof Error ? error.message : "上传失败"); }
  }
  async function apply(id: number) { try { await apiPost(`/templates/${id}/apply`, {}); setMessage("模板已 apply"); } catch (error) { setMessage(error instanceof Error ? error.message : "apply 失败"); } }
  return <main><WorkspaceHeader title="一表通模板" meta="上传、解析预览后显式 apply" /><div className="mx-auto grid max-w-[1400px] gap-5 p-6 lg:grid-cols-[360px_1fr]"><form className="panel h-fit p-4" onSubmit={upload}><input accept=".xlsx" className="control" name="file" required type="file" /><button className="button-primary mt-3 w-full"><FileUp size={16} />上传模板</button>{message ? <p className="mt-3 text-sm text-slate-600">{message}</p> : null}</form><section className="panel overflow-hidden">{items.map((item) => <div className="flex items-center justify-between border-b border-line p-4 last:border-0" key={item.id}><div><div className="font-medium">{item.file_name}</div><div className="text-sm text-slate-500">{item.parse_status}</div></div><button className="button-primary" disabled={item.parse_status !== "success"} onClick={() => apply(item.id)}><Check size={16} />Apply</button></div>)}</section></div></main>;
}

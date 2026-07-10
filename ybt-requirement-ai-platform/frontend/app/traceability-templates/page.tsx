"use client";

import { Check, Eye, FileUp } from "lucide-react";
import { FormEvent, useEffect, useState } from "react";

import { WorkspaceHeader } from "@/components/WorkspaceHeader";
import { Project, TraceabilityTemplateDocument, apiGet, apiPost, uploadForm } from "@/lib/api";

export default function TraceabilityTemplatesPage() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectId, setProjectId] = useState<number | null>(null);
  const [documents, setDocuments] = useState<TraceabilityTemplateDocument[]>([]);
  const [preview, setPreview] = useState<Record<string, unknown> | null>(null);
  const [message, setMessage] = useState("");

  useEffect(() => { void apiGet<Project[]>("/projects").then((items) => { setProjects(items); setProjectId(items[0]?.id || null); }); }, []);
  useEffect(() => { if (projectId) void apiGet<TraceabilityTemplateDocument[]>(`/projects/${projectId}/traceability-templates`).then(setDocuments); }, [projectId]);

  async function upload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!projectId) return;
    const form = new FormData(event.currentTarget);
    form.set("project_id", String(projectId));
    try {
      const result = await uploadForm<{ template_id: number; row_count: number; detected_scenarios: unknown[] }>("/traceability-templates/upload", form);
      setMessage(`解析完成：${result.row_count} 行，${result.detected_scenarios.length} 个场景`);
      setDocuments(await apiGet(`/projects/${projectId}/traceability-templates`));
    } catch (error) { setMessage(error instanceof Error ? error.message : "上传失败"); }
  }
  async function apply(id: number) {
    try {
      const result = await apiPost<Record<string, number>>(`/traceability-templates/${id}/apply`, {});
      setMessage(`apply 完成：字段 ${result.created_fields || 0}，场景 ${result.created_scenarios || 0}，业务口径 ${result.created_business_mappings || 0}，技术溯源 ${result.created_technical_lineages || 0}`);
    } catch (error) { setMessage(error instanceof Error ? error.message : "apply 失败"); }
  }
  return (
    <main>
      <WorkspaceHeader title="历史业务口径及溯源表" meta="多层表头、合并单元格、动态场景" actions={<select className="control w-64" value={projectId || ""} onChange={(e) => setProjectId(Number(e.target.value))}><option value="">选择项目</option>{projects.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select>} />
      <div className="mx-auto grid max-w-[1500px] gap-5 p-4 lg:grid-cols-[360px_1fr] lg:p-6">
        <form className="panel h-fit p-4" onSubmit={upload}>
          <label className="block text-sm font-medium" htmlFor="traceability-file">业务口径及溯源 Excel</label>
          <input accept=".xlsx" className="control mt-3" id="traceability-file" name="file" required type="file" />
          <button className="button-primary mt-3 w-full" type="submit"><FileUp size={16} />上传并解析</button>
          {message ? <p className="mt-3 whitespace-pre-wrap text-sm text-slate-600">{message}</p> : null}
        </form>
        <div className="space-y-4">
          <section className="panel overflow-hidden">
            {documents.map((document) => <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-4 py-3 last:border-0" key={document.id}><div><div className="font-medium">{document.file_name}</div><div className="mt-1 text-xs text-slate-500">{document.parse_status} / {document.parse_summary_json?.row_count || 0} 行 / {document.detected_scenarios_json?.map((item) => item.scenario_name).join("、") || "未识别场景"}</div></div><div className="flex gap-2"><button className="button-secondary" onClick={() => apiGet<Record<string, unknown>>(`/traceability-templates/${document.id}/preview`).then(setPreview)}><Eye size={16} />预览</button><button className="button-primary" disabled={document.parse_status !== "success"} onClick={() => apply(document.id)}><Check size={16} />Apply</button></div></div>)}
          </section>
          {preview ? <pre className="panel max-h-[620px] overflow-auto whitespace-pre-wrap p-4 text-xs leading-5">{JSON.stringify(preview, null, 2)}</pre> : null}
        </div>
      </div>
    </main>
  );
}

"use client";

import { Download } from "lucide-react";
import { useEffect, useState } from "react";

import { WorkspaceHeader } from "@/components/WorkspaceHeader";
import { Project, apiDownload, apiGet } from "@/lib/api";

export default function ExportPage() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectId, setProjectId] = useState<number | null>(null);
  const [message, setMessage] = useState("");
  useEffect(() => { void apiGet<Project[]>("/projects").then((items) => { setProjects(items); setProjectId(items[0]?.id || null); }); }, []);

  async function download() {
    if (!projectId) return;
    try {
      const result = await apiDownload(`/projects/${projectId}/export/traceability-workbook`);
      const url = URL.createObjectURL(result.blob);
      const anchor = document.createElement("a"); anchor.href = url; anchor.download = result.fileName; anchor.click(); URL.revokeObjectURL(url);
      setMessage(`已生成 ${result.fileName}`);
    } catch (error) { setMessage(error instanceof Error ? error.message : "导出失败"); }
  }
  return <main><WorkspaceHeader title="Excel 导出" meta="业务口径及技术溯源交付工作簿" /><div className="mx-auto max-w-3xl p-6"><section className="panel p-5"><label className="text-sm font-medium">项目</label><select className="control mt-2" value={projectId || ""} onChange={(e) => setProjectId(Number(e.target.value))}><option value="">选择项目</option>{projects.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select><button className="button-primary mt-4" disabled={!projectId} onClick={download}><Download size={16} />导出业务口径及技术溯源表</button>{message ? <p className="mt-3 text-sm text-slate-600">{message}</p> : null}</section></div></main>;
}

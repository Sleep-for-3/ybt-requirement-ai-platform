"use client";

import { Download } from "lucide-react";
import { useState } from "react";

import { ProjectSelector, useProjectWorkspace } from "@/components/ProjectContext";
import { WorkspaceHeader } from "@/components/WorkspaceHeader";
import { apiDownload } from "@/lib/api";

export default function ExportPage() {
  const { projectId } = useProjectWorkspace();
  const [message, setMessage] = useState("");

  async function download() {
    if (!projectId) return;
    try {
      const result = await apiDownload(`/projects/${projectId}/export/traceability-workbook`);
      const url = URL.createObjectURL(result.blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = result.fileName;
      anchor.click();
      URL.revokeObjectURL(url);
      setMessage(`已生成 ${result.fileName}`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "导出失败");
    }
  }

  return (
    <main>
      <WorkspaceHeader title="Excel 导出" meta="业务口径及技术溯源交付工作簿" />
      <div className="mx-auto max-w-3xl p-4 lg:p-6">
        <section className="panel">
          <div className="panel-header">
            <h2 className="text-[15px] font-semibold text-ink">导出交付工作簿</h2>
          </div>
          <div className="panel-body">
            <label className="text-sm font-medium text-ink">项目</label>
            <div className="mt-2">
              <ProjectSelector className="w-full" />
            </div>
            <button className="button-primary mt-4" disabled={!projectId} onClick={download}>
              <Download size={16} />
              导出业务口径及技术溯源表
            </button>
            {message ? (
              <p className="mt-4 rounded-lg border border-line bg-white px-3 py-2 text-sm text-slate-600">{message}</p>
            ) : null}
          </div>
        </section>
      </div>
    </main>
  );
}

"use client";

import { History, Upload } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { useProjectWorkspace } from "@/components/ProjectContext";
import { WorkspaceHeader } from "@/components/WorkspaceHeader";
import { HistoricalCaliberImport, apiGet, uploadForm } from "@/lib/api";
import { useProjectPermissions } from "@/lib/project-permissions";

const STATUS_BADGE: Record<string, string> = {
  approved: "badge-success",
  success: "badge-success",
  completed: "badge-success",
  enabled: "badge-success",
  failed: "badge-danger",
  rejected: "badge-danger",
  error: "badge-danger",
  pending: "badge-warning",
  running: "badge-warning",
  processing: "badge-warning",
  parsed: "badge-info",
  draft: "badge-info"
};

export default function Page() {
  const { projectId } = useProjectWorkspace();
  const permissions = useProjectPermissions(projectId);
  const [items, setItems] = useState<HistoricalCaliberImport[]>([]);
  const [file, setFile] = useState<File | null>(null);
  const [documentType, setDocumentType] = useState("full_package");
  const [message, setMessage] = useState("");

  async function load() {
    if (!projectId) return;
    try {
      setItems(await apiGet(`/projects/${projectId}/historical-calibers`));
    } catch (error) {
      setMessage(readError(error));
    }
  }

  useEffect(() => {
    void load();
  }, [projectId]);

  async function upload() {
    if (!projectId || !file) return;
    const form = new FormData();
    form.append("file", file);
    form.append("import_name", file.name.replace(/\.xlsx$/i, ""));
    form.append("document_type", documentType);
    try {
      await uploadForm(`/projects/${projectId}/historical-calibers/upload`, form);
      setMessage("历史口径已导入，列表已刷新。");
      setFile(null);
      await load();
    } catch (error) {
      setMessage(readError(error));
    }
  }

  return (
    <main>
      <WorkspaceHeader title="历史口径库" meta="持久导入、人工匹配与不覆盖复用" />
      <div className="mx-auto max-w-6xl space-y-5 p-4 lg:p-6">
        {permissions.can("historical_caliber.import") ? (
          <section className="panel">
            <div className="panel-header">
              <h2 className="text-[15px] font-semibold text-ink">导入历史口径</h2>
            </div>
            <div className="panel-body grid gap-3 md:grid-cols-[1fr_240px_auto]">
              <input
                accept=".xlsx"
                className="control"
                type="file"
                onChange={(event) => setFile(event.target.files?.[0] || null)}
              />
              <select
                className="control"
                value={documentType}
                onChange={(event) => setDocumentType(event.target.value)}
              >
                <option value="full_package">完整历史交付包</option>
                <option value="business_traceability">业务口径</option>
                <option value="source_to_mart">来源到集市</option>
                <option value="mart_to_ybt">集市到一表通</option>
              </select>
              <button className="button-primary" disabled={!file} onClick={upload}>
                <Upload size={15} />
                导入历史口径
              </button>
            </div>
          </section>
        ) : null}

        {message ? (
          <p className="rounded-lg border border-line bg-white px-3 py-2 text-sm text-slate-600">{message}</p>
        ) : null}

        {items.length ? (
          <section className="grid gap-4 md:grid-cols-2">
            {items.map((item) => (
              <Link
                className="panel flex flex-col p-4 transition hover:shadow-pop"
                href={`/historical-calibers/${item.id}`}
                key={item.id}
              >
                <div className="flex items-start justify-between gap-3">
                  <b className="text-sm font-semibold text-ink">{item.import_name}</b>
                  <span className={STATUS_BADGE[item.status] || "badge-neutral"}>{item.status}</span>
                </div>
                <p className="mt-2 text-sm text-slate-500">{item.document_type}</p>
                <div className="mt-3 grid grid-cols-3 gap-2 border-t border-line pt-3">
                  <div>
                    <div className="stat-label">记录</div>
                    <div className="mt-0.5 text-sm font-semibold tabular-nums text-ink">
                      {item.parse_summary_json.item_count || 0}
                    </div>
                  </div>
                  <div>
                    <div className="stat-label">已匹配</div>
                    <div className="mt-0.5 text-sm font-semibold tabular-nums text-ink">
                      {item.parse_summary_json.matched_count || 0}
                    </div>
                  </div>
                  <div>
                    <div className="stat-label">歧义</div>
                    <div className="mt-0.5 text-sm font-semibold tabular-nums text-ink">
                      {item.parse_summary_json.ambiguous_count || 0}
                    </div>
                  </div>
                </div>
                <p className="mt-2 text-xs text-slate-400">
                  {item.created_at ? new Date(item.created_at).toLocaleString() : ""}
                </p>
              </Link>
            ))}
          </section>
        ) : (
          <div className="empty-state">
            <History className="text-slate-300" size={28} />
            <p>当前项目还没有历史导入记录，导入历史交付包后可在此匹配并复用口径</p>
          </div>
        )}
      </div>
    </main>
  );
}

function readError(error: unknown) {
  return error instanceof Error ? error.message : "操作失败";
}

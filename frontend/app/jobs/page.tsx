"use client";

import { Cog, RotateCcw, X } from "lucide-react";
import { useEffect, useState } from "react";

import { useProjectWorkspace } from "@/components/ProjectContext";
import { WorkspaceHeader } from "@/components/WorkspaceHeader";
import { apiGet, apiPost } from "@/lib/api";

type Job = {
  id: number;
  job_type: string;
  status: string;
  progress: number;
  current_step?: string | null;
  error_message?: string | null;
};

function statusBadge(status: string) {
  if (["completed", "succeeded", "success"].includes(status)) return "badge-success";
  if (["failed", "error"].includes(status)) return "badge-danger";
  if (["pending", "queued", "running", "processing"].includes(status)) return "badge-warning";
  return "badge-neutral";
}

export default function Page() {
  const { projectId } = useProjectWorkspace();
  const [items, setItems] = useState<Job[]>([]);

  async function reload() {
    if (projectId) setItems(await apiGet(`/jobs?project_id=${projectId}`));
  }

  useEffect(() => {
    void reload();
  }, [projectId]);

  return (
    <main>
      <WorkspaceHeader title="后台任务" meta="进度、失败重试与取消" />
      <div className="mx-auto max-w-5xl p-4 lg:p-6">
        {items.length ? (
          <section className="panel divide-y divide-line">
            {items.map((item) => (
              <div className="p-4" key={item.id}>
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <b className="text-sm text-ink">
                    {item.job_type} #{item.id}
                  </b>
                  <div className="flex items-center gap-2">
                    <span className={statusBadge(item.status)}>{item.status}</span>
                    <span className="text-xs tabular-nums text-slate-500">{item.progress}%</span>
                  </div>
                </div>
                <div className="mt-2 h-2 rounded-full bg-slate-100">
                  <div className="h-2 rounded-full bg-pine transition-all" style={{ width: `${item.progress}%` }} />
                </div>
                {item.error_message ? (
                  <p className="mt-2 rounded-lg border border-coral-200 bg-coral-50 px-3 py-2 text-sm text-coral-700">
                    {item.error_message}
                  </p>
                ) : null}
                <div className="mt-3 flex gap-2">
                  {["failed", "partially_completed", "cancelled"].includes(item.status) ? (
                    <button
                      className="button-secondary"
                      onClick={async () => {
                        await apiPost(`/jobs/${item.id}/retry`, {});
                        await reload();
                      }}
                    >
                      <RotateCcw size={14} />
                      重试
                    </button>
                  ) : null}
                  {["queued", "running"].includes(item.status) ? (
                    <button
                      className="button-danger"
                      onClick={async () => {
                        await apiPost(`/jobs/${item.id}/cancel`, {});
                        await reload();
                      }}
                    >
                      <X size={14} />
                      取消
                    </button>
                  ) : null}
                </div>
              </div>
            ))}
          </section>
        ) : (
          <div className="empty-state">
            <Cog className="text-slate-300" size={28} />
            <p>暂无后台任务，触发解析或口径生成后可在此跟踪进度</p>
          </div>
        )}
      </div>
    </main>
  );
}

"use client";

import { Cog, RotateCcw, X } from "lucide-react";
import { useEffect, useState } from "react";

import { useProjectWorkspace } from "@/components/ProjectContext";
import { WorkspaceHeader } from "@/components/WorkspaceHeader";
import { AsyncActionButton } from "@/components/feedback/AsyncActionButton";
import { ConfirmDialog } from "@/components/feedback/ConfirmDialog";
import { JobProgressPanel } from "@/components/jobs/JobProgressPanel";
import { useAsyncAction } from "@/hooks/useAsyncAction";
import { BackgroundJobSummary, apiGet, apiPost } from "@/lib/api";

export default function Page() {
  const { projectId } = useProjectWorkspace();
  const [items, setItems] = useState<BackgroundJobSummary[]>([]);
  const [confirmation, setConfirmation] = useState<{ job: BackgroundJobSummary; kind: "retry" | "rerun" | "cancel" } | null>(null);
  const action = useAsyncAction<BackgroundJobSummary>({
    successMessage: (job) => job.status === "cancelled" ? "后台任务已取消" : "后台任务已重新提交"
  });

  async function reload() {
    if (projectId) setItems(await apiGet(`/jobs?project_id=${projectId}`));
  }

  useEffect(() => {
    void reload();
  }, [projectId]);
  useEffect(() => {
    if (!items.some((item) => ["queued", "running"].includes(item.status))) return;
    const timer = window.setInterval(() => void reload(), 3000);
    return () => window.clearInterval(timer);
  }, [items, projectId]);

  async function confirmAction() {
    if (!confirmation) return;
    const updated = await action.run(() => apiPost<BackgroundJobSummary>(`/jobs/${confirmation.job.id}/${confirmation.kind}`, {}));
    if (updated) {
      setConfirmation(null);
      await reload();
    }
  }

  const runningCount = items.filter((item) => item.status === "running").length;
  const queuedCount = items.filter((item) => item.status === "queued").length;
  const failedCount = items.filter((item) => ["failed", "partially_completed", "timed_out"].includes(item.status)).length;

  return (
    <main>
      <WorkspaceHeader title="后台任务" meta={`运行中 ${runningCount} · 排队 ${queuedCount} · 最近失败 ${failedCount}`} />
      <div className="mx-auto max-w-5xl p-4 lg:p-6">
        {items.length ? (
          <section className="space-y-3">
            {items.map((item) => (
              <div key={item.id}>
                <JobProgressPanel job={item} />
                <div className="mt-3 flex gap-2">
                  {["failed", "partially_completed", "cancelled"].includes(item.status) ? (
                    <AsyncActionButton
                      actionStatus={action.status}
                      className="button-secondary"
                      onClick={() => setConfirmation({ job: item, kind: "retry" })}
                    >
                      <RotateCcw size={14} />
                      重试
                    </AsyncActionButton>
                  ) : null}
                  {item.status === "completed" ? (
                    <AsyncActionButton
                      actionStatus={action.status}
                      className="button-secondary"
                      onClick={() => setConfirmation({ job: item, kind: "rerun" })}
                    >
                      <RotateCcw size={14} />
                      再次执行
                    </AsyncActionButton>
                  ) : null}
                  {["queued", "running"].includes(item.status) ? (
                    <AsyncActionButton
                      actionStatus={action.status}
                      className="button-danger"
                      onClick={() => setConfirmation({ job: item, kind: "cancel" })}
                    >
                      <X size={14} />
                      取消
                    </AsyncActionButton>
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
        <ConfirmDialog
          busy={action.isRunning}
          danger={confirmation?.kind === "cancel"}
          description={confirmation?.kind === "cancel"
            ? `将取消后台任务 #${confirmation?.job.id || ""}，已完成的处理结果和审计会保留。`
            : `将重新执行后台任务 #${confirmation?.job.id || ""}，会创建新的任务并保留原有审计记录。`}
          onCancel={() => setConfirmation(null)}
          onConfirm={confirmAction}
          open={Boolean(confirmation)}
          title={confirmation?.kind === "cancel" ? "确认取消任务？" : "确认重新执行？"}
        />
      </div>
    </main>
  );
}

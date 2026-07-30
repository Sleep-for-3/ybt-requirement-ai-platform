"use client";

import { FormEvent, useEffect, useState } from "react";
import { Check, RefreshCw, Upload } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";

import { WorkspaceHeader } from "@/components/WorkspaceHeader";
import { AsyncActionButton } from "@/components/feedback/AsyncActionButton";
import { ConfirmDialog } from "@/components/feedback/ConfirmDialog";
import { JobProgressPanel } from "@/components/jobs/JobProgressPanel";
import { useAsyncAction } from "@/hooks/useAsyncAction";
import { useJobPolling } from "@/hooks/useJobPolling";
import { BackgroundJobSummary, DataSource, MetadataSyncTask, apiGet, apiPost, uploadForm } from "@/lib/api";

type ImportPreview = { id: number; file_name: string; parse_summary_json: { row_count: number; sheet_count: number }; warnings_json: string[] };

function syncStatusBadge(status: string) {
  if (status === "success" || status === "completed") return "badge-success";
  if (status === "failed" || status === "error") return "badge-danger";
  if (status === "pending" || status === "running" || status === "processing") return "badge-warning";
  return "badge-neutral";
}

export default function DatasourceCatalogPage() {
  const id = Number(useParams<{ datasourceId: string }>().datasourceId);
  const [datasource, setDatasource] = useState<DataSource | null>(null);
  const [tasks, setTasks] = useState<MetadataSyncTask[]>([]);
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [message, setMessage] = useState("");
  const [activeJob, setActiveJob] = useState<BackgroundJobSummary | null>(null);
  const [confirmApply, setConfirmApply] = useState(false);
  const syncAction = useAsyncAction<MetadataSyncTask | BackgroundJobSummary>({
    successMessage: (result) => "job_type" in result
      ? result.deduplicated ? "相同元数据同步正在执行，已打开当前任务" : "元数据同步任务已提交"
      : "元数据同步完成"
  });
  const uploadAction = useAsyncAction<ImportPreview>({ successMessage: "数据字典已解析，请确认后应用" });
  const applyAction = useAsyncAction<unknown>({ successMessage: "数据字典已应用到目录" });
  const polledJob = useJobPolling(activeJob?.id, { initialJob: activeJob, onTerminal: reload });

  async function reload() {
    const [source, items] = await Promise.all([apiGet<DataSource>(`/datasources/${id}`), apiGet<MetadataSyncTask[]>(`/datasources/${id}/metadata-sync-tasks`)]);
    setDatasource(source);
    setTasks(items);
  }

  useEffect(() => {
    if (id) void reload();
  }, [id]);

  async function sync() {
    const result = await syncAction.run(() => apiPost<MetadataSyncTask | BackgroundJobSummary>(`/datasources/${id}/metadata-sync`, { sync_mode: "full", schema_names: [], include_views: true }));
    if (result) {
      if ("job_type" in result) {
        setActiveJob(result);
      } else {
      setMessage(`同步 ${result.status}：${result.table_count} 表 / ${result.column_count} 字段`);
      await reload();
      }
    }
  }

  async function upload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const result = await uploadAction.run(() => uploadForm<ImportPreview>(`/datasources/${id}/metadata-import/upload`, new FormData(event.currentTarget)));
    if (result) {
      setPreview(result);
      setMessage(`已解析 ${result.parse_summary_json.sheet_count} 个 sheet、${result.parse_summary_json.row_count} 行，请确认后应用`);
    }
  }

  async function applyImport() {
    if (!preview) return;
    const result = await applyAction.run(() => apiPost(`/metadata-imports/${preview.id}/apply`, {}));
    if (result !== undefined) {
      setMessage(`数据字典 ${preview.parse_summary_json.row_count} 行已应用`);
      setPreview(null);
      setConfirmApply(false);
      await reload();
    }
  }

  return (
    <main>
      <WorkspaceHeader title={`${datasource?.name || "数据源"} 元数据目录`} meta="元数据采集不读取业务表明细" />
      <div className="mx-auto max-w-5xl space-y-5 p-4 lg:p-6">
        <section className="panel flex flex-wrap items-center gap-3 p-4">
          <AsyncActionButton actionStatus={polledJob && ["queued", "running"].includes(polledJob.status) ? polledJob.status as "queued" | "running" : syncAction.status} className="button-primary" loadingText="正在提交同步…" onClick={() => void sync()}>
            <RefreshCw size={16} />
            同步元数据
          </AsyncActionButton>
          <Link className="button-secondary" href="/catalog">
            查看项目目录
          </Link>
          <form className="flex gap-2" onSubmit={upload}>
            <input accept=".xlsx" className="control" name="file" required type="file" />
            <AsyncActionButton actionStatus={uploadAction.status} className="button-secondary" loadingText="正在上传…" type="submit">
              <Upload size={16} />
              上传数据字典
            </AsyncActionButton>
          </form>
        </section>
        {polledJob ? <JobProgressPanel job={polledJob} resultHref="/catalog" /> : null}

        {message ? (
          <p className="rounded-lg border border-line bg-white px-3 py-2 text-sm text-slate-600">{message}</p>
        ) : null}

        {preview ? (
          <section className="panel">
            <div className="panel-header">
              <h2 className="text-[15px] font-semibold text-ink">数据字典预览</h2>
            </div>
            <div className="panel-body">
              <p className="text-sm text-slate-600">
                {preview.file_name} · {preview.parse_summary_json.sheet_count} sheet · {preview.parse_summary_json.row_count} 行
              </p>
              {preview.warnings_json.length ? (
                <p className="mt-2 text-sm text-gold-700">{preview.warnings_json.join("；")}</p>
              ) : null}
              <AsyncActionButton actionStatus={applyAction.status} className="button-primary mt-4" onClick={() => setConfirmApply(true)}>
                <Check size={16} />
                确认应用到目录
              </AsyncActionButton>
            </div>
          </section>
        ) : null}
        <ConfirmDialog
          busy={applyAction.isRunning}
          description={`将预览中的 ${preview?.parse_summary_json.row_count || 0} 行数据字典批量写入当前目录。`}
          onCancel={() => setConfirmApply(false)}
          onConfirm={applyImport}
          open={confirmApply}
          title="确认批量应用数据字典？"
        />

        <section className="panel overflow-hidden">
          <div className="panel-header">
            <h2 className="text-[15px] font-semibold text-ink">最近同步状态</h2>
          </div>
          {tasks.length ? (
            <>
              <div className="grid-head grid grid-cols-[130px_1fr]">
                <span>状态</span>
                <span>同步结果</span>
              </div>
              {tasks.map((task) => (
                <div className="grid-row grid grid-cols-[130px_1fr] items-center" key={task.id}>
                  <span>
                    <span className={syncStatusBadge(task.status)}>{task.status}</span>
                  </span>
                  <div>
                    <div className="text-slate-600">
                      {task.schema_count} schema / {task.table_count} 表 / {task.column_count} 字段
                    </div>
                    {task.warnings_json.length ? (
                      <div className="mt-1 text-xs text-gold-700">{task.warnings_json.join("；")}</div>
                    ) : null}
                  </div>
                </div>
              ))}
            </>
          ) : (
            <div className="m-4">
              <div className="empty-state">
                <RefreshCw className="text-slate-300" size={28} />
                <p>暂无同步记录，点击上方“同步元数据”发起首次采集</p>
              </div>
            </div>
          )}
        </section>
      </div>
    </main>
  );
}

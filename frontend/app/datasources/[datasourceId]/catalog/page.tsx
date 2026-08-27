"use client";

import { FormEvent, useEffect, useState } from "react";
import { Activity, Check, Clock3, Database, RefreshCw, Server, Upload } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";

import { WorkspaceHeader } from "@/components/WorkspaceHeader";
import { AsyncActionButton } from "@/components/feedback/AsyncActionButton";
import { ConfirmDialog } from "@/components/feedback/ConfirmDialog";
import { JobProgressPanel } from "@/components/jobs/JobProgressPanel";
import { useAsyncAction } from "@/hooks/useAsyncAction";
import { useJobPolling } from "@/hooks/useJobPolling";
import { BackgroundJobSummary, DataSource, MetadataDriftEvent, MetadataSyncTask, apiGet, apiPost, uploadForm } from "@/lib/api";

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
  const [drift, setDrift] = useState<MetadataDriftEvent[]>([]);
  const [syncMode, setSyncMode] = useState("incremental");
  const [selectedSchemas, setSelectedSchemas] = useState<string[]>([]);
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
    const configured = Array.isArray(source.connection_params_json?.schema_whitelist) ? source.connection_params_json.schema_whitelist.filter((item): item is string => typeof item === "string") : source.last_discovered_schemas_json || [];
    setSelectedSchemas((current) => current.length ? current : configured);
    setSyncMode(items.length ? "incremental" : "full");
    if (items[0]) setDrift(await apiGet<MetadataDriftEvent[]>(`/metadata-sync-tasks/${items[0].id}/drift?limit=200`));
    else setDrift([]);
  }

  useEffect(() => {
    if (id) void reload();
  }, [id]);

  async function sync() {
    const result = await syncAction.run(() => apiPost<MetadataSyncTask | BackgroundJobSummary>(`/datasources/${id}/metadata-sync`, { sync_mode: syncMode, schema_names: selectedSchemas, include_views: true }));
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
      <div className="mx-auto max-w-6xl space-y-5 p-4 lg:p-6">
        <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <HealthCard icon={<Activity size={17}/>} label="连接状态" value={datasource?.last_test_status || "未测试"} detail={datasource?.last_test_at ? `检查于 ${formatDate(datasource.last_test_at)}` : "尚未执行连接诊断"}/>
          <HealthCard icon={<Server size={17}/>} label="Connector / Driver" value={datasource?.db_type || "加载中"} detail={datasource?.last_database_version || "数据库版本待检测"}/>
          <HealthCard icon={<Database size={17}/>} label="纳管范围" value={`${selectedSchemas.length} 个 Schema`} detail={selectedSchemas.join("、") || "尚未选择纳管范围"}/>
          <HealthCard icon={<Clock3 size={17}/>} label="上次成功同步" value={lastSuccessfulTask(tasks) ? formatDate(lastSuccessfulTask(tasks)!.finished_at) : "暂无"} detail={lastSuccessfulTask(tasks) ? `${duration(lastSuccessfulTask(tasks)!)} · ${lastSuccessfulTask(tasks)!.table_count} 表 / ${lastSuccessfulTask(tasks)!.column_count} 字段` : "等待首次同步"}/>
        </section>
        <section className="panel p-4">
          <div className="flex flex-wrap items-end gap-3">
            <label className="text-sm font-medium text-ink">同步模式<select className="control mt-1.5 min-w-40" onChange={(event)=>setSyncMode(event.target.value)} value={syncMode}><option value="incremental">增量刷新</option><option value="full">全量对账</option><option value="selected_schemas">指定 Schema</option></select></label>
            <div className="min-w-0 flex-1"><p className="text-sm font-medium text-ink">纳管 Schema</p><div className="mt-1.5 flex max-h-28 flex-wrap gap-1.5 overflow-y-auto rounded-lg border border-line bg-slate-50 p-2">{(datasource?.last_discovered_schemas_json || []).map((schema)=><label className="badge-neutral cursor-pointer" key={schema}><input checked={selectedSchemas.includes(schema)} onChange={(event)=>setSelectedSchemas((current)=>event.target.checked?[...current,schema]:current.filter((item)=>item!==schema))} type="checkbox"/>{schema}</label>)}</div></div>
          <AsyncActionButton actionStatus={polledJob && ["queued", "running"].includes(polledJob.status) ? polledJob.status as "queued" | "running" : syncAction.status} className="button-primary" loadingText="正在提交同步…" onClick={() => void sync()}>
            <RefreshCw size={16} />
            {tasks.length ? "重新同步" : "首次同步"}
          </AsyncActionButton>
          <Link className="button-secondary" href="/catalog">
            查看项目目录
          </Link>
          <form className="flex flex-wrap gap-2" onSubmit={upload}>
            <input accept=".xlsx" className="control" name="file" required type="file" />
            <AsyncActionButton actionStatus={uploadAction.status} className="button-secondary" loadingText="正在上传…" type="submit">
              <Upload size={16} />
              上传数据字典
            </AsyncActionButton>
          </form>
          </div>
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
                      {task.schema_count} schema / {task.table_count} 表 / {task.column_count} 字段 · {duration(task)}
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
        <section className="panel overflow-hidden">
          <div className="panel-header"><div><h2 className="text-[15px] font-semibold text-ink">最近 Schema Drift</h2><p className="mt-1 text-xs text-slate-500">基于最近一次 Metadata Sync 的真实前后快照；rename 仅作为候选，不自动改写资产绑定。当前按最新顺序显示最多 200 条，完整事件已持久化并支持审计接口分页读取。</p></div></div>
          {drift.length ? <><div className="grid-head grid grid-cols-[90px_minmax(0,1fr)_minmax(0,1fr)]"><span>变化</span><span>资产</span><span>属性</span></div>{drift.map((event)=><div className="grid-row grid grid-cols-[90px_minmax(0,1fr)_minmax(0,1fr)] items-center gap-3" key={event.id}><span className={driftBadge(event.change_type)}>{driftLabel(event.change_type)}</span><div className="min-w-0"><p className="truncate font-medium text-ink">{event.entity_key}</p>{event.rename_candidate_key?<p className="mt-1 truncate text-xs text-gold-700">可能由 {event.rename_candidate_key} 重命名</p>:null}</div><p className="truncate text-xs text-slate-500">{event.changed_attributes_json.join("、") || "启用状态"}</p></div>)}</> : <div className="m-4"><div className="empty-state"><Activity className="text-slate-300" size={28}/><p>最近一次同步未检测到元数据变化</p></div></div>}
        </section>
      </div>
    </main>
  );
}

function HealthCard({icon,label,value,detail}:{icon:React.ReactNode;label:string;value:string;detail:string}) { return <article className="panel p-4"><p className="flex items-center gap-2 text-xs font-medium text-slate-500">{icon}{label}</p><p className="mt-2 truncate text-base font-semibold text-ink">{value}</p><p className="mt-1 line-clamp-2 text-xs text-slate-500">{detail}</p></article>; }
function lastSuccessfulTask(tasks:MetadataSyncTask[]) { return tasks.find((task)=>["completed","partially_completed","success"].includes(task.status)); }
function formatDate(value?:string|null) { return value ? new Intl.DateTimeFormat("zh-CN",{month:"2-digit",day:"2-digit",hour:"2-digit",minute:"2-digit"}).format(new Date(value)) : "暂无"; }
function duration(task:MetadataSyncTask) { if (!task.started_at || !task.finished_at) return task.status==="running"?"运行中":"时长未知"; const seconds=Math.max(0,Math.round((new Date(task.finished_at).getTime()-new Date(task.started_at).getTime())/1000)); return seconds<60?`${seconds} 秒`:`${Math.floor(seconds/60)} 分 ${seconds%60} 秒`; }
function driftBadge(type:string) { return type==="added"?"badge-success":type==="removed"?"badge-danger":"badge-warning"; }
function driftLabel(type:string) { return type==="added"?"新增":type==="removed"?"移除":"变更"; }

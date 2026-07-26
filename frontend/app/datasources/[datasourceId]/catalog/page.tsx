"use client";

import { FormEvent, useEffect, useState } from "react";
import { Check, RefreshCw, Upload } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";

import { WorkspaceHeader } from "@/components/WorkspaceHeader";
import { DataSource, MetadataSyncTask, apiGet, apiPost, uploadForm } from "@/lib/api";

type ImportPreview = { id: number; file_name: string; parse_summary_json: { row_count: number; sheet_count: number }; warnings_json: string[] };

export default function DatasourceCatalogPage() {
  const id = Number(useParams<{ datasourceId: string }>().datasourceId);
  const [datasource, setDatasource] = useState<DataSource | null>(null);
  const [tasks, setTasks] = useState<MetadataSyncTask[]>([]);
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [message, setMessage] = useState("");

  async function reload() {
    const [source, items] = await Promise.all([apiGet<DataSource>(`/datasources/${id}`), apiGet<MetadataSyncTask[]>(`/datasources/${id}/metadata-sync-tasks`)]);
    setDatasource(source); setTasks(items);
  }
  useEffect(() => { if (id) void reload(); }, [id]);

  async function sync() {
    try {
      const result = await apiPost<MetadataSyncTask>(`/datasources/${id}/metadata-sync`, { sync_mode: "full", schema_names: [], include_views: true });
      setMessage(`同步 ${result.status}：${result.table_count} 表 / ${result.column_count} 字段`); await reload();
    } catch (error) { setMessage(error instanceof Error ? error.message : "同步失败"); }
  }

  async function upload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    try {
      const result = await uploadForm<ImportPreview>(`/datasources/${id}/metadata-import/upload`, new FormData(event.currentTarget));
      setPreview(result); setMessage(`已解析 ${result.parse_summary_json.sheet_count} 个 sheet、${result.parse_summary_json.row_count} 行，请确认后应用`);
    } catch (error) { setMessage(error instanceof Error ? error.message : "导入失败"); }
  }

  async function applyImport() {
    if (!preview) return;
    try {
      await apiPost(`/metadata-imports/${preview.id}/apply`, {}); setMessage(`数据字典 ${preview.parse_summary_json.row_count} 行已应用`); setPreview(null);
    } catch (error) { setMessage(error instanceof Error ? error.message : "应用失败"); }
  }

  return <main>
    <WorkspaceHeader title={`${datasource?.name || "数据源"} 元数据目录`} meta="元数据采集不读取业务表明细" />
    <div className="mx-auto max-w-5xl space-y-5 p-6">
      <section className="panel flex flex-wrap gap-3 p-4"><button className="button-primary" onClick={sync}><RefreshCw size={16} />同步元数据</button><Link className="button-secondary" href="/catalog">查看项目目录</Link><form className="flex gap-2" onSubmit={upload}><input accept=".xlsx" className="control" name="file" required type="file" /><button className="button-secondary"><Upload size={16} />上传数据字典</button></form></section>
      {message ? <p className="text-sm text-slate-600">{message}</p> : null}
      {preview ? <section className="panel p-4"><h2 className="font-semibold">数据字典预览</h2><p className="mt-2 text-sm">{preview.file_name} · {preview.parse_summary_json.sheet_count} sheet · {preview.parse_summary_json.row_count} 行</p>{preview.warnings_json.length ? <p className="mt-2 text-sm text-amber-700">{preview.warnings_json.join("；")}</p> : null}<button className="button-primary mt-3" onClick={applyImport}><Check size={16} />确认应用到目录</button></section> : null}
      <section className="panel overflow-hidden"><div className="border-b p-3 font-semibold">最近同步状态</div>{tasks.map((task) => <div className="border-b p-3 text-sm" key={task.id}><strong>{task.status}</strong> · {task.schema_count} schema / {task.table_count} 表 / {task.column_count} 字段{task.warnings_json.length ? <div className="text-amber-700">{task.warnings_json.join("；")}</div> : null}</div>)}</section>
    </div>
  </main>;
}

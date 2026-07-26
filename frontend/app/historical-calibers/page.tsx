"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Upload } from "lucide-react";

import { useProjectWorkspace } from "@/components/ProjectContext";
import { WorkspaceHeader } from "@/components/WorkspaceHeader";
import { HistoricalCaliberImport, apiGet, uploadForm } from "@/lib/api";
import { useProjectPermissions } from "@/lib/project-permissions";

export default function Page() {
  const { projectId } = useProjectWorkspace(); const permissions = useProjectPermissions(projectId);
  const [items, setItems] = useState<HistoricalCaliberImport[]>([]); const [file, setFile] = useState<File | null>(null); const [documentType, setDocumentType] = useState("full_package"); const [message, setMessage] = useState("");
  async function load() { if (!projectId) return; try { setItems(await apiGet(`/projects/${projectId}/historical-calibers`)); } catch (error) { setMessage(readError(error)); } }
  useEffect(() => { void load(); }, [projectId]);
  async function upload() { if (!projectId || !file) return; const form = new FormData(); form.append("file", file); form.append("import_name", file.name.replace(/\.xlsx$/i, "")); form.append("document_type", documentType); try { await uploadForm(`/projects/${projectId}/historical-calibers/upload`, form); setMessage("历史口径已导入，列表已刷新。"); setFile(null); await load(); } catch (error) { setMessage(readError(error)); } }
  return <main><WorkspaceHeader title="历史口径库" meta="持久导入、人工匹配与不覆盖复用" /><div className="mx-auto max-w-6xl space-y-5 p-6">
    {permissions.can("historical_caliber.import") ? <section className="panel grid gap-3 p-4 md:grid-cols-[1fr_240px_auto]"><input className="control" type="file" accept=".xlsx" onChange={event => setFile(event.target.files?.[0] || null)} /><select className="control" value={documentType} onChange={event => setDocumentType(event.target.value)}><option value="full_package">完整历史交付包</option><option value="business_traceability">业务口径</option><option value="source_to_mart">来源到集市</option><option value="mart_to_ybt">集市到一表通</option></select><button className="button-primary" disabled={!file} onClick={upload}><Upload size={15} />导入历史口径</button></section> : null}
    {message ? <p className="panel p-3 text-sm">{message}</p> : null}
    <section className="grid gap-4 md:grid-cols-2">{items.map(item => <Link className="panel p-4 hover:border-pine" href={`/historical-calibers/${item.id}`} key={item.id}><div className="flex justify-between"><b>{item.import_name}</b><span className="text-xs">{item.status}</span></div><p className="mt-2 text-sm">{item.document_type}</p><div className="mt-3 grid grid-cols-3 gap-2 text-xs text-slate-500"><span>记录 {item.parse_summary_json.item_count || 0}</span><span>已匹配 {item.parse_summary_json.matched_count || 0}</span><span>歧义 {item.parse_summary_json.ambiguous_count || 0}</span></div><p className="mt-2 text-xs text-slate-500">{item.created_at ? new Date(item.created_at).toLocaleString() : ""}</p></Link>)}{!items.length ? <p className="panel p-6 text-sm text-slate-500">当前项目还没有历史导入记录。</p> : null}</section>
  </div></main>;
}

function readError(error:unknown) { return error instanceof Error ? error.message : "操作失败"; }

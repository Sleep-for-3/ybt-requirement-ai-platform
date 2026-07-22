"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { AlertTriangle, CheckCircle2, Upload } from "lucide-react";

import { WorkspaceHeader } from "@/components/WorkspaceHeader";
import { useProjectWorkspace } from "@/components/ProjectContext";
import { DeliverableTemplate, apiGet, uploadForm } from "@/lib/api";
import { useProjectPermissions } from "@/lib/project-permissions";

export default function Page() {
  const { projectId } = useProjectWorkspace();
  const permissions = useProjectPermissions(projectId);
  const [items, setItems] = useState<DeliverableTemplate[]>([]);
  const [file, setFile] = useState<File | null>(null);
  const [message, setMessage] = useState("");

  async function load() {
    if (!projectId) return;
    try { setItems(await apiGet(`/projects/${projectId}/deliverable-templates`)); }
    catch (error) { setMessage(error instanceof Error ? error.message : "模板加载失败"); }
  }
  useEffect(() => { void load(); }, [projectId]);

  async function upload() {
    if (!projectId || !file) return;
    const form = new FormData();
    form.append("file", file);
    form.append("template_name", file.name.replace(/\.xlsx$/i, ""));
    form.append("template_type", "full_delivery_package");
    try {
      await uploadForm(`/projects/${projectId}/deliverable-templates/upload`, form);
      setFile(null); setMessage("新模板已上传，请完成业务区域配置、校验并激活。"); await load();
    } catch (error) { setMessage(error instanceof Error ? error.message : "上传失败"); }
  }

  return <main>
    <WorkspaceHeader title="正式交付模板" meta="版本化配置、严格校验与激活" />
    <div className="mx-auto max-w-6xl space-y-5 p-6">
      {permissions.can("template.manage") ? <section className="panel flex flex-wrap items-center gap-3 p-4">
        <input className="control max-w-xl" type="file" accept=".xlsx" onChange={event => setFile(event.target.files?.[0] || null)} />
        <button className="button-primary" disabled={!file} onClick={upload}><Upload size={16} />上传新模板</button>
        <span className="text-xs text-slate-500">上传后不会自动激活，必须先完成全部必需区域并通过校验。</span>
      </section> : <p className="panel p-3 text-sm text-slate-500">当前角色为 {permissions.role || "只读角色"}，模板配置仅供查看。</p>}
      {message ? <p className="panel p-3 text-sm">{message}</p> : null}
      <section className="grid gap-4 md:grid-cols-2">
        {items.map(item => <Link className="panel p-4 hover:border-pine" href={`/deliverable-templates/${item.id}`} key={item.id}>
          <div className="flex items-start justify-between gap-4"><div><b>{item.template_name}</b><p className="mt-1 text-xs text-slate-500">{item.template_type}</p></div><span className="rounded bg-slate-100 px-2 py-1 text-xs">v{item.current_version_no}</span></div>
          <div className="mt-4 grid grid-cols-2 gap-2 text-sm"><span>版本状态：{statusLabel(item.current_version_status)}</span><span>默认模板：{item.is_default ? "是" : "否"}</span><span>错误：{item.validation_error_count || 0}</span><span>告警：{item.validation_warning_count || 0}</span></div>
          <div className="mt-3 flex items-center gap-2 text-xs">{item.current_version_status === "active" ? <><CheckCircle2 className="text-emerald-600" size={15} />可用于正式交付包</> : <><AlertTriangle className="text-amber-600" size={15} />待配置或待激活</>}</div>
        </Link>)}
        {!items.length ? <p className="panel p-6 text-sm text-slate-500">当前项目尚无正式交付模板。</p> : null}
      </section>
    </div>
  </main>;
}

function statusLabel(status?: string | null) {
  return ({ parsed: "待配置", configured: "已配置", active: "已激活" } as Record<string, string>)[status || ""] || status || "未知";
}

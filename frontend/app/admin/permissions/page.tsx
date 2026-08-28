"use client";

import { Check, Code2, ShieldCheck } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { WorkspaceHeader } from "@/components/WorkspaceHeader";
import { PageState } from "@/components/feedback/PageState";
import { apiGet } from "@/lib/api";
import { groupPermissions, institutionRoleLabel, permissionLanguage, projectRoleDescription, projectRoleLabel } from "@/lib/permission-language.mjs";

type Matrix = { institution_roles: string[]; project_roles: Record<string, string[]> };
type MatrixTab = "institution" | "project" | "dictionary";
const tabs: Array<{ key: MatrixTab; label: string }> = [{ key: "institution", label: "机构角色" }, { key: "project", label: "项目角色" }, { key: "dictionary", label: "权限字典" }];

export default function Page() {
  const [data, setData] = useState<Matrix | null>(null);
  const [error, setError] = useState("");
  const [tab, setTab] = useState<MatrixTab>("project");
  useEffect(() => { apiGet<Matrix>("/admin/permissions").then(setData).catch((cause) => setError(cause instanceof Error ? cause.message : "权限模型加载失败")); }, []);
  const permissionCodes = useMemo(() => Array.from(new Set(Object.values(data?.project_roles || {}).flat())).sort(), [data]);
  return <main><WorkspaceHeader title="角色与权限" meta="统一 PermissionService 的产品化只读视图" />
    <div className="mx-auto max-w-6xl space-y-4 p-4 lg:p-6">
      <div aria-label="权限视图" className="inline-flex rounded-lg border border-line bg-white p-1" role="tablist">{tabs.map((item) => <button aria-selected={tab === item.key} className={`rounded-md px-4 py-2 text-sm font-medium ${tab === item.key ? "bg-pine-700 text-white" : "text-slate-600 hover:bg-slate-50"}`} key={item.key} onClick={() => setTab(item.key)} role="tab" type="button">{item.label}</button>)}</div>
      {error ? <PageState kind="error" title="角色与权限加载失败" description={error} /> : null}
      {!data && !error ? <PageState kind="loading" title="正在加载权限模型" description="正在读取服务端统一权限定义。" /> : null}
      {data && tab === "institution" ? <section className="grid gap-4 sm:grid-cols-2">{data.institution_roles.map((role) => <article className="panel p-5" key={role}><div className="flex items-start gap-3"><span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-pine-50 text-pine-700"><ShieldCheck size={18} /></span><div><h2 className="text-sm font-semibold text-ink">{institutionRoleLabel(role)}</h2><p className="mt-1 text-sm text-slate-500">{permissionLanguage.institutionRoles[role]?.description || "该角色尚未配置产品说明"}</p><details className="mt-3 text-xs text-slate-500"><summary className="cursor-pointer font-medium text-pine-700">查看技术标识</summary><code className="mt-2 block rounded bg-slate-50 px-2 py-1">{role}</code></details></div></div></article>)}</section> : null}
      {data && tab === "project" ? <section className="space-y-4">{Object.entries(data.project_roles).map(([role, permissions]) => <article className="panel overflow-hidden" key={role}><div className="panel-header flex flex-wrap items-start justify-between gap-3"><div><h2 className="text-base font-semibold text-ink">{projectRoleLabel(role)}</h2><p className="mt-1 text-sm text-slate-500">{projectRoleDescription(role)}</p></div><span className="badge-info">拥有 {permissions.length} 项权限</span></div><div className="grid gap-5 p-5 md:grid-cols-2 lg:grid-cols-3">{groupPermissions(permissions).map((group) => <div key={group.group}><h3 className="mb-2 text-xs font-semibold text-slate-500">{group.group}</h3><ul className="space-y-2">{group.permissions.map((permission) => <li className="flex items-start gap-2 text-sm text-slate-700" key={permission.code}><Check className="mt-0.5 shrink-0 text-pine-600" size={15} /><span>{permission.label}{!permission.configured ? <span className="ml-2 text-coral-600">未配置中文名称</span> : null}</span></li>)}</ul></div>)}</div><details className="border-t border-line px-5 py-3 text-xs text-slate-500"><summary className="flex cursor-pointer items-center gap-2 font-medium text-pine-700"><Code2 size={14} />查看技术标识</summary><div className="mt-3 space-y-2"><code className="block rounded bg-slate-50 px-2 py-1">{role}</code><div className="flex flex-wrap gap-1.5">{permissions.map((permission) => <code className="rounded bg-slate-50 px-2 py-1" key={permission}>{permission}</code>)}</div></div></details></article>)}</section> : null}
      {data && tab === "dictionary" ? <section className="panel overflow-hidden"><div className="grid-head grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)]"><span>产品名称</span><span>业务域</span></div>{groupPermissions(permissionCodes).flatMap((group) => group.permissions.map((permission) => <div className="grid-row grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)] items-start gap-3" key={permission.code}><div><strong className="text-sm text-ink">{permission.label}</strong>{!permission.configured ? <p className="text-xs text-coral-600">未配置中文名称</p> : null}<details className="mt-1 text-xs text-slate-500"><summary className="cursor-pointer text-pine-700">查看技术标识</summary><code>{permission.code}</code></details></div><span className="text-sm text-slate-600">{group.group}</span></div>))}</section> : null}
    </div>
  </main>;
}

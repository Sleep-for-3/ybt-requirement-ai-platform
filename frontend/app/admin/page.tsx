"use client";

import { Activity, Building2, ShieldCheck, Users } from "lucide-react";
import Link from "next/link";

import { WorkspaceHeader } from "@/components/WorkspaceHeader";
import { useAdminCapabilities } from "@/components/admin/AdminShell";

const destinations = [
  { href: "/admin/institutions", title: "机构管理", description: "查看机构边界与运行状态", icon: Building2, capability: "can_view_admin" },
  { href: "/admin/users", title: "用户管理", description: "管理机构用户与角色分配", icon: Users, capability: "can_manage_users" },
  { href: "/admin/permissions", title: "角色与权限", description: "查看统一 PermissionService 权限模型", icon: ShieldCheck, capability: "can_view_permission_matrix" },
  { href: "/admin/health", title: "平台健康", description: "检查核心服务与数据基础设施", icon: Activity, capability: "can_view_platform_health" },
] as const;

export default function AdminOverviewPage() {
  const capabilities = useAdminCapabilities();
  return <main><WorkspaceHeader title="系统管理中心" meta="机构、用户、权限与平台运行状态" />
    <div className="mx-auto grid max-w-6xl gap-4 p-4 sm:grid-cols-2 lg:p-6">
      {destinations.filter((item) => capabilities[item.capability]).map((item) => { const Icon = item.icon; return <Link className="panel flex items-start gap-4 p-5 transition hover:border-pine-200 hover:shadow-md" href={item.href} key={item.href}><span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-pine-50 text-pine-700"><Icon size={20} /></span><span><strong className="text-sm text-ink">{item.title}</strong><span className="mt-1 block text-sm text-slate-500">{item.description}</span></span></Link>; })}
    </div>
  </main>;
}

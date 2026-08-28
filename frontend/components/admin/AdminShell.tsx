"use client";

import { Activity, Building2, LayoutDashboard, ShieldCheck, Users } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { createContext, useContext, useEffect, useState } from "react";

import { PageState } from "@/components/feedback/PageState";
import { apiGet } from "@/lib/api";
import { AuthCapabilities, AuthMe, NO_CAPABILITIES } from "@/lib/auth-capabilities";

const AdminCapabilityContext = createContext<AuthCapabilities>(NO_CAPABILITIES);

const adminItems = [
  { href: "/admin", label: "管理概览", icon: LayoutDashboard, capability: "can_view_admin" },
  { href: "/admin/institutions", label: "机构管理", icon: Building2, capability: "can_view_admin" },
  { href: "/admin/users", label: "用户管理", icon: Users, capability: "can_manage_users" },
  { href: "/admin/permissions", label: "角色与权限", icon: ShieldCheck, capability: "can_view_permission_matrix" },
  { href: "/admin/health", label: "平台健康", icon: Activity, capability: "can_view_platform_health" },
] as const;

export function useAdminCapabilities() {
  return useContext(AdminCapabilityContext);
}

export function AdminShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [auth, setAuth] = useState<AuthMe | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    apiGet<AuthMe>("/auth/me").then((nextAuth) => {
      if (!active) return;
      setAuth(nextAuth);
      setError("");
    }).catch((cause) => {
      if (active) setError(cause instanceof Error ? cause.message : "无法验证管理权限");
    });
    return () => { active = false; };
  }, []);

  if (error) {
    return <main className="p-6"><PageState kind="error" title="系统管理权限校验失败" description={error} /></main>;
  }
  if (!auth) {
    return <main className="p-6"><PageState kind="loading" title="正在验证管理权限" description="正在读取服务端授权能力。" /></main>;
  }
  if (!auth.capabilities.can_view_admin) {
    return <main className="p-6"><PageState kind="forbidden" title="没有系统管理权限" description="此地址仅对具备管理能力的账号开放。" /></main>;
  }

  const requiredCapability = pathname.startsWith("/admin/permissions") ? "can_view_permission_matrix"
    : pathname.startsWith("/admin/health") || pathname.startsWith("/admin/system-health") ? "can_view_platform_health"
      : pathname.startsWith("/admin/users") ? "can_manage_users" : "can_view_admin";
  if (!auth.capabilities[requiredCapability]) {
    return <main className="p-6"><PageState kind="forbidden" title="没有此管理页面的权限" description="系统已根据服务端授权能力阻止访问此地址。" /></main>;
  }

  const visibleItems = adminItems.filter((item) => auth.capabilities[item.capability]);
  return (
    <AdminCapabilityContext.Provider value={auth.capabilities}>
      <nav aria-label="系统管理二级导航" className="border-b border-line bg-white px-4 lg:px-6">
        <div className="flex min-h-12 flex-wrap items-center gap-1">
          {visibleItems.map((item) => {
            const active = pathname === item.href || (item.href !== "/admin" && pathname.startsWith(`${item.href}/`));
            const Icon = item.icon;
            return <Link aria-current={active ? "page" : undefined} className={`flex h-10 items-center gap-2 border-b-2 px-3 text-sm font-medium transition ${active ? "border-pine-600 text-pine-700" : "border-transparent text-slate-500 hover:text-ink"}`} href={item.href} key={item.href}><Icon size={16} />{item.label}</Link>;
          })}
        </div>
      </nav>
      {children}
    </AdminCapabilityContext.Provider>
  );
}

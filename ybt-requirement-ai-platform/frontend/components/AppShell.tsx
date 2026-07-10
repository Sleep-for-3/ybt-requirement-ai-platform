"use client";

import { Building2, Database, FileOutput, FileSpreadsheet, FolderKanban, Layers3, ListTree, TableProperties, Workflow } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

const NAV = [
  { href: "/projects", label: "项目", icon: FolderKanban },
  { href: "/templates", label: "一表通模板", icon: FileSpreadsheet },
  { href: "/traceability-templates", label: "历史口径", icon: TableProperties },
  { href: "/business-systems", label: "业务系统", icon: Building2 },
  { href: "/mart", label: "监管集市", icon: Layers3 },
  { href: "/fields", label: "字段场景", icon: ListTree },
  { href: "/export", label: "Excel 导出", icon: FileOutput },
  { href: "/datasources", label: "数据源", icon: Database },
  { href: "/tasks", label: "安全查询", icon: Workflow },
];

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  return (
    <div className="min-h-screen bg-mist">
      <header className="sticky top-0 z-40 border-b border-line bg-white">
        <div className="mx-auto flex min-h-14 max-w-[1680px] items-center gap-5 px-4 lg:px-6">
          <Link className="shrink-0 font-semibold text-ink" href="/projects">一表通口径平台</Link>
          <nav className="flex min-w-0 flex-1 items-center gap-1 overflow-x-auto py-2">
            {NAV.map((item) => {
              const active = pathname === item.href || pathname.startsWith(`${item.href}/`);
              const Icon = item.icon;
              return (
                <Link
                  className={`inline-flex h-9 shrink-0 items-center gap-2 rounded-md px-3 text-sm font-medium ${active ? "bg-pine text-white" : "text-slate-600 hover:bg-mist hover:text-ink"}`}
                  href={item.href}
                  key={item.href}
                >
                  <Icon size={16} />
                  {item.label}
                </Link>
              );
            })}
          </nav>
          <Link className="button-secondary shrink-0" href="/legacy">综合工作台</Link>
        </div>
      </header>
      {children}
    </div>
  );
}

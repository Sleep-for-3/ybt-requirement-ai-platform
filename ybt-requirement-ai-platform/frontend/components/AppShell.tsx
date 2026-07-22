"use client";

import { Bell, BrainCircuit, Building2, ChartNoAxesCombined, ClipboardCheck, Database, FileOutput, FileSpreadsheet, FolderKanban, GitBranch, History, Layers3, LibraryBig, ListChecks, ListTree, PackageCheck, TableProperties, Workflow } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

import { ProjectProvider, ProjectSelector, useProjectWorkspace } from "@/components/ProjectContext";
import { apiGet } from "@/lib/api";

const NAV = [
  { href: "/projects", label: "项目", icon: FolderKanban },
  { href: "/templates", label: "一表通模板", icon: FileSpreadsheet },
  { href: "/traceability-templates", label: "历史口径", icon: TableProperties },
  { href: "/business-systems", label: "业务系统", icon: Building2 },
  { href: "/mart", label: "监管集市", icon: Layers3 },
  { href: "/fields", label: "字段场景", icon: ListTree },
  { href: "/export", label: "Excel 导出", icon: FileOutput },
  { href: "/deliverables", label: "正式交付", icon: PackageCheck },
  { href: "/deliverable-templates", label: "交付模板", icon: FileSpreadsheet },
  { href: "/historical-calibers", label: "历史口径库", icon: History },
  { href: "/questions", label: "待确认问题", icon: ListChecks },
  { href: "/datasources", label: "数据源", icon: Database },
  { href: "/catalog", label: "数据目录", icon: LibraryBig },
  { href: "/lineage", label: "脚本血缘", icon: GitBranch },
  { href: "/knowledge", label: "知识库", icon: BrainCircuit },
  { href: "/evaluations", label: "RAG 评测", icon: ChartNoAxesCombined },
  { href: "/tasks", label: "安全查询", icon: Workflow },
  { href: "/review-tasks", label: "我的待办", icon: ClipboardCheck },
  { href: "/notifications", label: "通知", icon: Bell },
  { href: "/jobs", label: "后台任务", icon: History },
  { href: "/audit", label: "审计", icon: History },
];

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  if (pathname === "/login") return <>{children}</>;
  return <ProjectProvider><ShellContent>{children}</ShellContent></ProjectProvider>;
}

function ShellContent({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { selectedProject } = useProjectWorkspace();
  const [user, setUser] = useState<{display_name?:string|null;username:string}|null>(null);
  useEffect(()=>{apiGet<{display_name?:string|null;username:string}>("/auth/me").then(setUser).catch(()=>setUser(null));},[]);
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
          <ProjectSelector className="w-48 shrink-0" />
          <div className="hidden shrink-0 text-right text-xs text-slate-500 xl:block"><div>{selectedProject?.bank_name||"当前银行"}</div><div className="font-medium text-ink">{user?.display_name||user?.username||"未登录"}</div></div>
          <Link className="button-secondary shrink-0" href="/admin/institutions">管理</Link>
          <Link className="button-secondary shrink-0" href="/legacy">综合工作台</Link>
        </div>
      </header>
      {children}
    </div>
  );
}

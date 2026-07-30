"use client";

import {
  Bell,
  BrainCircuit,
  Building2,
  ChartNoAxesCombined,
  ClipboardCheck,
  Database,
  FileOutput,
  FileSpreadsheet,
  FolderKanban,
  GitBranch,
  History,
  Landmark,
  Layers3,
  LayoutGrid,
  LibraryBig,
  ListChecks,
  ListTree,
  LogOut,
  Menu,
  PackageCheck,
  ScrollText,
  Settings2,
  ShieldCheck,
  TableProperties,
  Workflow,
  X
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { ProjectProvider, ProjectSelector, useProjectWorkspace } from "@/components/ProjectContext";
import { BackgroundJobSummary, apiGet, clearSession } from "@/lib/api";

type NavItem = {
  href: string;
  label: string;
  icon: typeof Bell;
  /** Prefix used for the active check when it differs from href. */
  match?: string;
};

type NavGroup = { label: string; items: NavItem[] };

const NAV_GROUPS: NavGroup[] = [
  {
    label: "工作台",
    items: [
      { href: "/projects", label: "项目", icon: FolderKanban },
      { href: "/review-tasks", label: "我的待办", icon: ClipboardCheck },
      { href: "/notifications", label: "通知", icon: Bell }
    ]
  },
  {
    label: "需求与口径",
    items: [
      { href: "/templates", label: "一表通模板", icon: FileSpreadsheet },
      { href: "/fields", label: "字段场景", icon: ListTree },
      { href: "/questions", label: "待确认问题", icon: ListChecks },
      { href: "/traceability-templates", label: "历史口径", icon: TableProperties },
      { href: "/historical-calibers", label: "历史口径库", icon: History }
    ]
  },
  {
    label: "数据资产",
    items: [
      { href: "/business-systems", label: "业务系统", icon: Building2 },
      { href: "/mart", label: "监管集市", icon: Layers3 },
      { href: "/datasources", label: "数据源", icon: Database },
      { href: "/catalog", label: "数据目录", icon: LibraryBig },
      { href: "/lineage", label: "脚本血缘", icon: GitBranch }
    ]
  },
  {
    label: "智能与知识",
    items: [
      { href: "/knowledge", label: "知识库", icon: BrainCircuit },
      { href: "/evaluations", label: "RAG 评测", icon: ChartNoAxesCombined },
      { href: "/tasks", label: "安全查询", icon: Workflow }
    ]
  },
  {
    label: "交付与验收",
    items: [
      { href: "/export", label: "Excel 导出", icon: FileOutput },
      { href: "/deliverables", label: "正式交付", icon: PackageCheck },
      { href: "/deliverable-templates", label: "交付模板", icon: FileSpreadsheet },
      { href: "/uat", label: "UAT 验收", icon: ShieldCheck }
    ]
  },
  {
    label: "系统",
    items: [
      { href: "/jobs", label: "后台任务", icon: History },
      { href: "/audit", label: "审计", icon: ScrollText },
      { href: "/admin/institutions", label: "管理", icon: Settings2, match: "/admin" },
      { href: "/legacy", label: "综合工作台", icon: LayoutGrid }
    ]
  }
];

function isActive(pathname: string, item: NavItem) {
  const prefix = item.match || item.href;
  return pathname === prefix || pathname.startsWith(`${prefix}/`);
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  if (pathname === "/login") return <>{children}</>;
  return <ProjectProvider><ShellContent>{children}</ShellContent></ProjectProvider>;
}

function SidebarNav({ pathname, runningJobs = 0 }: { pathname: string; runningJobs?: number }) {
  return (
    <nav className="flex-1 space-y-4 overflow-y-auto px-3 pb-4">
      {NAV_GROUPS.map((group) => (
        <div key={group.label}>
          <div className="px-3 pb-1.5 pt-2 text-[11px] font-medium tracking-wider text-emerald-100/40">{group.label}</div>
          <div className="space-y-0.5">
            {group.items.map((item) => {
              const active = isActive(pathname, item);
              const Icon = item.icon;
              return (
                <Link
                  className={`group flex items-center gap-2.5 rounded-lg px-3 py-2 text-[13px] font-medium transition ${
                    active ? "bg-white/[0.09] text-white" : "text-emerald-50/65 hover:bg-white/[0.05] hover:text-white"
                  }`}
                  href={item.href}
                  key={item.href}
                >
                  <Icon className={active ? "text-pine-300" : "text-emerald-100/40 transition group-hover:text-emerald-100/75"} size={16} />
                  {item.label}
                  {item.href === "/jobs" && runningJobs > 0 ? (
                    <span className="ml-auto min-w-5 rounded-full bg-amber-300 px-1.5 text-center text-[10px] font-bold leading-5 text-amber-950" aria-label={`${runningJobs} 个活动任务`}>
                      {runningJobs > 99 ? "99+" : runningJobs}
                    </span>
                  ) : null}
                </Link>
              );
            })}
          </div>
        </div>
      ))}
    </nav>
  );
}

function SidebarBrand() {
  return (
    <Link className="flex items-center gap-3 px-5 pb-4 pt-5" href="/projects">
      <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-pine-500 text-white shadow-md shadow-pine-950/40">
        <Landmark size={18} />
      </span>
      <span className="min-w-0">
        <span className="block truncate text-sm font-semibold text-white">一表通口径平台</span>
        <span className="block text-[11px] text-emerald-100/50">字段级口径 · 智能辅助</span>
      </span>
    </Link>
  );
}

function SidebarFooter() {
  return (
    <div className="border-t border-white/5 px-5 py-3 text-[11px] leading-relaxed text-emerald-100/35">
      仅限脱敏模拟数据环境
    </div>
  );
}

function ShellContent({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const { projectId, selectedProject } = useProjectWorkspace();
  const [user, setUser] = useState<{ display_name?: string | null; username: string } | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [runningJobs, setRunningJobs] = useState(0);

  useEffect(() => {
    apiGet<{ display_name?: string | null; username: string }>("/auth/me").then(setUser).catch(() => setUser(null));
  }, []);

  useEffect(() => {
    setDrawerOpen(false);
  }, [pathname]);
  useEffect(() => {
    if (!projectId) {
      setRunningJobs(0);
      return;
    }
    let active = true;
    async function loadJobCount() {
      try {
        const jobs = await apiGet<BackgroundJobSummary[]>(`/jobs?project_id=${projectId}`);
        if (active) setRunningJobs(jobs.filter((job) => ["queued", "running"].includes(job.status)).length);
      } catch {
        // 导航计数失败不打断当前页面，任务中心仍可手工打开。
      }
    }
    void loadJobCount();
    const timer = window.setInterval(() => void loadJobCount(), 5000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [projectId]);

  const displayName = user?.display_name || user?.username || "未登录";

  function logout() {
    clearSession();
    router.replace("/login");
  }

  return (
    <div className="flex min-h-screen bg-mist">
      <aside className="sticky top-0 hidden h-screen w-60 shrink-0 flex-col bg-gradient-to-b from-[#102620] to-[#0a1b16] lg:flex">
        <SidebarBrand />
        <SidebarNav pathname={pathname} runningJobs={runningJobs} />
        <SidebarFooter />
      </aside>

      {drawerOpen ? (
        <div className="fixed inset-0 z-50 lg:hidden">
          <div aria-hidden className="absolute inset-0 bg-slate-950/55 backdrop-blur-sm" onClick={() => setDrawerOpen(false)} />
          <aside className="absolute inset-y-0 left-0 flex w-64 flex-col bg-gradient-to-b from-[#102620] to-[#0a1b16] shadow-pop">
            <div className="flex items-center justify-between pr-3">
              <SidebarBrand />
              <button aria-label="关闭导航" className="button-ghost h-9 w-9 px-0 text-emerald-100/70 hover:bg-white/10 hover:text-white" onClick={() => setDrawerOpen(false)} type="button">
                <X size={18} />
              </button>
            </div>
            <SidebarNav pathname={pathname} runningJobs={runningJobs} />
            <SidebarFooter />
          </aside>
        </div>
      ) : null}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-40 border-b border-line bg-white/90 backdrop-blur">
          <div className="flex h-14 items-center gap-3 px-4 lg:px-6">
            <button aria-label="打开导航" className="button-ghost h-9 w-9 px-0 lg:hidden" onClick={() => setDrawerOpen(true)} type="button">
              <Menu size={18} />
            </button>
            <div className="hidden min-w-0 items-baseline gap-2 md:flex">
              <span className="truncate text-sm font-medium text-ink">{selectedProject?.bank_name || "未选择机构"}</span>
              {selectedProject ? <span className="truncate text-xs text-slate-400">{selectedProject.name}</span> : null}
            </div>
            <div className="flex-1" />
            <ProjectSelector className="w-44 sm:w-52" />
            <div className="flex items-center gap-2 border-l border-line pl-3">
              <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-pine-100 text-sm font-semibold text-pine-700">
                {displayName.slice(0, 1)}
              </span>
              <span className="hidden max-w-32 truncate text-sm font-medium text-ink sm:block">{displayName}</span>
              {user ? (
                <button aria-label="退出登录" className="button-ghost h-9 w-9 px-0" onClick={logout} title="退出登录" type="button">
                  <LogOut size={16} />
                </button>
              ) : null}
            </div>
          </div>
        </header>
        <div className="flex-1">{children}</div>
      </div>
    </div>
  );
}

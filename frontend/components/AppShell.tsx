"use client";

import {
  Bell,
  BookOpenCheck,
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
import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { ProjectProvider, ProjectSelector, useProjectWorkspace } from "@/components/ProjectContext";
import { GlobalSearch } from "@/components/GlobalSearch";
import { BackgroundJobSummary, apiGet, clearSession } from "@/lib/api";
import {
  canViewNavigationAudience,
  navigationAccessForProject,
  type NavigationAccess,
  type NavigationAudience
} from "@/lib/navigation-contract.mjs";

type NavItem = {
  href: string;
  label: string;
  icon: typeof Bell;
  audience?: NavigationAudience;
  /** Prefix used for the active check when it differs from href. */
  match?: string;
};

type NavGroup = { label: string; items: NavItem[] };

const NAV_GROUPS: NavGroup[] = [
  {
    label: "工作台",
    items: [
      { href: "/workspace", label: "需求文档工作台", icon: FileSpreadsheet },
      { href: "/projects", label: "项目", icon: FolderKanban },
      { href: "/review-tasks", label: "我的待办", icon: ClipboardCheck }
    ]
  },
  {
    label: "需求文档",
    items: [
      { href: "/fields", label: "字段与口径", icon: ListTree },
      { href: "/questions", label: "待确认问题", icon: ListChecks },
      { href: "/templates", label: "监管模板", icon: TableProperties }
    ]
  },
  {
    label: "数据资产",
    items: [
      { href: "/datasources", label: "数据源", icon: Database, audience: "technical" },
      { href: "/catalog", label: "数据目录", icon: LibraryBig, audience: "technical" },
      { href: "/semantics", label: "语义目录", icon: BookOpenCheck },
      { href: "/quality", label: "质量期望", icon: ShieldCheck },
      { href: "/business-systems", label: "业务系统", icon: Building2, audience: "technical" },
      { href: "/mart", label: "监管集市", icon: Layers3, audience: "technical" }
    ]
  },
  {
    label: "知识库",
    items: [
      { href: "/knowledge", label: "知识检索", icon: BrainCircuit },
      { href: "/historical-calibers", label: "历史口径库", icon: History }
    ]
  },
  {
    label: "交付中心",
    items: [
      { href: "/deliverables", label: "正式交付", icon: PackageCheck },
      { href: "/export", label: "Excel 导出", icon: FileOutput }
    ]
  }
];

const SECONDARY_NAV: NavItem[] = [
  { href: "/traceability-templates", label: "历史口径模板", icon: TableProperties, audience: "technical" },
  { href: "/lineage", label: "脚本血缘", icon: GitBranch, audience: "technical" },
  { href: "/evaluations", label: "RAG 评测", icon: ChartNoAxesCombined, audience: "admin" },
  { href: "/tasks", label: "安全查询", icon: Workflow, audience: "technical" },
  { href: "/deliverable-templates", label: "交付模板", icon: FileSpreadsheet, audience: "admin" },
  { href: "/uat", label: "UAT 验收", icon: ShieldCheck, audience: "admin" },
  { href: "/notifications", label: "通知", icon: Bell },
  { href: "/jobs", label: "后台任务", icon: History, audience: "technical" },
  { href: "/audit", label: "审计", icon: ScrollText, audience: "admin" },
  { href: "/admin/institutions", label: "系统管理", icon: Settings2, match: "/admin", audience: "admin" },
  { href: "/legacy", label: "Legacy 综合工作台", icon: LayoutGrid, audience: "admin" }
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

function SidebarNav({ access, pathname, runningJobs = 0 }: { access: NavigationAccess; pathname: string; runningJobs?: number }) {
  const canSee = (item: NavItem) => canViewNavigationAudience(item.audience, access);
  const primaryGroups = NAV_GROUPS.map((group) => ({ ...group, items: group.items.filter(canSee) })).filter((group) => group.items.length);
  const secondaryItems = SECONDARY_NAV.filter(canSee);
  const secondaryActive = secondaryItems.some((item) => isActive(pathname, item));
  const [secondaryOpen, setSecondaryOpen] = useState(secondaryActive);
  useEffect(() => { if (secondaryActive) setSecondaryOpen(true); }, [secondaryActive]);
  return (
    <nav className="flex-1 space-y-4 overflow-y-auto px-3 pb-4">
      {primaryGroups.map((group) => (
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
      {secondaryItems.length ? <details className="group border-t border-white/[0.06] pt-3" onToggle={(event) => setSecondaryOpen(event.currentTarget.open)} open={secondaryOpen}>
        <summary className="mx-1 flex cursor-pointer list-none items-center gap-2 rounded-lg px-3 py-2 text-[12px] font-medium text-emerald-50/45 hover:bg-white/[0.05] hover:text-white">
          <Settings2 size={15} />系统管理与低频工具
          <span className="ml-auto text-[10px] transition group-open:rotate-180">⌄</span>
        </summary>
        <div className="mt-1 space-y-0.5">
          {secondaryItems.map((item) => {
            const active = isActive(pathname, item);
            const Icon = item.icon;
            return (
              <Link className={`flex items-center gap-2.5 rounded-lg px-3 py-2 text-[12px] transition ${active ? "bg-white/[0.09] text-white" : "text-emerald-50/55 hover:bg-white/[0.05] hover:text-white"}`} href={item.href} key={item.href}>
                <Icon size={15} />{item.label}
                {item.href === "/jobs" && runningJobs > 0 ? <span className="ml-auto rounded-full bg-amber-300 px-1.5 text-[9px] font-bold text-amber-950">{runningJobs}</span> : null}
              </Link>
            );
          })}
        </div>
      </details> : null}
    </nav>
  );
}

function SidebarBrand() {
  return (
    <Link className="flex h-[70px] items-center gap-3 border-b border-white/[0.06] px-5" href="/workspace">
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
      银行内网业务系统 · 人工确认优先
    </div>
  );
}

function ShellContent({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const { projectId, selectedProject } = useProjectWorkspace();
  const [user, setUser] = useState<{
    display_name?: string | null;
    username: string;
    effective_project_permissions?: Record<string, string[]>;
    institution_memberships?: Array<{ institution_id?: number; role?: string; status?: string }>;
  } | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const jobsQuery = useQuery({
    queryKey:["project-jobs",projectId],
    queryFn:({signal})=>apiGet<BackgroundJobSummary[]>(`/jobs?project_id=${projectId}`,{signal,cache:"no-cache"}),
    enabled:Boolean(projectId),
    staleTime:5_000,
    refetchInterval:(query)=>{
      const jobs=(query.state.data as BackgroundJobSummary[]|undefined)||[];
      return jobs.some((job)=>["queued","running"].includes(job.status))?5_000:60_000;
    }
  });
  const runningJobs = (jobsQuery.data || []).filter((job) => ["queued", "running"].includes(job.status)).length;

  useEffect(() => {
    apiGet<NonNullable<typeof user>>("/auth/me").then(setUser).catch(() => setUser(null));
  }, []);

  useEffect(() => {
    setDrawerOpen(false);
  }, [pathname]);
  const displayName = user?.display_name || user?.username || "未登录";
  const navigationAccess = navigationAccessForProject(user, projectId);

  function logout() {
    clearSession();
    router.replace("/login");
  }

  return (
    <div className="flex min-h-screen bg-mist">
      <aside className="sticky top-0 hidden h-screen w-[248px] shrink-0 flex-col bg-gradient-to-b from-[#102a30] to-[#0a1f22] lg:flex">
        <SidebarBrand />
        <SidebarNav access={navigationAccess} pathname={pathname} runningJobs={runningJobs} />
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
            <SidebarNav access={navigationAccess} pathname={pathname} runningJobs={runningJobs} />
            <SidebarFooter />
          </aside>
        </div>
      ) : null}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-40 border-b border-line bg-white/95 backdrop-blur">
          <div className="flex h-[70px] items-center gap-3 px-4 lg:px-6">
            <button aria-label="打开导航" className="button-ghost h-9 w-9 px-0 lg:hidden" onClick={() => setDrawerOpen(true)} type="button">
              <Menu size={18} />
            </button>
            <div className="hidden min-w-0 items-baseline gap-2 md:flex">
              <span className="truncate text-sm font-medium text-ink">{selectedProject?.bank_name || "未选择机构"}</span>
              {selectedProject ? <span className="truncate text-xs text-slate-400">{selectedProject.name}</span> : null}
            </div>
            <div className="flex-1" />
            <GlobalSearch projectId={projectId} />
            <Link className="hidden items-center gap-2 rounded-full border border-pine-100 bg-pine-50 px-3 py-1.5 text-[11px] font-medium text-pine-700 xl:flex" href="/jobs">
              <span className={`h-1.5 w-1.5 rounded-full ${runningJobs ? "bg-gold-500" : "bg-pine-400"}`} />
              {runningJobs ? `${runningJobs} 个后台任务运行中` : "后台任务正常"}
            </Link>
            <ProjectSelector className="w-32 sm:w-52" />
            <div className="flex items-center gap-1 sm:gap-2 sm:border-l sm:border-line sm:pl-3">
              <span className="hidden h-8 w-8 shrink-0 items-center justify-center rounded-full bg-pine-100 text-sm font-semibold text-pine-700 sm:flex">
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
        <ProjectContentBoundary>{children}</ProjectContentBoundary>
      </div>
    </div>
  );
}

function ProjectContentBoundary({ children }: { children: React.ReactNode }) {
  const { projectId } = useProjectWorkspace();
  // A project switch must never leave the previous project's page state mounted
  // while the next project starts loading. The keyed boundary immediately drops
  // rendered sensitive state; page fetches then begin from their empty state.
  return <div className="flex-1" key={`project-scope-${projectId ?? "none"}`}>{children}</div>;
}

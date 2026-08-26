"use client";

import { ArrowLeft, ChevronRight } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

const sectionRoutes = [
  ["/workspace", "需求工作台"], ["/projects", "项目"], ["/datasources", "数据源"], ["/catalog", "数据目录"],
  ["/semantics", "监管语义"], ["/fields", "字段与口径"], ["/mart", "监管集市"], ["/knowledge", "知识与证据"],
  ["/lineage", "技术血缘"], ["/deliverables", "交付成果"], ["/historical-calibers", "历史口径"],
  ["/review-tasks", "我的待办"], ["/questions", "待确认问题"], ["/jobs", "后台任务"], ["/admin", "系统管理"]
] as const;

function parentRoute(pathname: string) {
  if (/^\/semantics\/\d+$/.test(pathname)) return "/semantics";
  if (/^\/datasources\/\d+\/catalog$/.test(pathname)) return "/datasources";
  if (/^\/fields\/\d+\/scenarios$/.test(pathname)) return "/fields";
  if (/^\/projects\/\d+\/(dashboard|members|onboarding|readiness)$/.test(pathname)) return "/projects";
  if (/^\/deliverables\/\d+$/.test(pathname)) return "/deliverables";
  if (/^\/deliverable-templates\/\d+$/.test(pathname)) return "/deliverable-templates";
  if (/^\/historical-calibers\/\d+$/.test(pathname)) return "/historical-calibers";
  if (/^\/knowledge\/documents\/\d+$/.test(pathname)) return "/knowledge/documents";
  if (/^\/lineage\/(changes|impacts|scripts)\/\d+$/.test(pathname) || /^\/lineage\/fields\/\d+$/.test(pathname)) return "/lineage";
  if (/^\/uat\/(findings|runs|suites)\/\d+$/.test(pathname)) return "/uat";
  return null;
}

export function WorkspaceHeader({ title, meta, actions }: { title: string; meta?: string; actions?: React.ReactNode }) {
  const pathname = usePathname();
  const [retainedQuery, setRetainedQuery] = useState("");
  useEffect(() => { setRetainedQuery(window.location.search.slice(1)); }, [pathname]);
  const parent = parentRoute(pathname);
  const section = [...sectionRoutes].sort((a, b) => b[0].length - a[0].length).find(([route]) => pathname === route || pathname.startsWith(`${route}/`));
  const parentHref = parent ? `${parent}${retainedQuery ? `?${retainedQuery}` : ""}` : null;
  return (
    <div className="border-b border-line bg-white">
      <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-5 lg:px-6">
        <div className="min-w-0">
          <nav aria-label="当前位置" className="mb-2 flex min-w-0 items-center gap-1.5 text-xs text-slate-500">
            <Link className="hover:text-pine-700" href="/workspace">工作台</Link>
            {section && section[0] !== "/workspace" ? <><ChevronRight aria-hidden size={13} /><Link className="truncate hover:text-pine-700" href={section[0]}>{section[1]}</Link></> : null}
            {parent ? <><ChevronRight aria-hidden size={13} /><span aria-current="page" className="truncate text-slate-700">{title}</span></> : null}
          </nav>
          {parentHref ? <Link className="button-ghost -ml-2 mb-2 h-8 px-2 text-xs" href={parentHref}><ArrowLeft aria-hidden size={15} />返回{section?.[1] || "上级"}</Link> : null}
          <h1 className="text-xl font-semibold tracking-tight text-ink">{title}</h1>
          {meta ? <p className="mt-1 text-sm text-slate-500">{meta}</p> : null}
        </div>
        {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
      </div>
    </div>
  );
}

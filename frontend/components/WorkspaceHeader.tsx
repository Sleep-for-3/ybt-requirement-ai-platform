"use client";

import { ArrowLeft, ChevronRight } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { navigationTrailForPath, parentReturnHref } from "@/lib/navigation-contract.mjs";

export function WorkspaceHeader({ title, meta, actions }: { title: string; meta?: string; actions?: React.ReactNode }) {
  const pathname = usePathname();
  const [retainedQuery, setRetainedQuery] = useState("");
  useEffect(() => { setRetainedQuery(window.location.search.slice(1)); }, [pathname]);
  const trail = navigationTrailForPath(pathname);
  const parentHref = parentReturnHref(trail.parentHref, retainedQuery);
  return (
    <div className="border-b border-line bg-white">
      <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-5 lg:px-6">
        <div className="min-w-0">
          <nav aria-label="当前位置" className="mb-2 flex min-w-0 items-center gap-1.5 text-xs text-slate-500">
            <Link className="hover:text-pine-700" href="/workspace">工作台</Link>
            {trail.sectionHref && trail.sectionHref !== "/workspace" ? <><ChevronRight aria-hidden size={13} /><Link className="truncate hover:text-pine-700" href={trail.sectionHref}>{trail.sectionLabel}</Link></> : null}
            {trail.parentHref ? <><ChevronRight aria-hidden size={13} /><span aria-current="page" className="truncate text-slate-700">{title}</span></> : null}
          </nav>
          {parentHref ? <Link className="button-ghost -ml-2 mb-2 h-8 px-2 text-xs" href={parentHref}><ArrowLeft aria-hidden size={15} />返回{trail.sectionLabel || "上级"}</Link> : null}
          <h1 className="text-xl font-semibold tracking-tight text-ink">{title}</h1>
          {meta ? <p className="mt-1 text-sm text-slate-500">{meta}</p> : null}
        </div>
        {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
      </div>
    </div>
  );
}

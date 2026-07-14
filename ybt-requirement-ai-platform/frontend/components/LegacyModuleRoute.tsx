"use client";

import { ArrowRight } from "lucide-react";
import Link from "next/link";

import { useProjectWorkspace } from "@/components/ProjectContext";
import { WorkspaceHeader } from "@/components/WorkspaceHeader";

export function LegacyModuleRoute({ title }: { title: string }) {
  const { projects, selectProject } = useProjectWorkspace();
  return <main><WorkspaceHeader title={title} meta={`${projects.length} 个可用项目`} /><div className="mx-auto max-w-4xl p-6"><section className="panel overflow-hidden">{projects.map((project) => <div className="flex items-center justify-between gap-4 border-b border-line px-4 py-3 last:border-0" key={project.id}><div><div className="font-medium">{project.name}</div><div className="mt-1 text-xs text-slate-500">{project.bank_name || "-"}</div></div><Link className="button-secondary" href="/legacy" onClick={() => selectProject(project.id)} title={`打开 ${title}`}><ArrowRight size={16} /></Link></div>)}</section></div></main>;
}

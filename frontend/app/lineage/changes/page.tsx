"use client";

import { GitCompare } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { useProjectWorkspace } from "@/components/ProjectContext";
import { WorkspaceHeader } from "@/components/WorkspaceHeader";
import { ScriptChange, apiGet } from "@/lib/api";

function severityBadge(severity: string) {
  if (severity === "critical") return "badge-danger";
  if (severity === "high") return "badge-warning";
  return "badge-neutral";
}

export default function Page() {
  const { projectId } = useProjectWorkspace();
  const [items, setItems] = useState<ScriptChange[]>([]);

  useEffect(() => {
    if (projectId) void apiGet<ScriptChange[]>(`/projects/${projectId}/lineage/changes`).then(setItems);
  }, [projectId]);

  return (
    <main>
      <WorkspaceHeader title="脚本版本变化" meta="文本、AST、语义与血缘 diff" />
      <div className="mx-auto max-w-6xl p-4 lg:p-6">
        <section className="panel overflow-hidden">
          {items.length ? (
            <>
              <div className="grid-head grid grid-cols-[minmax(0,1fr)_110px]">
                <span>变更集</span>
                <span className="text-right">风险等级</span>
              </div>
              {items.map((item) => (
                <Link
                  className="grid-row grid grid-cols-[minmax(0,1fr)_110px] items-center"
                  href={`/lineage/changes/${item.id}`}
                  key={item.id}
                >
                  <div>
                    <strong className="text-ink">
                      变更集 #{item.id} · 脚本 #{item.script_file_id}
                    </strong>
                    <div className="mt-1 text-xs text-slate-500">
                      {((item.summary.categories as string[]) || []).join("、") || item.change_type}
                    </div>
                  </div>
                  <span className="justify-self-end">
                    <span className={severityBadge(item.severity)}>{item.severity}</span>
                  </span>
                </Link>
              ))}
            </>
          ) : (
            <div className="panel-body">
              <div className="empty-state">
                <GitCompare className="text-slate-300" size={28} />
                <p>暂无版本变化，脚本产生新版本后差异会出现在这里</p>
              </div>
            </div>
          )}
        </section>
      </div>
    </main>
  );
}

"use client";

import { ScrollText } from "lucide-react";
import { useEffect, useState } from "react";

import { useProjectWorkspace } from "@/components/ProjectContext";
import { WorkspaceHeader } from "@/components/WorkspaceHeader";
import { apiGet } from "@/lib/api";

type Audit = {
  id: number;
  action: string;
  resource_type: string;
  resource_id?: string | null;
  actor_user_id?: number | null;
  result: string;
  created_at: string;
};

function resultBadge(result: string) {
  if (["success", "approved", "completed"].includes(result)) return "badge-success";
  if (["failed", "denied", "rejected", "error"].includes(result)) return "badge-danger";
  if (["pending", "running", "processing"].includes(result)) return "badge-warning";
  return "badge-neutral";
}

export default function Page() {
  const { projectId } = useProjectWorkspace();
  const [items, setItems] = useState<Audit[]>([]);

  useEffect(() => {
    if (projectId) apiGet<Audit[]>(`/audit?project_id=${projectId}`).then(setItems).catch(() => setItems([]));
  }, [projectId]);

  return (
    <main>
      <WorkspaceHeader title="操作审计" meta="不可修改的脱敏操作摘要" />
      <div className="mx-auto max-w-6xl p-4 lg:p-6">
        {items.length ? (
          <section className="panel overflow-hidden">
            <div className="grid-head grid grid-cols-[160px_140px_1fr_100px]">
              <span>操作</span>
              <span>资源类型</span>
              <span>详情</span>
              <span>结果</span>
            </div>
            {items.map((item) => (
              <div className="grid-row grid grid-cols-[160px_140px_1fr_100px] items-center" key={item.id}>
                <span>{item.action}</span>
                <span>{item.resource_type}</span>
                <span className="text-slate-600">
                  资源 #{item.resource_id || "-"} · 操作者 #{item.actor_user_id || "系统"}
                </span>
                <span>
                  <span className={resultBadge(item.result)}>{item.result}</span>
                </span>
              </div>
            ))}
          </section>
        ) : (
          <div className="empty-state">
            <ScrollText className="text-slate-300" size={28} />
            <p>暂无审计记录，选择项目后将展示该项目的操作留痕</p>
          </div>
        )}
      </div>
    </main>
  );
}

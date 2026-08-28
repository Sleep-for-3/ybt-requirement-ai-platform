"use client";

import { ClipboardList } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { WorkspaceHeader } from "@/components/WorkspaceHeader";
import { apiGet, apiPost } from "@/lib/api";
import { statusLabel, workflowStepLabel } from "@/lib/product-language";

type Task = {
  id: number;
  step_key: string;
  task_type: string;
  status: string;
  project_id: number;
  due_at?: string | null;
};

function statusBadge(status: string) {
  if (["approved", "completed", "success"].includes(status)) return "badge-success";
  if (["failed", "rejected", "error"].includes(status)) return "badge-danger";
  if (["pending", "running", "processing"].includes(status)) return "badge-warning";
  return "badge-neutral";
}

export default function Page() {
  const [items, setItems] = useState<Task[]>([]);

  async function reload() {
    setItems(await apiGet("/me/tasks"));
  }

  useEffect(() => {
    void reload();
  }, []);

  async function claim(id: number) {
    await apiPost(`/review-tasks/${id}/claim`, {});
    await reload();
  }

  return (
    <main>
      <WorkspaceHeader title="我的待办" meta={`${items.length} 个待处理任务`} />
      <div className="mx-auto max-w-5xl p-4 lg:p-6">
        {items.length ? (
          <section className="panel overflow-hidden">
            <div className="grid-head grid grid-cols-[1fr_130px_170px_180px]">
              <span>任务</span>
              <span>状态</span>
              <span>到期时间</span>
              <span className="text-right">操作</span>
            </div>
            {items.map((item) => (
              <div className="grid-row grid grid-cols-[1fr_130px_170px_180px] items-center" key={item.id}>
                <div>
                  <b className="text-sm text-ink">{workflowStepLabel(item.step_key)}</b>
                  <div className="mt-0.5 text-xs text-slate-500">所属项目 #{item.project_id}</div>
                </div>
                <span>
                  <span className={statusBadge(item.status)}>{statusLabel(item.status)}</span>
                </span>
                <span className="text-xs text-slate-500">{item.due_at || "未设置到期时间"}</span>
                <div className="flex justify-end gap-2">
                  {!item.status.includes("claimed") ? (
                    <button className="button-secondary" onClick={() => claim(item.id)}>
                      领取
                    </button>
                  ) : null}
                  <Link className="button-primary" href={`/tasks/${item.id}`}>
                    处理
                  </Link>
                </div>
              </div>
            ))}
          </section>
        ) : (
          <div className="empty-state">
            <ClipboardList className="text-slate-300" size={28} />
            <p>暂无待办任务，分派给你的评审任务会出现在这里</p>
          </div>
        )}
      </div>
    </main>
  );
}

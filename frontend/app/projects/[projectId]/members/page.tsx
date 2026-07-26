"use client";

import { UserPlus, Users } from "lucide-react";
import { useParams } from "next/navigation";
import { FormEvent, useEffect, useState } from "react";

import { WorkspaceHeader } from "@/components/WorkspaceHeader";
import { apiGet, apiPost } from "@/lib/api";

type Member = { id: number; user_id: number; project_role: string; status: string };

const ROLES = [
  "project_manager",
  "business_analyst",
  "technical_analyst",
  "business_reviewer",
  "technical_reviewer",
  "final_reviewer",
  "knowledge_manager",
  "data_catalog_manager",
  "viewer"
];

function statusBadge(status: string) {
  if (["active", "enabled", "approved"].includes(status)) return "badge-success";
  if (["failed", "rejected", "error"].includes(status)) return "badge-danger";
  if (["pending", "running", "processing"].includes(status)) return "badge-warning";
  return "badge-neutral";
}

export default function Page() {
  const { projectId } = useParams<{ projectId: string }>();
  const [items, setItems] = useState<Member[]>([]);

  async function reload() {
    setItems(await apiGet(`/projects/${projectId}/members`));
  }

  useEffect(() => {
    void reload();
  }, [projectId]);

  async function add(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    await apiPost(`/projects/${projectId}/members`, {
      user_id: Number(form.get("user_id")),
      project_role: form.get("role")
    });
    await reload();
  }

  return (
    <main>
      <WorkspaceHeader title="项目成员" meta="用户、角色与职责分离" />
      <div className="mx-auto grid max-w-5xl gap-5 p-4 lg:grid-cols-[320px_1fr] lg:p-6">
        <form className="panel h-fit" onSubmit={add}>
          <div className="panel-header">
            <h2 className="text-[15px] font-semibold text-ink">添加成员</h2>
          </div>
          <div className="panel-body space-y-3">
            <input className="control" name="user_id" type="number" placeholder="用户 ID" required />
            <select className="control" name="role">
              {ROLES.map((role) => (
                <option key={role}>{role}</option>
              ))}
            </select>
            <button className="button-primary w-full">
              <UserPlus size={16} />
              添加或更新成员
            </button>
          </div>
        </form>

        {items.length ? (
          <section className="panel h-fit overflow-hidden">
            <div className="grid-head grid grid-cols-[120px_1fr_96px] gap-3">
              <span>用户</span>
              <span>项目角色</span>
              <span>状态</span>
            </div>
            {items.map((item) => (
              <div className="grid-row grid grid-cols-[120px_1fr_96px] items-center gap-3" key={item.id}>
                <span className="font-medium text-ink">用户 #{item.user_id}</span>
                <span className="truncate text-slate-600">{item.project_role}</span>
                <span>
                  <span className={statusBadge(item.status)}>{item.status}</span>
                </span>
              </div>
            ))}
          </section>
        ) : (
          <div className="empty-state h-fit">
            <Users className="text-slate-300" size={28} />
            <p>还没有项目成员，先在左侧按用户 ID 分配项目角色</p>
          </div>
        )}
      </div>
    </main>
  );
}

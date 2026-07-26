"use client";

import { FormEvent, useEffect, useState } from "react";
import { Plus, Server } from "lucide-react";

import { useProjectWorkspace } from "@/components/ProjectContext";
import { WorkspaceHeader } from "@/components/WorkspaceHeader";
import { BusinessSystem, apiGet, apiPost } from "@/lib/api";

export default function Page() {
  const { projectId } = useProjectWorkspace();
  const [items, setItems] = useState<BusinessSystem[]>([]);
  const [message, setMessage] = useState("");

  async function reload() {
    if (projectId) setItems(await apiGet(`/projects/${projectId}/business-systems`));
  }

  useEffect(() => {
    void reload();
  }, [projectId]);

  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!projectId) return;
    const form = new FormData(event.currentTarget);
    try {
      await apiPost(`/projects/${projectId}/business-systems`, {
        system_code: form.get("code"),
        system_name: form.get("name"),
        owner_department: form.get("owner"),
        description: form.get("description"),
        enabled: true
      });
      event.currentTarget.reset();
      setMessage("业务系统已创建");
      await reload();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "创建失败");
    }
  }

  return (
    <main>
      <WorkspaceHeader title="业务系统来源层" meta={`${items.length} 个业务系统`} />
      <div className="mx-auto grid max-w-[1400px] gap-5 p-4 lg:grid-cols-[360px_1fr] lg:p-6">
        <form className="panel h-fit" onSubmit={create}>
          <div className="panel-header">
            <h2 className="text-[15px] font-semibold text-ink">新增业务系统</h2>
          </div>
          <div className="panel-body space-y-3">
            <input className="control" name="code" placeholder="系统代码" required />
            <input className="control" name="name" placeholder="系统名称" required />
            <input className="control" name="owner" placeholder="负责部门" />
            <textarea className="control" name="description" placeholder="脱敏说明" />
            <button className="button-primary w-full" type="submit">
              <Plus size={16} />
              新增
            </button>
            {message ? (
              <p className="rounded-lg border border-line bg-white px-3 py-2 text-sm text-slate-600">{message}</p>
            ) : null}
          </div>
        </form>

        <section className="panel h-fit overflow-hidden">
          <div className="grid-head grid grid-cols-[140px_1fr_1fr_90px]">
            <span>系统代码</span>
            <span>系统名称</span>
            <span>负责部门</span>
            <span>状态</span>
          </div>
          {items.length ? (
            items.map((item) => (
              <div className="grid-row grid grid-cols-[140px_1fr_1fr_90px] items-center" key={item.id}>
                <span className="font-medium text-ink">{item.system_code}</span>
                <span className="text-ink">{item.system_name}</span>
                <span className="text-slate-500">{item.owner_department || "负责部门待确认"}</span>
                <span>
                  {item.enabled ? (
                    <span className="badge-success">启用</span>
                  ) : (
                    <span className="badge-neutral">停用</span>
                  )}
                </span>
              </div>
            ))
          ) : (
            <div className="m-4">
              <div className="empty-state">
                <Server className="text-slate-300" size={28} />
                <p>还没有业务系统，先在左侧登记来源业务系统</p>
              </div>
            </div>
          )}
        </section>
      </div>
    </main>
  );
}

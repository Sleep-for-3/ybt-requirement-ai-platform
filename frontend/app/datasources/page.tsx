"use client";

import { FormEvent, useEffect, useState } from "react";
import { Database, Play } from "lucide-react";
import Link from "next/link";

import { useProjectWorkspace } from "@/components/ProjectContext";
import { WorkspaceHeader } from "@/components/WorkspaceHeader";
import { DataSource, apiGet, apiPost } from "@/lib/api";

function testStatusBadge(status?: string | null) {
  if (status === "success") return "badge-success";
  if (status === "failed" || status === "error") return "badge-danger";
  return "badge-neutral";
}

export default function Page() {
  const { projectId } = useProjectWorkspace();
  const [items, setItems] = useState<DataSource[]>([]);
  const [message, setMessage] = useState("");

  async function reload() {
    if (projectId) setItems(await apiGet(`/projects/${projectId}/datasources`));
  }

  useEffect(() => {
    void reload();
  }, [projectId]);

  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!projectId) return;
    const form = new FormData(event.currentTarget);
    try {
      await apiPost(`/projects/${projectId}/datasources`, {
        name: form.get("name"),
        display_name: form.get("display"),
        db_type: "sqlite",
        database_name: form.get("database"),
        readonly_flag: true,
        enabled: true
      });
      event.currentTarget.reset();
      setMessage("只读 SQLite 数据源已创建");
      await reload();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "创建失败");
    }
  }

  async function test(id: number) {
    try {
      const result = await apiPost<{ status: string; message: string }>(`/datasources/${id}/test`, {});
      setMessage(`${result.status}: ${result.message}`);
      await reload();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "连接失败");
    }
  }

  return (
    <main>
      <WorkspaceHeader title="数据源" meta="只读连接、元数据同步与 SafeSqlExecutor" />
      <div className="mx-auto grid max-w-[1400px] gap-5 p-4 lg:grid-cols-[360px_1fr] lg:p-6">
        <form className="panel h-fit" onSubmit={create}>
          <div className="panel-header">
            <h2 className="text-[15px] font-semibold text-ink">新增只读 SQLite 数据源</h2>
          </div>
          <div className="panel-body space-y-3">
            <input className="control" name="name" placeholder="连接名称" required />
            <input className="control" name="display" placeholder="显示名称" />
            <input className="control" name="database" placeholder="脱敏测试库路径" required />
            <button className="button-primary w-full" type="submit">
              <Database size={16} />
              新增
            </button>
            {message ? (
              <p className="rounded-lg border border-line bg-white px-3 py-2 text-sm text-slate-600">{message}</p>
            ) : null}
          </div>
        </form>

        <section className="panel h-fit overflow-hidden">
          <div className="grid-head grid grid-cols-[1fr_130px_230px]">
            <span>数据源</span>
            <span>测试状态</span>
            <span className="text-right">操作</span>
          </div>
          {items.length ? (
            items.map((item) => (
              <div className="grid-row grid grid-cols-[1fr_130px_230px] items-center" key={item.id}>
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-medium text-ink">
                    {item.name} · {item.display_name || item.db_type}
                  </span>
                  <span className="badge-info">只读</span>
                </div>
                <span>
                  <span className={testStatusBadge(item.last_test_status)}>
                    {item.last_test_status || "未测试"}
                  </span>
                </span>
                <div className="flex justify-end gap-2">
                  <button className="button-secondary" onClick={() => test(item.id)}>
                    <Play size={16} />
                    测试
                  </button>
                  <Link className="button-primary" href={`/datasources/${item.id}/catalog`}>
                    元数据目录
                  </Link>
                </div>
              </div>
            ))
          ) : (
            <div className="m-4">
              <div className="empty-state">
                <Database className="text-slate-300" size={28} />
                <p>还没有数据源，先在左侧新增只读 SQLite 数据源</p>
              </div>
            </div>
          )}
        </section>
      </div>
    </main>
  );
}

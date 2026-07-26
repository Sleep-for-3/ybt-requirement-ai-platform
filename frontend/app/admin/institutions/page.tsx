"use client";

import { Building2, Plus } from "lucide-react";
import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";

import { WorkspaceHeader } from "@/components/WorkspaceHeader";
import { apiGet, apiPost } from "@/lib/api";

type Institution = {
  id: number;
  institution_code: string;
  institution_name: string;
  institution_type: string;
  status: string;
};

export default function Page() {
  const [items, setItems] = useState<Institution[]>([]);
  const [msg, setMsg] = useState("");

  async function reload() {
    try {
      setItems(await apiGet("/admin/institutions"));
    } catch (error) {
      setMsg(error instanceof Error ? error.message : "加载失败");
    }
  }

  useEffect(() => {
    void reload();
  }, []);

  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    try {
      await apiPost("/admin/institutions", {
        institution_code: form.get("code"),
        institution_name: form.get("name"),
        institution_type: form.get("type")
      });
      event.currentTarget.reset();
      await reload();
    } catch (error) {
      setMsg(error instanceof Error ? error.message : "创建失败");
    }
  }

  return (
    <main>
      <WorkspaceHeader title="机构管理" meta="银行、咨询公司与平台运营机构" />
      <div className="mx-auto grid max-w-[1300px] gap-5 p-4 lg:grid-cols-[360px_1fr] lg:p-6">
        <form className="panel h-fit" onSubmit={create}>
          <div className="panel-header">
            <h2 className="text-[15px] font-semibold text-ink">新建机构</h2>
          </div>
          <div className="panel-body space-y-3">
            <input className="control" name="code" placeholder="机构代码" required />
            <input className="control" name="name" placeholder="机构名称" required />
            <select className="control" name="type">
              <option value="bank">银行</option>
              <option value="consulting_company">咨询公司</option>
              <option value="platform_operator">平台运营方</option>
            </select>
            <button className="button-primary w-full">
              <Plus size={16} />
              创建机构
            </button>
            <div className="flex gap-2 border-t border-line pt-3">
              <Link className="button-secondary" href="/admin/users">
                用户
              </Link>
              <Link className="button-secondary" href="/admin/permissions">
                权限矩阵
              </Link>
            </div>
            {msg ? (
              <p className="rounded-lg border border-coral-200 bg-coral-50 px-3 py-2 text-sm text-coral-700">{msg}</p>
            ) : null}
          </div>
        </form>

        {items.length ? (
          <section className="panel h-fit overflow-hidden">
            <div className="grid-head grid grid-cols-[1fr_auto]">
              <span>机构</span>
              <span>状态</span>
            </div>
            {items.map((item) => (
              <div className="grid-row grid grid-cols-[1fr_auto] items-center gap-3" key={item.id}>
                <div>
                  <b>{item.institution_name}</b>
                  <div className="text-xs text-slate-500">
                    {item.institution_code} · {item.institution_type}
                  </div>
                </div>
                <span className={item.status === "active" ? "badge-success" : "badge-neutral"}>{item.status}</span>
              </div>
            ))}
          </section>
        ) : (
          <div className="empty-state h-fit">
            <Building2 className="text-slate-300" size={28} />
            <p>还没有机构，先在左侧创建银行、咨询公司或平台运营方</p>
          </div>
        )}
      </div>
    </main>
  );
}

"use client";

import { ShieldCheck } from "lucide-react";
import { useEffect, useState } from "react";

import { WorkspaceHeader } from "@/components/WorkspaceHeader";
import { apiGet } from "@/lib/api";

type Matrix = {
  institution_roles: string[];
  project_roles: Record<string, string[]>;
};

export default function Page() {
  const [data, setData] = useState<Matrix | null>(null);

  useEffect(() => {
    apiGet<Matrix>("/admin/permissions").then(setData).catch(() => setData(null));
  }, []);

  const roles = Object.entries(data?.project_roles || {});

  return (
    <main>
      <WorkspaceHeader title="权限矩阵" meta="统一 PermissionService 的只读视图" />
      <div className="mx-auto max-w-5xl p-4 lg:p-6">
        <section className="panel overflow-hidden">
          <div className="panel-header text-sm text-ink">
            机构角色：{data?.institution_roles.join("、") || "加载中"}
          </div>
          {roles.length ? (
            <>
              <div className="grid-head grid grid-cols-[220px_1fr]">
                <span>项目角色</span>
                <span>权限</span>
              </div>
              {roles.map(([role, permissions]) => (
                <div className="grid-row grid grid-cols-[220px_1fr] items-center" key={role}>
                  <b>{role}</b>
                  <span className="text-slate-600">{permissions.join("、")}</span>
                </div>
              ))}
            </>
          ) : (
            <div className="empty-state m-4">
              <ShieldCheck className="text-slate-300" size={28} />
              <p>暂无项目角色权限数据，请确认当前账号具备管理员权限</p>
            </div>
          )}
        </section>
      </div>
    </main>
  );
}

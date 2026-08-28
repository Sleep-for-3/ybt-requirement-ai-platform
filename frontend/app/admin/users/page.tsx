"use client";

import { UserPlus } from "lucide-react";
import { FormEvent, useEffect, useState } from "react";

import { WorkspaceHeader } from "@/components/WorkspaceHeader";
import { useAdminCapabilities } from "@/components/admin/AdminShell";
import { ConfirmDialog } from "@/components/feedback/ConfirmDialog";
import { ModalDialog } from "@/components/feedback/ModalDialog";
import { PageState } from "@/components/feedback/PageState";
import { apiGet, apiPost } from "@/lib/api";
import { institutionRoleLabel } from "@/lib/permission-language.mjs";
import { statusLabel } from "@/lib/product-language";

type Institution = { id: number; institution_name: string };
type AdminUser = {
  id: number;
  username: string;
  display_name?: string | null;
  email?: string | null;
  status: string;
  institution_memberships: Array<{ institution_id: number; institution_name: string; role: string; status: string }>;
};

export default function Page() {
  const capabilities = useAdminCapabilities();
  const [institutions, setInstitutions] = useState<Institution[]>([]);
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [msg, setMsg] = useState("");
  const [formError, setFormError] = useState("");
  const [createOpen, setCreateOpen] = useState(false);
  const [discardOpen, setDiscardOpen] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [creating, setCreating] = useState(false);

  useEffect(() => {
    void Promise.all([
      apiGet<Institution[]>("/admin/institutions"),
      apiGet<AdminUser[]>("/admin/users")
    ]).then(([nextInstitutions, nextUsers]) => {
      setInstitutions(nextInstitutions);
      setUsers(nextUsers);
      setMsg("");
    }).catch((error) => setMsg(error instanceof Error ? error.message : "用户目录加载失败"));
  }, []);

  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setFormError("");
    setCreating(true);
    try {
      await apiPost("/admin/users", {
        username: form.get("username"),
        display_name: form.get("display_name"),
        email: form.get("email"),
        password: form.get("password"),
        institution_id: Number(form.get("institution_id")),
        institution_role: form.get("role")
      });
      event.currentTarget.reset();
      setUsers(await apiGet<AdminUser[]>("/admin/users"));
      setDirty(false);
      setCreateOpen(false);
      setMsg("用户已创建，密码仅保存为 Argon2 哈希");
    } catch (error) {
      setFormError(error instanceof Error ? error.message : "创建失败");
    } finally {
      setCreating(false);
    }
  }

  function requestCloseCreate() {
    if (creating) return;
    if (dirty) { setDiscardOpen(true); return; }
    setCreateOpen(false);
  }

  function openCreate() {
    setFormError("");
    setCreateOpen(true);
  }

  return (
    <main>
      <WorkspaceHeader title="用户管理" meta={`${users.length} 个权限范围内用户`} actions={capabilities.can_manage_users ? <button className="button-primary" disabled={!institutions.length} onClick={openCreate} type="button"><UserPlus size={16} />新建用户</button> : null} />
      <div className="mx-auto max-w-[1300px] p-4 lg:p-6">
        {msg ? <p className="mb-4 rounded-lg border border-line bg-white px-3 py-2 text-sm text-slate-600">{msg}</p> : null}
        {users.length ? (
          <section className="panel overflow-hidden">
            <div className="grid-head grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)_minmax(0,1.2fr)_100px]"><span>用户</span><span>邮箱</span><span>机构角色</span><span>状态</span></div>
            {users.map((user) => <div className="grid-row grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)_minmax(0,1.2fr)_100px] items-center gap-3" key={user.id}><div className="min-w-0"><p className="truncate font-medium text-ink">{user.display_name || user.username}</p><p className="truncate text-xs text-slate-500">{user.username}</p></div><span className="truncate text-sm text-slate-600">{user.email || "未填写"}</span><div className="flex flex-wrap gap-1">{user.institution_memberships.map((membership) => <span className="badge-neutral" key={`${membership.institution_id}-${membership.role}`}>{membership.institution_name} · {institutionRoleLabel(membership.role)}</span>)}</div><span className={user.status === "active" ? "badge-success" : "badge-neutral"}>{statusLabel(user.status)}</span></div>)}
          </section>
        ) : <PageState kind="empty" title="权限范围内暂无用户" description="创建用户时必须指定机构和机构角色。" action={capabilities.can_manage_users ? <button className="button-primary" disabled={!institutions.length} onClick={openCreate} type="button"><UserPlus size={16} />新建用户</button> : null} />}
      </div>
      <ModalDialog description="初始密码仅用于首次登录，后端只保存 Argon2 哈希。" onClose={requestCloseCreate} open={createOpen} title="新建用户">
        <form className="space-y-4" onChange={() => setDirty(true)} onSubmit={create}>
            {formError ? <p className="rounded-lg border border-coral-200 bg-coral-50 px-3 py-2 text-sm text-coral-700" role="alert">{formError}</p> : null}
            <div className="grid gap-3 sm:grid-cols-2">
              <input className="control" name="username" placeholder="用户名" required />
              <input className="control" name="display_name" placeholder="显示名称" required />
              <input className="control" type="email" name="email" placeholder="邮箱" required />
              <input
                className="control"
                type="password"
                name="password"
                placeholder="初始密码（至少 12 位）"
                minLength={12}
                required
              />
              <select className="control" name="institution_id" required>
                <option value="">选择机构</option>
                {institutions.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.institution_name}
                  </option>
                ))}
              </select>
              <select className="control" name="role">
                <option value="member">普通成员</option>
                <option value="institution_admin">机构管理员</option>
                <option value="security_admin">安全管理员</option>
                <option value="auditor">审计人员</option>
              </select>
            </div>
            <div className="flex justify-end gap-2"><button className="button-secondary" disabled={creating} onClick={requestCloseCreate} type="button">取消</button><button className="button-primary" disabled={creating} type="submit"><UserPlus size={16} />{creating ? "创建中…" : "创建用户"}</button></div>
        </form>
      </ModalDialog>
      <ConfirmDialog danger confirmText="放弃修改" description="尚未保存的用户和初始密码将丢失。" onCancel={() => setDiscardOpen(false)} onConfirm={() => { setDiscardOpen(false); setDirty(false); setCreateOpen(false); }} open={discardOpen} title="放弃新建用户？" />
    </main>
  );
}

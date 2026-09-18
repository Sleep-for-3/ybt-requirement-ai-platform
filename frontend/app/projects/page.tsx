"use client";

import { ArrowRight, Building2, FolderKanban, Gauge, Plus, Power, RotateCcw } from "lucide-react";
import { FormEvent, useEffect, useRef, useState } from "react";

import { useProjectWorkspace } from "@/components/ProjectContext";
import { StatefulLink } from "@/components/StatefulLink";
import { WorkspaceHeader } from "@/components/WorkspaceHeader";
import { ConfirmDialog } from "@/components/feedback/ConfirmDialog";
import { ModalDialog } from "@/components/feedback/ModalDialog";
import { Project, apiGet, apiPatch, apiPost } from "@/lib/api";

export default function ProjectsPage() {
  const { projects, projectId, refreshProjects, selectProject } = useProjectWorkspace();
  const [message, setMessage] = useState("");
  const [formError, setFormError] = useState("");
  const [institutions, setInstitutions] = useState<Array<{ id: number; institution_name: string }>>([]);
  const [createOpen, setCreateOpen] = useState(false);
  const [discardOpen, setDiscardOpen] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [creating, setCreating] = useState(false);
  const [lifecycle, setLifecycle] = useState<{ project: Project; nextStatus: "active" | "suspended" } | null>(null);
  const [lifecycleBusy, setLifecycleBusy] = useState(false);
  const [actionError, setActionError] = useState("");
  const [canManageLifecycle, setCanManageLifecycle] = useState(false);
  const creationRequestId = useRef<string | null>(null);
  const activeCount = projects.filter((project) => (project.project_status || "active") === "active").length;
  const suspendedCount = projects.length - activeCount;

  useEffect(() => {
    apiGet<Array<{ id: number; institution_name: string }>>("/admin/institutions").then(setInstitutions).catch(() => setInstitutions([]));
    apiGet<{ capabilities?: { can_view_admin?: boolean } }>("/auth/me")
      .then((auth) => setCanManageLifecycle(Boolean(auth.capabilities?.can_view_admin)))
      .catch(() => setCanManageLifecycle(false));
  }, []);

  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (creating) return;
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    const requestId = creationRequestId.current || newProjectRequestId();
    creationRequestId.current = requestId;
    setFormError("");
    setCreating(true);
    try {
      await apiPost("/projects", {
        name: form.get("name"),
        institution_id: Number(form.get("institution_id")) || null,
        bank_name: form.get("bank_name"),
        description: form.get("description"),
        client_request_id: requestId
      });
      formElement.reset();
      creationRequestId.current = null;
      setMessage("项目已创建");
      setDirty(false);
      setCreateOpen(false);
      try {
        await refreshProjects();
      } catch {
        setActionError("项目已创建，但项目列表刷新失败，请手动刷新页面。");
      }
    } catch (error) {
      setFormError(error instanceof Error ? error.message : "创建失败");
    } finally {
      setCreating(false);
    }
  }

  function requestCloseCreate() {
    if (creating) return;
    if (dirty) { setDiscardOpen(true); return; }
    creationRequestId.current = null;
    setCreateOpen(false);
  }

  function openCreate() {
    setFormError("");
    creationRequestId.current = newProjectRequestId();
    setCreateOpen(true);
  }

  function requestLifecycle(project: Project) {
    setActionError("");
    setLifecycle({
      project,
      nextStatus: (project.project_status || "active") === "active" ? "suspended" : "active"
    });
  }

  async function changeLifecycle() {
    if (!lifecycle) return;
    setLifecycleBusy(true);
    setActionError("");
    try {
      await apiPatch<Project>(`/projects/${lifecycle.project.id}/status`, {
        project_status: lifecycle.nextStatus
      });
      if (lifecycle.nextStatus === "suspended" && projectId === lifecycle.project.id) {
        selectProject(null);
      }
      setMessage(lifecycle.nextStatus === "active" ? "项目已恢复" : "项目已停用，历史数据已保留");
      setLifecycle(null);
      await refreshProjects();
    } catch (error) {
      setActionError(error instanceof Error ? error.message : "项目状态更新失败");
      setLifecycle(null);
    } finally {
      setLifecycleBusy(false);
    }
  }

  return (
    <main>
      <WorkspaceHeader meta={suspendedCount ? `${activeCount} 个在用项目 · ${suspendedCount} 个已停用` : `${activeCount} 个一表通口径项目`} title="项目" actions={<button className="button-primary" onClick={openCreate} type="button"><Plus size={16} />新建项目</button>} />
      <div className="mx-auto max-w-[1400px] p-4 lg:p-6">
        {message ? <p className="mb-4 rounded-lg border border-line bg-white px-3 py-2 text-sm text-slate-600">{message}</p> : null}
        {actionError ? <p className="mb-4 rounded-lg border border-coral-200 bg-coral-50 px-3 py-2 text-sm text-coral-700" role="alert">{actionError}</p> : null}
        {projects.length ? (
          <section className="grid h-fit gap-4 md:grid-cols-2">
            {projects.map((project) => {
              const suspended = (project.project_status || "active") !== "active";
              return (
              <article className={`panel flex flex-col p-5 transition hover:shadow-pop ${suspended ? "bg-slate-50" : ""}`} key={project.id}>
                <div className="flex items-start justify-between gap-3">
                  <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-pine-50 text-pine-600">
                    <FolderKanban size={18} />
                  </span>
                  <div className="flex flex-wrap justify-end gap-2">{suspended ? <span className="badge-neutral">已停用</span> : null}{project.bank_name ? (
                    <span className="badge-neutral">
                      <Building2 size={12} />
                      {project.bank_name}
                    </span>
                  ) : null}</div>
                </div>
                <h3 className="mt-3 text-base font-semibold text-ink">{project.name}</h3>
                <p className="mt-1 flex-1 text-sm leading-relaxed text-slate-500">{project.description || "暂无项目说明"}</p>
                {!suspended ? <div className="mt-4 flex flex-wrap gap-2 border-t border-line pt-4">
                  <StatefulLink className="button-secondary" href={`/projects/${project.id}/onboarding`} onClick={() => selectProject(project.id)}>
                    初始化
                  </StatefulLink>
                  <StatefulLink className="button-secondary" href={`/projects/${project.id}/readiness`} onClick={() => selectProject(project.id)}>
                    <Gauge size={15} />
                    准备度
                  </StatefulLink>
                  <StatefulLink className="button-primary ml-auto" href={`/projects/${project.id}/dashboard`} onClick={() => selectProject(project.id)}>
                    工作台
                    <ArrowRight size={15} />
                  </StatefulLink>
                  {canManageLifecycle ? <button className="button-secondary" onClick={() => requestLifecycle(project)} type="button"><Power size={15} />停用项目</button> : null}
                </div> : <div className="mt-4 flex items-center justify-between gap-3 border-t border-line pt-4"><p className="text-xs text-slate-500">历史资料、版本、审核及交付记录全部保留。</p>{canManageLifecycle ? <button className="button-secondary shrink-0" onClick={() => requestLifecycle(project)} type="button"><RotateCcw size={15} />恢复项目</button> : null}</div>}
              </article>
              );
            })}
          </section>
        ) : (
          <div className="empty-state h-fit">
            <FolderKanban className="text-slate-300" size={28} />
            <p>还没有项目，从右上角创建第一个一表通口径项目</p>
            <button className="button-primary" onClick={openCreate} type="button"><Plus size={16} />新建项目</button>
          </div>
        )}
      </div>
      <ModalDialog description="项目是权限、数据资产和报送任务的隔离边界。" onClose={requestCloseCreate} open={createOpen} title="新建项目">
        <form className="space-y-4" onChange={() => setDirty(true)} onSubmit={create}>
          {formError ? <p className="rounded-lg border border-coral-200 bg-coral-50 px-3 py-2 text-sm text-coral-700" role="alert">{formError}</p> : null}
          <input className="control" name="name" placeholder="项目名称" required />
          <select className="control" name="institution_id" required><option value="">选择所属机构</option>{institutions.map((item) => <option key={item.id} value={item.id}>{item.institution_name}</option>)}</select>
          <input className="control" name="bank_name" placeholder="机构名称（脱敏）" />
          <textarea className="control min-h-24" name="description" placeholder="项目说明" />
          <div className="flex justify-end gap-2"><button className="button-secondary" disabled={creating} onClick={requestCloseCreate} type="button">取消</button><button className="button-primary" disabled={creating} type="submit"><Plus size={16} />{creating ? "创建中…" : "创建项目"}</button></div>
        </form>
      </ModalDialog>
      <ConfirmDialog danger confirmText="放弃修改" description="尚未保存的项目信息将丢失。" onCancel={() => setDiscardOpen(false)} onConfirm={() => { creationRequestId.current = null; setDiscardOpen(false); setDirty(false); setCreateOpen(false); }} open={discardOpen} title="放弃新建项目？" />
      <ConfirmDialog
        busy={lifecycleBusy}
        confirmText={lifecycle?.nextStatus === "active" ? "恢复项目" : "停用项目"}
        danger={lifecycle?.nextStatus !== "active"}
        description={lifecycle?.nextStatus === "active"
          ? "恢复后项目会重新出现在项目切换器，并恢复原有权限和业务数据。"
          : "项目将退出正常项目选择和作业入口。机构、权限、资料、版本、审核及交付记录全部保留，可随时恢复。"}
        onCancel={() => setLifecycle(null)}
        onConfirm={changeLifecycle}
        open={Boolean(lifecycle)}
        title={lifecycle?.nextStatus === "active" ? "恢复项目？" : "停用项目？"}
      />
    </main>
  );
}

function newProjectRequestId() {
  const cryptoApi = globalThis.crypto as Crypto | undefined;
  if (typeof cryptoApi?.randomUUID === "function") return cryptoApi.randomUUID();
  const bytes = new Uint8Array(16);
  if (typeof cryptoApi?.getRandomValues === "function") {
    cryptoApi.getRandomValues(bytes);
    return Array.from(bytes, (value) => value.toString(16).padStart(2, "0")).join("");
  }
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2).padEnd(12, "0")}`;
}

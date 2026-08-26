"use client";

import { ArrowRight, Building2, FolderKanban, Gauge, Plus } from "lucide-react";
import { FormEvent, useEffect, useState } from "react";

import { useProjectWorkspace } from "@/components/ProjectContext";
import { StatefulLink } from "@/components/StatefulLink";
import { WorkspaceHeader } from "@/components/WorkspaceHeader";
import { ConfirmDialog } from "@/components/feedback/ConfirmDialog";
import { ModalDialog } from "@/components/feedback/ModalDialog";
import { apiGet, apiPost } from "@/lib/api";

export default function ProjectsPage() {
  const { projects, refreshProjects, selectProject } = useProjectWorkspace();
  const [message, setMessage] = useState("");
  const [formError, setFormError] = useState("");
  const [institutions, setInstitutions] = useState<Array<{ id: number; institution_name: string }>>([]);
  const [createOpen, setCreateOpen] = useState(false);
  const [discardOpen, setDiscardOpen] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [creating, setCreating] = useState(false);

  useEffect(() => {
    apiGet<Array<{ id: number; institution_name: string }>>("/admin/institutions").then(setInstitutions).catch(() => setInstitutions([]));
  }, []);

  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setFormError("");
    setCreating(true);
    try {
      await apiPost("/projects", {
        name: form.get("name"),
        institution_id: Number(form.get("institution_id")) || null,
        bank_name: form.get("bank_name"),
        description: form.get("description")
      });
      event.currentTarget.reset();
      setMessage("项目已创建");
      setDirty(false);
      setCreateOpen(false);
      await refreshProjects();
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
      <WorkspaceHeader meta={`${projects.length} 个一表通口径项目`} title="项目" actions={<button className="button-primary" onClick={openCreate} type="button"><Plus size={16} />新建项目</button>} />
      <div className="mx-auto max-w-[1400px] p-4 lg:p-6">
        {message ? <p className="mb-4 rounded-lg border border-line bg-white px-3 py-2 text-sm text-slate-600">{message}</p> : null}
        {projects.length ? (
          <section className="grid h-fit gap-4 md:grid-cols-2">
            {projects.map((project) => (
              <article className="panel flex flex-col p-5 transition hover:shadow-pop" key={project.id}>
                <div className="flex items-start justify-between gap-3">
                  <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-pine-50 text-pine-600">
                    <FolderKanban size={18} />
                  </span>
                  {project.bank_name ? (
                    <span className="badge-neutral">
                      <Building2 size={12} />
                      {project.bank_name}
                    </span>
                  ) : null}
                </div>
                <h3 className="mt-3 text-base font-semibold text-ink">{project.name}</h3>
                <p className="mt-1 flex-1 text-sm leading-relaxed text-slate-500">{project.description || "暂无项目说明"}</p>
                <div className="mt-4 flex flex-wrap gap-2 border-t border-line pt-4">
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
                </div>
              </article>
            ))}
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
      <ConfirmDialog danger confirmText="放弃修改" description="尚未保存的项目信息将丢失。" onCancel={() => setDiscardOpen(false)} onConfirm={() => { setDiscardOpen(false); setDirty(false); setCreateOpen(false); }} open={discardOpen} title="放弃新建项目？" />
    </main>
  );
}

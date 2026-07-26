"use client";

import { ArrowRight, Building2, FolderKanban, Gauge, Plus } from "lucide-react";
import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";

import { useProjectWorkspace } from "@/components/ProjectContext";
import { WorkspaceHeader } from "@/components/WorkspaceHeader";
import { apiGet, apiPost } from "@/lib/api";

export default function ProjectsPage() {
  const { projects, refreshProjects, selectProject } = useProjectWorkspace();
  const [message, setMessage] = useState("");
  const [institutions, setInstitutions] = useState<Array<{ id: number; institution_name: string }>>([]);

  useEffect(() => {
    apiGet<Array<{ id: number; institution_name: string }>>("/admin/institutions").then(setInstitutions).catch(() => setInstitutions([]));
  }, []);

  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    try {
      await apiPost("/projects", {
        name: form.get("name"),
        institution_id: Number(form.get("institution_id")) || null,
        bank_name: form.get("bank_name"),
        description: form.get("description")
      });
      event.currentTarget.reset();
      setMessage("项目已创建");
      await refreshProjects();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "创建失败");
    }
  }

  return (
    <main>
      <WorkspaceHeader meta={`${projects.length} 个一表通口径项目`} title="项目" />
      <div className="mx-auto grid max-w-[1400px] gap-5 p-4 lg:grid-cols-[340px_1fr] lg:p-6">
        <form className="panel h-fit" onSubmit={create}>
          <div className="panel-header">
            <h2 className="text-[15px] font-semibold text-ink">新建项目</h2>
          </div>
          <div className="panel-body space-y-3">
            <input className="control" name="name" placeholder="项目名称" required />
            <select className="control" name="institution_id" required>
              <option value="">选择所属机构</option>
              {institutions.map((item) => (
                <option key={item.id} value={item.id}>{item.institution_name}</option>
              ))}
            </select>
            <input className="control" name="bank_name" placeholder="机构名称（脱敏）" />
            <textarea className="control min-h-24" name="description" placeholder="项目说明" />
            <button className="button-primary w-full" type="submit">
              <Plus size={16} />
              新建
            </button>
            {message ? <p className="text-sm text-slate-600">{message}</p> : null}
          </div>
        </form>

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
                  <Link className="button-secondary" href={`/projects/${project.id}/onboarding`} onClick={() => selectProject(project.id)}>
                    初始化
                  </Link>
                  <Link className="button-secondary" href={`/projects/${project.id}/readiness`} onClick={() => selectProject(project.id)}>
                    <Gauge size={15} />
                    准备度
                  </Link>
                  <Link className="button-primary ml-auto" href={`/projects/${project.id}/dashboard`} onClick={() => selectProject(project.id)}>
                    工作台
                    <ArrowRight size={15} />
                  </Link>
                </div>
              </article>
            ))}
          </section>
        ) : (
          <div className="empty-state h-fit">
            <FolderKanban className="text-slate-300" size={28} />
            <p>还没有项目，先在左侧创建第一个一表通口径项目</p>
          </div>
        )}
      </div>
    </main>
  );
}

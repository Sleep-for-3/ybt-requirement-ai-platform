"use client";

import { Plus } from "lucide-react";
import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";

import { useProjectWorkspace } from "@/components/ProjectContext";
import { WorkspaceHeader } from "@/components/WorkspaceHeader";
import { apiGet, apiPost } from "@/lib/api";

export default function ProjectsPage() {
  const { projects, refreshProjects, selectProject } = useProjectWorkspace();
  const [message, setMessage] = useState("");
  const [institutions,setInstitutions]=useState<Array<{id:number;institution_name:string}>>([]);
  useEffect(()=>{apiGet<Array<{id:number;institution_name:string}>>("/admin/institutions").then(setInstitutions).catch(()=>setInstitutions([]));},[]);

  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    try {
      await apiPost("/projects", { name: form.get("name"), institution_id: Number(form.get("institution_id"))||null, bank_name: form.get("bank_name"), description: form.get("description") });
      event.currentTarget.reset();
      setMessage("项目已创建");
      await refreshProjects();
    } catch (error) { setMessage(error instanceof Error ? error.message : "创建失败"); }
  }

  return (
    <main>
      <WorkspaceHeader title="项目" meta={`${projects.length} 个一表通口径项目`} />
      <div className="mx-auto grid max-w-[1400px] gap-5 p-4 lg:grid-cols-[360px_1fr] lg:p-6">
        <form className="panel h-fit p-4" onSubmit={create}>
          <h2 className="text-sm font-semibold">新建项目</h2>
          <div className="mt-4 space-y-3">
            <input className="control" name="name" placeholder="项目名称" required />
            <select className="control" name="institution_id" required><option value="">选择所属机构</option>{institutions.map(item=><option value={item.id} key={item.id}>{item.institution_name}</option>)}</select>
            <input className="control" name="bank_name" placeholder="机构名称（脱敏）" />
            <textarea className="control min-h-24" name="description" placeholder="项目说明" />
            <button className="button-primary w-full" type="submit"><Plus size={16} />新建</button>
          </div>
          {message ? <p className="mt-3 text-sm text-slate-600">{message}</p> : null}
        </form>
        <section className="panel overflow-hidden">
          <div className="grid grid-cols-[1fr_180px_220px] border-b border-line bg-slate-50 px-4 py-2 text-xs font-semibold text-slate-500">
            <span>项目</span><span>机构</span><span>操作</span>
          </div>
          {projects.map((project) => (
            <div className="grid grid-cols-[1fr_180px_220px] items-center border-b border-line px-4 py-3 text-sm last:border-0" key={project.id}>
              <div><div className="font-medium">{project.name}</div><div className="mt-1 text-xs text-slate-500">{project.description || "-"}</div></div>
              <span>{project.bank_name || "-"}</span>
              <div className="flex gap-2"><Link className="button-secondary" href={`/projects/${project.id}/onboarding`} onClick={() => selectProject(project.id)}>初始化</Link><Link className="button-secondary" href={`/projects/${project.id}/readiness`} onClick={() => selectProject(project.id)}>准备度</Link></div>
            </div>
          ))}
        </section>
      </div>
    </main>
  );
}

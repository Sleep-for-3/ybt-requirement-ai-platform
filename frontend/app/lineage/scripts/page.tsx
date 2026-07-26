"use client";

import { FileCode2, GitPullRequest, Upload } from "lucide-react";
import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";

import { useProjectWorkspace } from "@/components/ProjectContext";
import { WorkspaceHeader } from "@/components/WorkspaceHeader";
import { ScriptFile, apiGet, apiPost, uploadForm } from "@/lib/api";

type Repo = {
  id: number;
  repository_name: string;
  repository_type: string;
  repository_url: string;
  default_branch: string;
  last_sync_commit?: string | null;
  last_synced_at?: string | null;
};

export default function Page() {
  const { projectId } = useProjectWorkspace();
  const [items, setItems] = useState<ScriptFile[]>([]);
  const [repos, setRepos] = useState<Repo[]>([]);
  const [message, setMessage] = useState("");

  async function load() {
    if (!projectId) return;
    const [a, b] = await Promise.all([
      apiGet<ScriptFile[]>(`/projects/${projectId}/scripts`),
      apiGet<Repo[]>(`/projects/${projectId}/code-repositories`)
    ]);
    setItems(a);
    setRepos(b);
  }

  useEffect(() => {
    void load();
  }, [projectId]);

  async function upload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!projectId) return;
    const form = new FormData(event.currentTarget);
    const file = form.get("file") as File;
    const path = file.name.toLowerCase().endsWith(".zip")
      ? `/projects/${projectId}/scripts/upload-zip`
      : `/projects/${projectId}/scripts/upload`;
    try {
      const result = await uploadForm<{ status?: string; parse_status?: string }>(path, form);
      setMessage(`摄取完成：${result.status || result.parse_status || "completed"}`);
      await load();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "上传失败");
    }
  }

  async function createRepo(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!projectId) return;
    const form = new FormData(event.currentTarget);
    await apiPost(`/projects/${projectId}/code-repositories`, Object.fromEntries(form));
    setMessage("仓库配置已保存（凭据仅引用环境变量）");
    await load();
  }

  async function sync(id: number) {
    const result = await apiPost<{ status: string; result: Record<string, unknown> }>(`/code-repositories/${id}/sync`, {});
    setMessage(`同步 ${result.status}: ${JSON.stringify(result.result)}`);
    await load();
  }

  return (
    <main>
      <WorkspaceHeader title="脚本仓库" meta={`${items.length} 个脚本 / ${repos.length} 个 Git 仓库`} />
      <div className="mx-auto max-w-7xl space-y-5 p-4 lg:p-6">
        <div className="grid gap-5 lg:grid-cols-2">
          <form className="panel h-fit" onSubmit={upload}>
            <div className="panel-header">
              <h2 className="text-[15px] font-semibold text-ink">手工或 ZIP 导入</h2>
            </div>
            <div className="panel-body space-y-3">
              <input className="control" name="file" type="file" accept=".sql,.sh,.ksh,.bash,.txt,.zip" required />
              <input className="control" name="relative_path" placeholder="相对路径（ZIP 可留空）" />
              <select className="control" name="dialect">
                <option value="">自动/通用</option>
                <option value="sqlite">SQLite</option>
                <option value="postgres">PostgreSQL</option>
                <option value="mysql">MySQL</option>
                <option value="oracle">Oracle 语法</option>
              </select>
              <button className="button-primary w-full">
                <Upload size={16} />
                安全摄取
              </button>
            </div>
          </form>

          <form className="panel h-fit" onSubmit={createRepo}>
            <div className="panel-header">
              <h2 className="text-[15px] font-semibold text-ink">Git 仓库（bare clone，不 checkout）</h2>
            </div>
            <div className="panel-body grid gap-3 sm:grid-cols-2">
              <input className="control" name="repository_name" placeholder="仓库名称" required />
              <select className="control" name="repository_type">
                <option value="git_repository">Git repository</option>
                <option value="github">GitHub</option>
                <option value="gitee">Gitee</option>
              </select>
              <input className="control sm:col-span-2" name="repository_url" placeholder="仓库 URL 或银行内网本地路径" required />
              <input className="control" name="default_branch" defaultValue="main" />
              <input className="control" name="credential_env_name" placeholder="凭据环境变量名（可选）" />
              <button className="button-primary sm:col-span-2">
                <GitPullRequest size={16} />
                保存仓库
              </button>
            </div>
          </form>
        </div>

        {message ? (
          <p className="rounded-lg border border-line bg-white px-3 py-2 text-sm text-slate-600">{message}</p>
        ) : null}

        <section className="panel overflow-hidden">
          <div className="panel-header">
            <h2 className="text-[15px] font-semibold text-ink">Git 同步</h2>
          </div>
          {repos.length ? (
            <>
              <div className="grid-head grid grid-cols-[minmax(0,1fr)_96px]">
                <span>仓库</span>
                <span className="text-right">操作</span>
              </div>
              {repos.map((repo) => (
                <div className="grid-row grid grid-cols-[minmax(0,1fr)_96px] items-center" key={repo.id}>
                  <div>
                    <strong className="text-ink">{repo.repository_name}</strong>
                    <div className="text-xs text-slate-500">
                      {repo.default_branch} · {repo.last_sync_commit?.slice(0, 12) || "未同步"}
                    </div>
                  </div>
                  <button className="button-secondary justify-self-end" onClick={() => sync(repo.id)}>
                    同步
                  </button>
                </div>
              ))}
            </>
          ) : (
            <div className="panel-body">
              <div className="empty-state">
                <GitPullRequest className="text-slate-300" size={28} />
                <p>还没有 Git 仓库，可在上方保存仓库配置后受控同步</p>
              </div>
            </div>
          )}
        </section>

        <section className="panel overflow-hidden">
          <div className="panel-header">
            <h2 className="text-[15px] font-semibold text-ink">脚本版本</h2>
          </div>
          {items.length ? (
            <>
              <div className="grid-head grid grid-cols-[minmax(0,1fr)_110px]">
                <span>脚本</span>
                <span className="text-right">状态</span>
              </div>
              {items.map((item) => (
                <Link
                  className="grid-row grid grid-cols-[minmax(0,1fr)_110px] items-center"
                  href={`/lineage/scripts/${item.id}`}
                  key={item.id}
                >
                  <div>
                    <strong className="text-ink">{item.relative_path}</strong>
                    <div className="text-xs text-slate-500">
                      {item.file_type} · v{item.current_version_no}
                    </div>
                  </div>
                  <span className="justify-self-end">
                    <span className={item.enabled ? "badge-success" : "badge-danger"}>
                      {item.enabled ? "enabled" : "deleted"}
                    </span>
                  </span>
                </Link>
              ))}
            </>
          ) : (
            <div className="panel-body">
              <div className="empty-state">
                <FileCode2 className="text-slate-300" size={28} />
                <p>还没有脚本，先上传 SQL / Shell / ZIP 或同步 Git 仓库</p>
              </div>
            </div>
          )}
        </section>
      </div>
    </main>
  );
}

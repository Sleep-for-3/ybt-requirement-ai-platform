"use client";

import { FileCode2, GitPullRequest, Upload } from "lucide-react";
import { FormEvent, useEffect, useState } from "react";

import { useProjectWorkspace } from "@/components/ProjectContext";
import { StatefulLink } from "@/components/StatefulLink";
import { WorkspaceHeader } from "@/components/WorkspaceHeader";
import { AsyncActionButton } from "@/components/feedback/AsyncActionButton";
import { JobProgressPanel } from "@/components/jobs/JobProgressPanel";
import { useAsyncAction } from "@/hooks/useAsyncAction";
import { useJobPolling } from "@/hooks/useJobPolling";
import { BackgroundJobSummary, ScriptFile, apiGet, apiPost, uploadForm } from "@/lib/api";

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
  const [activeJob, setActiveJob] = useState<BackgroundJobSummary | null>(null);
  const ingestAction = useAsyncAction<{ status?: string; parse_status?: string } | BackgroundJobSummary>({
    successMessage: (result) => "job_type" in result
      ? result.deduplicated ? "相同脚本摄取任务已存在，已打开当前任务" : "脚本摄取任务已提交"
      : "脚本摄取完成"
  });
  const repoAction = useAsyncAction<Record<string, unknown>>({ successMessage: "仓库配置已保存" });
  const syncAction = useAsyncAction<BackgroundJobSummary>({
    successMessage: (job) => job.deduplicated ? "相同仓库同步正在执行，已打开当前任务" : "仓库同步任务已提交"
  });
  const polledJob = useJobPolling(activeJob?.id, { initialJob: activeJob, onTerminal: load });

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
    const result = await ingestAction.run(() => uploadForm<{ status?: string; parse_status?: string } | BackgroundJobSummary>(path, form));
    if (result) {
      if ("job_type" in result) {
        setActiveJob(result);
        setMessage("文件已保存，正在后台解析和分析血缘");
      } else {
        setMessage(`摄取完成：${String(result.status || result.parse_status || "completed")}`);
      }
      event.currentTarget.reset();
      await load();
    }
  }

  async function createRepo(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!projectId) return;
    const form = new FormData(event.currentTarget);
    const result = await repoAction.run(() => apiPost<Record<string, unknown>>(`/projects/${projectId}/code-repositories`, Object.fromEntries(form)));
    if (result) {
      event.currentTarget.reset();
      setMessage("仓库配置已保存（凭据仅引用环境变量）");
      await load();
    }
  }

  async function sync(id: number) {
    const result = await syncAction.run(() => apiPost<BackgroundJobSummary>(`/code-repositories/${id}/sync`, {}));
    if (result) {
      setActiveJob(result);
      setMessage(result.deduplicated ? "已打开正在执行的仓库同步任务" : "仓库同步任务已创建");
    }
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
              <AsyncActionButton actionStatus={ingestAction.status} className="button-primary w-full" loadingText="正在上传…">
                <Upload size={16} />
                安全摄取
              </AsyncActionButton>
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
              <AsyncActionButton actionStatus={repoAction.status} className="button-primary sm:col-span-2">
                <GitPullRequest size={16} />
                保存仓库
              </AsyncActionButton>
            </div>
          </form>
        </div>

        {message ? (
          <p className="rounded-lg border border-line bg-white px-3 py-2 text-sm text-slate-600">{message}</p>
        ) : null}
        {polledJob ? <JobProgressPanel job={polledJob} resultHref="/lineage/scripts" /> : null}

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
                  <AsyncActionButton actionStatus={syncAction.status} className="button-secondary justify-self-end" loadingText="提交同步…" onClick={() => void sync(repo.id)}>
                    同步
                  </AsyncActionButton>
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
                <StatefulLink
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
                </StatefulLink>
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

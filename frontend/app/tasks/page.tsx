"use client";

import { ClipboardList, Play, Send, Terminal } from "lucide-react";
import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";

import { useProjectWorkspace } from "@/components/ProjectContext";
import { WorkspaceHeader } from "@/components/WorkspaceHeader";
import { NaturalLanguageTask, NaturalLanguageTaskCreateResponse, apiGet, apiPost } from "@/lib/api";

function statusBadge(status: string) {
  if (["approved", "success", "completed", "enabled"].includes(status)) return "badge-success";
  if (["failed", "rejected", "error"].includes(status)) return "badge-danger";
  if (["pending", "running", "processing"].includes(status)) return "badge-warning";
  if (["parsed", "draft", "info"].includes(status)) return "badge-info";
  return "badge-neutral";
}

export default function Page() {
  const { projectId } = useProjectWorkspace();
  const [items, setItems] = useState<NaturalLanguageTask[]>([]);
  const [message, setMessage] = useState("");
  const [creating, setCreating] = useState(false);
  const [reviewTasks, setReviewTasks] = useState<Array<{ id: number; step_key: string; status: string; due_at?: string | null }>>([]);

  async function reload() {
    if (projectId) setItems(await apiGet(`/projects/${projectId}/nl-tasks`));
    try {
      setReviewTasks(await apiGet("/me/tasks"));
    } catch {
      setReviewTasks([]);
    }
  }

  useEffect(() => {
    void reload();
  }, [projectId]);

  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!projectId || creating) return;
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    setCreating(true);
    try {
      const result = await apiPost<NaturalLanguageTaskCreateResponse>("/nl-tasks", { project_id: projectId, text: form.get("text") });
      formElement.reset();
      setMessage(result.message);
      await reload();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "创建失败");
    } finally {
      setCreating(false);
    }
  }

  async function run(id: number) {
    try {
      await apiPost(`/nl-tasks/${id}/run`, {});
      setMessage("安全查询任务已执行");
      await reload();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "执行失败");
    }
  }

  return (
    <main>
      <WorkspaceHeader title="任务中心" meta="审核待办与自然语言安全查询" />
      <div className="mx-auto max-w-[1400px] space-y-5 p-4 lg:p-6">
        <section className="panel overflow-hidden">
          <div className="panel-header">
            <h2 className="text-[15px] font-semibold text-ink">我的审核待办</h2>
          </div>
          {reviewTasks.length ? (
            <div>
              <div className="grid-head grid grid-cols-[1fr_140px_200px_100px] gap-3">
                <span>步骤</span>
                <span>状态</span>
                <span>到期时间</span>
                <span className="text-right">操作</span>
              </div>
              {reviewTasks.map((item) => (
                <div className="grid-row grid grid-cols-[1fr_140px_200px_100px] items-center gap-3" key={item.id}>
                  <span className="font-medium text-ink">{item.step_key}</span>
                  <span>
                    <span className={statusBadge(item.status)}>{item.status}</span>
                  </span>
                  <span className="text-slate-500">{item.due_at || "未设置到期时间"}</span>
                  <span className="text-right">
                    <Link className="button-primary" href={`/tasks/${item.id}`}>
                      处理
                    </Link>
                  </span>
                </div>
              ))}
            </div>
          ) : (
            <div className="panel-body">
              <div className="empty-state">
                <ClipboardList className="text-slate-300" size={28} />
                <p>暂无审核待办，评审流程流转到你时会显示在这里</p>
              </div>
            </div>
          )}
        </section>

        <div className="grid gap-5 lg:grid-cols-[420px_1fr]">
          <form className="panel h-fit" onSubmit={create}>
            <div className="panel-header">
              <h2 className="text-[15px] font-semibold text-ink">自然语言安全查询</h2>
            </div>
            <div className="panel-body space-y-3">
              <p className="text-sm leading-relaxed text-slate-500">
                此处仅对已配置的数据源执行受限 SQL 查询，不会检索知识库。制度、口径和监管答疑请使用
                <Link className="ml-1 font-medium text-pine-600 hover:text-pine-700" href="/knowledge/ask">
                  有证据问答
                </Link>
                。
              </p>
              <textarea className="control min-h-28" name="text" placeholder="例如：使用脱敏测试数据源查询客户表证件类型字段的空值率" required />
              <button className="button-primary w-full" disabled={creating}>
                <Send size={16} />
                {creating ? "正在创建…" : "创建任务"}
              </button>
              {message ? (
                <p className="rounded-lg border border-line bg-white px-3 py-2 text-sm text-slate-600">{message}</p>
              ) : null}
            </div>
          </form>

          <section className="panel h-fit overflow-hidden">
            <div className="panel-header">
              <h2 className="text-[15px] font-semibold text-ink">查询任务</h2>
            </div>
            {items.length ? (
              items.map((item) => (
                <div className="flex items-start justify-between gap-4 border-b border-line p-4 last:border-0" key={item.id}>
                  <div>
                    <div className="font-medium text-ink">{item.raw_text}</div>
                    <div className="mt-1.5 flex flex-wrap items-center gap-2">
                      <span className={statusBadge(item.status)}>{item.status}</span>
                      <span className="text-sm text-slate-500">{item.datasource_name || "数据源待识别"}</span>
                    </div>
                    {item.error_message ? <p className="mt-1.5 text-sm text-slate-500">{item.error_message}</p> : null}
                  </div>
                  <button className="button-secondary" disabled={item.status === "completed"} onClick={() => run(item.id)}>
                    <Play size={16} />
                    执行
                  </button>
                </div>
              ))
            ) : (
              <div className="panel-body">
                <div className="empty-state">
                  <Terminal className="text-slate-300" size={28} />
                  <p>还没有查询任务，在左侧用自然语言描述一次安全查询</p>
                </div>
              </div>
            )}
          </section>
        </div>
      </div>
    </main>
  );
}

"use client";

import { History } from "lucide-react";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { WorkspaceHeader } from "@/components/WorkspaceHeader";
import { apiGet, apiPost } from "@/lib/api";

type Task = {
  id: number;
  step_key: string;
  status: string;
  target_type: string;
  target_id: number;
  decisions: Array<{ decision: string; comment?: string | null }>;
};

function decisionBadge(decision: string) {
  if (["approve", "approved", "success", "completed"].includes(decision)) return "badge-success";
  if (["reject", "rejected", "failed", "error"].includes(decision)) return "badge-danger";
  if (["pending", "running", "processing"].includes(decision)) return "badge-warning";
  return "badge-neutral";
}

export default function Page() {
  const params = useParams<{ taskId: string }>();
  const taskId = params.taskId;
  const [item, setItem] = useState<Task | null>(null);
  const [msg, setMsg] = useState("");

  async function reload() {
    setItem(await apiGet(`/review-tasks/${taskId}`));
  }

  useEffect(() => {
    void reload();
  }, [taskId]);

  async function decide(formElement: HTMLFormElement, action: string) {
    const form = new FormData(formElement);
    try {
      await apiPost(`/review-tasks/${taskId}/${action}`, {
        comment: form.get("comment"),
        return_to_step: form.get("return_to_step") || null
      });
      setMsg("处理完成");
      await reload();
    } catch (error) {
      setMsg(error instanceof Error ? error.message : "处理失败");
    }
  }

  return (
    <main>
      <WorkspaceHeader title={`任务 #${taskId}`} meta={item ? `${item.step_key} · ${item.status}` : "加载中"} />
      <div className="mx-auto grid max-w-5xl gap-5 p-4 lg:grid-cols-2 lg:p-6">
        <section className="panel h-fit">
          <div className="panel-header">
            <h2 className="text-[15px] font-semibold text-ink">处理对象</h2>
          </div>
          <div className="panel-body">
            <p className="text-sm text-slate-600">
              {item?.target_type} #{item?.target_id}
            </p>
            <div className="mt-4 space-y-2">
              {item?.decisions?.length ? (
                item.decisions.map((decision, index) => (
                  <div className="flex items-start gap-2 rounded-lg bg-slate-50 p-3 text-sm" key={index}>
                    <span className={decisionBadge(decision.decision)}>{decision.decision}</span>
                    <span className="text-slate-600">{decision.comment || "无意见"}</span>
                  </div>
                ))
              ) : item ? (
                <div className="empty-state">
                  <History className="text-slate-300" size={28} />
                  <p>暂无处理记录，提交审核意见后会显示在这里</p>
                </div>
              ) : null}
            </div>
          </div>
        </section>

        <form className="panel h-fit">
          <div className="panel-header">
            <h2 className="text-[15px] font-semibold text-ink">处理意见</h2>
          </div>
          <div className="panel-body">
            <textarea className="control min-h-32" name="comment" placeholder="审核意见或退回原因" />
            <input className="control mt-3" name="return_to_step" placeholder="退回步骤（可选）" />
            <div className="mt-3 flex gap-2">
              <button
                className="button-primary"
                type="button"
                onClick={(event) => {
                  const form = event.currentTarget.form;
                  if (form) void decide(form, "approve");
                }}
              >
                通过
              </button>
              <button
                className="button-danger"
                type="button"
                onClick={(event) => {
                  const form = event.currentTarget.form;
                  if (form) void decide(form, "reject");
                }}
              >
                驳回
              </button>
            </div>
            {msg ? (
              <p className="mt-3 rounded-lg border border-line bg-white px-3 py-2 text-sm text-slate-600">{msg}</p>
            ) : null}
          </div>
        </form>
      </div>
    </main>
  );
}

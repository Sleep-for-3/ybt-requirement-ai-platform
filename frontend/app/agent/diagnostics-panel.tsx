"use client";

import { useQuery } from "@tanstack/react-query";
import { ChevronDown, Terminal } from "lucide-react";
import { useState } from "react";

import { apiGet } from "@/lib/api";

type DiagnosticCall = {
  id: number;
  tool_key?: string | null;
  status?: string | null;
  attempt?: number | null;
  risk_level?: string | null;
  read_only?: boolean | null;
  duration_ms?: number | null;
  model_name?: string | null;
  prompt_version?: string | null;
  provider_type?: string | null;
  token_usage?: Record<string, unknown> | null;
  degraded_path?: string | null;
  failure_reason?: string | null;
  evidence_count?: number | null;
  input_summary?: Record<string, unknown> | null;
};

type DiagnosticStep = {
  id: number;
  step_key?: string | null;
  tool_key?: string | null;
  status?: string | null;
  order_index?: number | null;
  attempt_count?: number | null;
  human_gate_key?: string | null;
  review_task_id?: number | null;
  gap_codes?: string[] | null;
  evidence_count?: number | null;
  error_code?: string | null;
  error_message?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
  tool_calls?: DiagnosticCall[];
};

export type AgentDiagnostics = {
  task?: {
    id?: number;
    status?: string | null;
    scenario_key?: string | null;
    plan_version?: number | null;
    background_job_id?: number | null;
    retry_count?: number | null;
    replanning_count?: number | null;
    error_code?: string | null;
    error_message?: string | null;
    model_metadata?: Record<string, unknown> | null;
  };
  plan?: {
    planner_source?: string | null;
    degraded_reason?: string | null;
    planner_attempts?: number | null;
    plan_hash?: string | null;
    validation_errors?: unknown;
  } | null;
  steps?: DiagnosticStep[];
};

const CELL = "border-b border-line px-3 py-2 align-top text-xs text-slate-700";

function jsonText(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "string") return value;
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

/**
 * 技术诊断：工具名、模型、Prompt、Token、原始异常。
 * 服务端用 audit.read 单独鉴权；这个组件只是“在有权时提供查看入口”，
 * 前端隐藏不是安全边界。
 */
export function DiagnosticsPanel({ taskId, canRead }: { taskId: number; canRead: boolean }) {
  const [open, setOpen] = useState(false);
  const diagnostics = useQuery({
    queryKey: ["agent-diagnostics", taskId],
    enabled: open && canRead,
    retry: false,
    queryFn: ({ signal }) => apiGet<AgentDiagnostics>(`/agent/tasks/${taskId}/diagnostics`, { signal }),
  });

  if (!canRead) return null;

  const data = diagnostics.data;
  return (
    <section className="panel" id="agent-diagnostics">
      <button aria-expanded={open} className="panel-header flex w-full items-center justify-between gap-2 text-left"
        onClick={() => setOpen((value) => !value)} type="button">
        <span className="inline-flex items-center gap-2 text-sm font-semibold text-ink">
          <Terminal aria-hidden size={15} />技术诊断（审计视角）
        </span>
        <span className="inline-flex items-center gap-1 text-xs text-slate-500">
          {open ? "收起" : "查看工具调用、模型与原始错误"}
          <ChevronDown aria-hidden className={open ? "rotate-180 transition-transform" : "transition-transform"} size={14} />
        </span>
      </button>
      {open ? (
        <div className="panel-body space-y-4">
          <p className="rounded-lg border border-line bg-mist/60 px-3 py-2 text-xs text-slate-600">
            以下内容仅供项目负责人与审计排查使用，不属于业务结论，不要直接引用到对外材料。
          </p>
          {diagnostics.isLoading ? <p className="text-sm text-slate-500">正在读取技术诊断…</p> : null}
          {diagnostics.isError ? (
            <p className="rounded-lg border border-coral-200 bg-coral-50 px-3 py-2 text-sm text-coral-700" role="alert">
              技术诊断读取失败，请稍后重试；如果持续失败，请确认本账号是否具备审计查看权限。
            </p>
          ) : null}
          {data ? (
            <>
              <dl className="grid gap-3 text-xs sm:grid-cols-3 lg:grid-cols-4">
                <div><dt className="text-slate-500">任务状态</dt><dd className="mt-1 font-mono text-slate-700">{data.task?.status || "—"}</dd></div>
                <div><dt className="text-slate-500">场景标识</dt><dd className="mt-1 font-mono text-slate-700">{data.task?.scenario_key || "—"}</dd></div>
                <div><dt className="text-slate-500">计划版本</dt><dd className="mt-1 font-mono text-slate-700">{data.task?.plan_version ?? "—"}</dd></div>
                <div><dt className="text-slate-500">后台任务</dt><dd className="mt-1 font-mono text-slate-700">{data.task?.background_job_id ?? "—"}</dd></div>
                <div><dt className="text-slate-500">失败码</dt><dd className="mt-1 font-mono text-slate-700">{data.task?.error_code || "—"}</dd></div>
                <div><dt className="text-slate-500">重试 / 重规划</dt><dd className="mt-1 font-mono text-slate-700">{data.task?.retry_count ?? 0} / {data.task?.replanning_count ?? 0}</dd></div>
                <div className="sm:col-span-2"><dt className="text-slate-500">计划来源</dt><dd className="mt-1 font-mono text-slate-700">{data.plan?.planner_source || "—"} · hash {data.plan?.plan_hash || "—"}</dd></div>
              </dl>
              {data.task?.error_message ? (
                <details>
                  <summary className="cursor-pointer text-xs font-medium text-coral-700">原始错误信息</summary>
                  <pre className="mt-2 max-h-56 overflow-auto whitespace-pre-wrap rounded-lg bg-slate-900 px-3 py-2 text-[11px] leading-5 text-slate-100">
                    {data.task.error_message}
                  </pre>
                </details>
              ) : null}
              {data.plan?.validation_errors ? (
                <details>
                  <summary className="cursor-pointer text-xs font-medium text-slate-700">计划校验错误</summary>
                  <pre className="mt-2 max-h-56 overflow-auto whitespace-pre-wrap rounded-lg bg-slate-900 px-3 py-2 text-[11px] leading-5 text-slate-100">
                    {jsonText(data.plan.validation_errors)}
                  </pre>
                </details>
              ) : null}
              <div className="overflow-x-auto">
                <table className="w-full min-w-[720px] border-collapse text-left">
                  <thead>
                    <tr className="bg-slate-50 text-[11px] font-semibold text-slate-500">
                      <th className={CELL}>步骤</th>
                      <th className={CELL}>工具</th>
                      <th className={CELL}>状态</th>
                      <th className={CELL}>尝试</th>
                      <th className={CELL}>模型 / Prompt</th>
                      <th className={CELL}>Token</th>
                      <th className={CELL}>耗时</th>
                      <th className={CELL}>降级 / 失败原因</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(data.steps || []).flatMap((step) => (
                      step.tool_calls?.length ? step.tool_calls.map((call) => (
                        <tr key={`${step.id}-${call.id}`}>
                          <td className={`${CELL} font-mono`}>{step.step_key}</td>
                          <td className={`${CELL} font-mono`}>{call.tool_key}</td>
                          <td className={CELL}>{call.status || "—"}</td>
                          <td className={CELL}>{call.attempt ?? "—"}</td>
                          <td className={`${CELL} font-mono`}>{call.model_name || "—"} / {call.prompt_version || "—"}</td>
                          <td className={CELL}>{jsonText(call.token_usage)}</td>
                          <td className={CELL}>{call.duration_ms ?? "—"} 毫秒</td>
                          <td className={CELL}>{[call.degraded_path, call.failure_reason].filter(Boolean).join(" / ") || "—"}</td>
                        </tr>
                      )) : (
                        <tr key={step.id}>
                          <td className={`${CELL} font-mono`}>{step.step_key}</td>
                          <td className={`${CELL} font-mono`}>{step.tool_key}</td>
                          <td className={CELL}>{step.status || "—"}</td>
                          <td className={CELL}>{step.attempt_count ?? "—"}</td>
                          <td className={CELL}>—</td>
                          <td className={CELL}>—</td>
                          <td className={CELL}>—</td>
                          <td className={CELL}>{[step.error_code, step.error_message].filter(Boolean).join(" / ") || "—"}</td>
                        </tr>
                      )
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}

"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { Activity, CheckCircle2, Cloud, Cpu, Inbox, Play, Power, PowerOff, Settings2, TriangleAlert } from "lucide-react";

import { useProjectWorkspace } from "@/components/ProjectContext";
import { WorkspaceHeader } from "@/components/WorkspaceHeader";
import { AsyncActionButton } from "@/components/feedback/AsyncActionButton";
import { ConfirmDialog } from "@/components/feedback/ConfirmDialog";
import { useAsyncAction } from "@/hooks/useAsyncAction";
import { apiGet, apiPatch, apiPost } from "@/lib/api";

type ProviderStatus = {
  provider: string;
  model?: string | null;
  base_url_host?: string | null;
  is_mock: boolean;
  is_local?: boolean;
  api_key_env_name?: string | null;
  api_key_present?: boolean;
  configuration_status: string;
  last_connection_test?: { status: string; tested_at: string; error?: string | null } | null;
};
type RuntimeStatus = {
  llm: ProviderStatus;
  embedding: ProviderStatus;
  vector_store: { provider: string; is_mock: boolean; configuration_status: string };
  issues: Array<{ component: string; message: string }>;
  observability: {
    last_success_at?: string | null;
    last_failure_at?: string | null;
    average_latency_ms: number;
    recent_token_usage: Record<string, unknown>;
  };
};
type Profile = {
  id: number;
  profile_name: string;
  provider_type: string;
  base_url?: string | null;
  base_url_host?: string | null;
  model_name?: string | null;
  api_key_env_name?: string | null;
  api_key_present: boolean;
  local_only: boolean;
  enabled: boolean;
  config_json: { last_connection_test?: { status: string; tested_at: string; error?: string | null } | null };
};
type ModelCall = {
  id: number;
  prompt_key: string;
  provider?: string | null;
  model_name?: string | null;
  status: string;
  latency_ms: number;
  token_usage: Record<string, unknown>;
  error_type?: string | null;
  created_at: string;
};

const providers = ["mock", "openai", "openai_compatible", "local_vllm", "local_ollama_compatible"];

export default function Page() {
  const { projectId } = useProjectWorkspace();
  const [runtime, setRuntime] = useState<RuntimeStatus | null>(null);
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [calls, setCalls] = useState<ModelCall[]>([]);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [editing, setEditing] = useState<Profile | null>(null);
  const [confirmation, setConfirmation] = useState<{ profile: Profile; kind: "activate" | "disable" } | null>(null);
  const profileAction = useAsyncAction<Record<string, unknown>>({ successMessage: "模型配置操作已完成" });

  const reload = useCallback(async () => {
    const [status, items] = await Promise.all([apiGet<RuntimeStatus>("/ai-runtime/status"), apiGet<Profile[]>("/model-profiles")]);
    setRuntime(status);
    setProfiles(items);
    if (projectId) {
      const logs = await apiGet<{ items: ModelCall[] }>(`/projects/${projectId}/model-calls?page_size=10`);
      setCalls(logs.items);
    } else setCalls([]);
  }, [projectId]);
  useEffect(() => {
    void reload().catch((error) => setMessage(readError(error)));
  }, [reload]);

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy("save");
    setMessage("");
    const form = new FormData(event.currentTarget);
    const provider = String(form.get("provider_type"));
    const modelName = String(form.get("model_name") || "") || null;
    if (looksLikeApiKey(modelName)) {
      setMessage("模型名称疑似填入了 API Key。请填写模型 ID，并把密钥放入 backend/.env。");
      setBusy(null);
      return;
    }
    const payload = {
      profile_name: String(form.get("profile_name")),
      provider_type: provider,
      base_url: String(form.get("base_url") || "") || null,
      model_name: modelName,
      api_key_env_name: String(form.get("api_key_env_name") || "") || null,
      local_only: provider.startsWith("local_"),
      config_json: { json_mode: true, max_output_tokens: 2048, temperature: .2, timeout_seconds: 60, retry_count: 2 },
    };
    try {
      if (editing) await apiPatch(`/model-profiles/${editing.id}`, payload);
      else await apiPost("/model-profiles", payload);
      setEditing(null);
      event.currentTarget.reset();
      setMessage(editing ? "Profile 已更新" : "Profile 已创建，连接测试不会自动激活");
      await reload();
    } catch (error) {
      setMessage(readError(error));
    } finally {
      setBusy(null);
    }
  }

  async function action(profile: Profile, kind: "test" | "activate" | "disable") {
    setMessage("");
    const result = await profileAction.run(() => apiPost<Record<string, unknown>>(`/model-profiles/${profile.id}/${kind}`, {}));
    if (result) {
      setMessage(kind === "test" ? `连接成功，耗时 ${result.latency_ms ?? "-"} ms` : `Profile 已${kind === "activate" ? "激活" : "停用"}`);
      setConfirmation(null);
      await reload();
    }
  }

  return (
    <main>
      <WorkspaceHeader title="AI 运行环境" meta="聊天模型、Embedding、连接测试与调用可观测性；密钥只从 backend/.env 读取" />
      <div className="mx-auto max-w-[1400px] space-y-5 p-4 lg:p-6">
        {message ? (
          <div className="rounded-lg border border-line bg-white px-3 py-2 text-sm text-slate-600">{message}</div>
        ) : null}

        {runtime ? (
          <section className="grid gap-4 md:grid-cols-3">
            <StatusCard title="聊天模型" status={runtime.llm} icon={<Cloud size={18} />} />
            <StatusCard title="Embedding" status={runtime.embedding} icon={<Cpu size={18} />} />
            <div className="panel p-4">
              <div className="flex items-center gap-2 font-semibold text-ink">
                <Activity size={18} />
                向量存储
              </div>
              <div className="mt-3 text-lg">{runtime.vector_store.provider}</div>
              <Badge mock={runtime.vector_store.is_mock} configured={runtime.vector_store.configuration_status === "configured"} />
              {runtime.vector_store.is_mock ? (
                <p className="mt-2 text-sm text-gold-700">当前向量语义能力为模拟模式，不代表生产向量检索。</p>
              ) : null}
            </div>
          </section>
        ) : null}

        {runtime ? (
          <section className="panel overflow-hidden">
            <div className="panel-header">
              <h2 className="text-[15px] font-semibold text-ink">调用状态</h2>
            </div>
            <div className="panel-body">
              <div className="grid gap-3 md:grid-cols-4">
                <Metric label="最近成功" value={formatTime(runtime.observability.last_success_at)} />
                <Metric label="最近失败" value={formatTime(runtime.observability.last_failure_at)} />
                <Metric label="平均延迟" value={`${runtime.observability.average_latency_ms} ms`} />
                <Metric label="最近 Token" value={tokenText(runtime.observability.recent_token_usage)} />
              </div>
              {runtime.issues.length ? (
                <div className="mt-4 rounded-lg border border-coral-200 bg-coral-50 px-3 py-2 text-sm text-coral-700">
                  <TriangleAlert className="mr-2 inline" size={16} />
                  {runtime.issues.map((item) => item.message).join("；")}
                </div>
              ) : null}
            </div>
          </section>
        ) : null}

        <section className="grid gap-5 lg:grid-cols-[360px_1fr]">
          <form className="panel h-fit" onSubmit={save}>
            <div className="panel-header">
              <h2 className="text-[15px] font-semibold text-ink">{editing ? "编辑 Profile" : "新建 Profile"}</h2>
            </div>
            <div className="panel-body space-y-3">
              <Field label="Profile 名称">
                <input className="control" name="profile_name" placeholder="例如：DeepSeek 正式模型" defaultValue={editing?.profile_name || ""} key={`name-${editing?.id || 0}`} required />
              </Field>
              <Field label="Provider 类型">
                <select className="control" name="provider_type" defaultValue={editing?.provider_type || "mock"} key={`provider-${editing?.id || 0}`}>
                  {providers.map((item) => (
                    <option key={item}>{item}</option>
                  ))}
                </select>
              </Field>
              <Field label="Base URL">
                <input className="control" name="base_url" placeholder="例如：https://api.deepseek.com" defaultValue={editing?.base_url || ""} key={`url-${editing?.id || 0}`} />
              </Field>
              <Field label="模型名称（模型 ID，不是密钥）">
                <input className="control" name="model_name" placeholder="例如：deepseek-chat" defaultValue={editing?.model_name || ""} key={`model-${editing?.id || 0}`} />
              </Field>
              <Field label="API Key 环境变量名（不是密钥）">
                <input
                  className="control"
                  name="api_key_env_name"
                  placeholder="例如：DEEPSEEK_API_KEY"
                  defaultValue={editing?.api_key_env_name || ""}
                  key={`env-${editing?.id || 0}`}
                  pattern="[A-Z_][A-Z0-9_]*"
                  title="只能使用大写英文字母、数字和下划线，且不能以数字开头"
                />
              </Field>
              <p className="text-xs text-slate-500">
                此处只填环境变量名，不能粘贴 API Key 本身。请在 <code>backend/.env</code> 中按“变量名=密钥”配置真实密钥。
              </p>
              <div className="flex gap-2">
                <button className="button-primary flex-1" disabled={busy === "save"}>
                  {busy === "save" ? "保存中…" : editing ? "保存修改" : "创建"}
                </button>
                {editing ? (
                  <button type="button" className="button-secondary" onClick={() => setEditing(null)}>
                    取消
                  </button>
                ) : null}
              </div>
            </div>
          </form>

          <div className="panel overflow-hidden">
            {profiles.length ? (
              profiles.map((profile) => (
                <div className="border-b border-line p-4 last:border-0" key={profile.id}>
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <div className="flex items-center gap-2 font-medium">
                        {profile.profile_name}
                        {profile.enabled ? <span className="badge-success">当前启用</span> : null}
                      </div>
                      <div className="mt-1 text-sm text-slate-600">
                        {profile.provider_type} · {profile.model_name || "未配置模型"} · {profile.base_url_host || "无外部地址"}
                      </div>
                      <div className="mt-1 text-xs text-slate-500">
                        Key 环境变量：{profile.api_key_env_name || "不需要"} · {profile.api_key_present ? "已配置" : "未配置"} · {profile.local_only ? "本地模型" : "外部模型"}
                      </div>
                      {profile.config_json.last_connection_test ? (
                        <div className="mt-1 text-xs text-slate-500">
                          最近测试：{profile.config_json.last_connection_test.status} / {formatTime(profile.config_json.last_connection_test.tested_at)}
                        </div>
                      ) : null}
                    </div>
                    <div className="flex flex-wrap gap-2">
                      <button className="button-secondary" onClick={() => setEditing(profile)}>
                        编辑
                      </button>
                      <AsyncActionButton actionStatus={profileAction.status} className="button-secondary" loadingText="测试中…" onClick={() => void action(profile, "test")}>
                        <Play size={15} />
                        测试连接
                      </AsyncActionButton>
                      {profile.enabled ? (
                        <AsyncActionButton actionStatus={profileAction.status} className="button-danger" onClick={() => setConfirmation({ profile, kind: "disable" })}>
                          <PowerOff size={15} />
                          停用
                        </AsyncActionButton>
                      ) : (
                        <AsyncActionButton actionStatus={profileAction.status} className="button-primary" onClick={() => setConfirmation({ profile, kind: "activate" })}>
                          <Power size={15} />
                          激活
                        </AsyncActionButton>
                      )}
                    </div>
                  </div>
                </div>
              ))
            ) : (
              <div className="empty-state m-4">
                <Settings2 className="text-slate-300" size={28} />
                <p>暂无数据库 Profile，系统使用 backend/.env 的运行配置。</p>
              </div>
            )}
          </div>
        </section>
        <ConfirmDialog
          busy={profileAction.isRunning}
          danger={confirmation?.kind === "disable"}
          description={confirmation?.kind === "disable"
            ? `停用“${confirmation?.profile.profile_name || ""}”后，系统将不再使用该 Profile。`
            : `激活“${confirmation?.profile.profile_name || ""}”会停用当前活动 Profile。`}
          onCancel={() => setConfirmation(null)}
          onConfirm={() => confirmation ? action(confirmation.profile, confirmation.kind) : undefined}
          open={Boolean(confirmation)}
          title={confirmation?.kind === "disable" ? "确认停用模型 Profile？" : "确认激活模型 Profile？"}
        />

        <section className="panel overflow-hidden">
          <div className="panel-header">
            <h2 className="text-[15px] font-semibold text-ink">当前项目最近模型调用</h2>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[800px] text-left text-sm">
              <thead className="border-b border-line bg-slate-50/80 text-xs font-semibold text-slate-500">
                <tr>
                  {["时间", "Prompt", "Provider / 模型", "状态", "延迟", "Token / 错误"].map((item) => (
                    <th className="px-4 py-2.5 font-semibold" key={item}>{item}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {calls.map((call) => (
                  <tr className="border-t border-line transition-colors hover:bg-mist/70" key={call.id}>
                    <td className="px-4 py-3">{formatTime(call.created_at)}</td>
                    <td className="px-4 py-3">{call.prompt_key}</td>
                    <td className="px-4 py-3">{call.provider || "-"} / {call.model_name || "-"}</td>
                    <td className="px-4 py-3">
                      <span className={statusBadgeClass(call.status)}>{call.status}</span>
                    </td>
                    <td className="px-4 py-3">{call.latency_ms} ms</td>
                    <td className="px-4 py-3">{call.error_type || tokenText(call.token_usage)}</td>
                  </tr>
                ))}
                {!calls.length ? (
                  <tr>
                    <td className="p-4" colSpan={6}>
                      <div className="empty-state">
                        <Inbox className="text-slate-300" size={28} />
                        <p>选择项目后显示调用摘要；页面不会展示完整输入或输出。</p>
                      </div>
                    </td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>
        </section>
      </div>
    </main>
  );
}

function StatusCard({ title, status, icon }: { title: string; status: ProviderStatus; icon: React.ReactNode }) {
  return (
    <div className="panel p-4">
      <div className="flex items-center gap-2 font-semibold text-ink">
        {icon}
        {title}
      </div>
      <div className="mt-3 text-lg">{status.model || "未配置"}</div>
      <div className="text-sm text-slate-500">{status.provider} · {status.base_url_host || "无外部地址"}</div>
      <div className="mt-2">
        <Badge mock={status.is_mock} configured={status.configuration_status === "configured"} />
      </div>
      <div className="mt-2 text-xs text-slate-500">
        {status.is_local ? "本地模型" : "外部模型"} · Key {status.api_key_present ? "已配置" : "未配置或不需要"}
      </div>
      {status.is_mock && title === "Embedding" ? (
        <p className="mt-2 text-sm text-gold-700">Embedding 仍为 Mock，可与真实聊天模型独立组合。</p>
      ) : null}
    </div>
  );
}

function Badge({ mock, configured }: { mock: boolean; configured: boolean }) {
  if (mock) return <span className="badge-warning">Mock 模式</span>;
  return configured ? (
    <span className="badge-success">
      <CheckCircle2 size={13} />
      真实模型已配置
    </span>
  ) : (
    <span className="badge-danger">配置不完整</span>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="stat-card">
      <div className="stat-label">{label}</div>
      <div className="stat-value text-lg">{value}</div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block space-y-1">
      <span className="text-xs font-medium text-slate-600">{label}</span>
      {children}
    </label>
  );
}

function looksLikeApiKey(value?: string | null) {
  return Boolean(value && /^(?:sk-[A-Za-z0-9_-]{16,}|AIza[A-Za-z0-9_-]{20,}|(?:ghp|github_pat|xox[baprs])[_-][A-Za-z0-9_-]{16,})$/.test(value.trim()));
}

function statusBadgeClass(status: string) {
  const value = status.toLowerCase();
  if (["success", "succeeded", "completed", "approved", "enabled"].includes(value)) return "badge-success";
  if (["failed", "rejected", "error"].includes(value)) return "badge-danger";
  if (["pending", "running", "processing"].includes(value)) return "badge-warning";
  return "badge-neutral";
}

function formatTime(value?: string | null) {
  return value ? new Date(value).toLocaleString() : "暂无";
}

function tokenText(usage: Record<string, unknown>) {
  return usage.usage_available === false ? "usage unavailable" : String(usage.total_tokens ?? "usage unavailable");
}

function readError(error: unknown) {
  if (!(error instanceof Error)) return "操作失败";
  return error.message;
}

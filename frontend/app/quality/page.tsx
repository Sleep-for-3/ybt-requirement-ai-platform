"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Plus, ShieldCheck } from "lucide-react";
import { FormEvent, useState } from "react";

import { useProjectWorkspace } from "@/components/ProjectContext";
import { WorkspaceHeader } from "@/components/WorkspaceHeader";
import { ModalDialog } from "@/components/feedback/ModalDialog";
import { apiGet, apiPost } from "@/lib/api";

type Binding = {
  id: number;
  scope_type: string;
  entity_type: string;
  entity_id: number | null;
  entity_key: string | null;
};
type Expectation = {
  id: number;
  rule_code: string;
  rule_name: string;
  description: string | null;
  rule_type: string;
  severity: "info" | "warning" | "error";
  status: string;
  source_type: string;
  confirmed_by: string | null;
  bindings: Binding[];
};

const RULE_LABELS: Record<string, string> = {
  not_null: "非空",
  unique: "唯一",
  range: "范围",
  enum: "枚举",
  referential: "参照完整性",
  consistency: "一致性",
  custom_expression: "自定义表达式",
};
const SCOPE_LABELS: Record<string, string> = {
  requirement: "需求口径",
  mapping: "映射",
  uat: "UAT",
  monitoring: "生产监控",
};

export default function QualityExpectationsPage() {
  const { projectId } = useProjectWorkspace();
  const queryClient = useQueryClient();
  const [createOpen, setCreateOpen] = useState(false);
  const [formError, setFormError] = useState("");
  const [confirmError, setConfirmError] = useState("");
  const queryKey = ["quality-expectations", projectId];
  const expectations = useQuery({
    queryKey,
    enabled: Boolean(projectId),
    queryFn: () =>
      apiGet<Expectation[]>(`/projects/${projectId}/quality-expectations`),
    staleTime: 15_000,
  });
  const confirm = useMutation({
    mutationFn: (id: number) =>
      apiPost(`/quality-expectations/${id}/status`, {
        status: "confirmed",
        comment: "已在质量期望中心确认",
      }),
    onMutate: () => setConfirmError(""),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey }),
    onError: (error) =>
      setConfirmError(
        error instanceof Error ? error.message : "无法确认质量期望",
      ),
  });

  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!projectId) return;
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    const ruleType = String(form.get("rule_type"));
    const scopeType = String(form.get("scope_type"));
    const entityType = String(form.get("entity_type")).trim();
    const entityId = Number(form.get("entity_id")) || null;
    const entityKey = String(form.get("entity_key") || "").trim() || null;
    const bindings = entityType
      ? [
          {
            scope_type: scopeType,
            entity_type: entityType,
            entity_id: entityId,
            entity_key: entityKey,
          },
        ]
      : [];
    setFormError("");
    try {
      const parameters = parseParameters(String(form.get("parameters") || ""));
      await apiPost(`/projects/${projectId}/quality-expectations`, {
        rule_code: form.get("rule_code"),
        rule_name: form.get("rule_name"),
        description: form.get("description"),
        rule_type: ruleType,
        severity: form.get("severity"),
        status: form.get("status"),
        source_type: form.get("source_type"),
        confidence_level: form.get("confidence_level"),
        expression: form.get("expression") || null,
        parameters_json: parameters,
        bindings,
      });
      formElement.reset();
      setCreateOpen(false);
      await queryClient.invalidateQueries({ queryKey });
    } catch (error) {
      setFormError(error instanceof Error ? error.message : "无法创建质量期望");
    }
  }

  const actions = (
    <button
      className="button-primary"
      disabled={!projectId}
      onClick={() => {
        setFormError("");
        setCreateOpen(true);
      }}
      type="button"
    >
      <Plus size={16} />
      新建质量期望
    </button>
  );
  return (
    <main>
      <WorkspaceHeader
        title="质量期望"
        meta="可复用到需求、映射、UAT 与生产监控；AI 建议必须经人工确认"
        actions={actions}
      />
      <div className="mx-auto max-w-[1400px] space-y-4 p-4 lg:p-6">
        {confirmError ? (
          <section
            className="rounded-lg border border-coral-200 bg-coral-50 p-4 text-sm text-coral-800"
            role="alert"
          >
            {confirmError}
          </section>
        ) : null}
        {!projectId ? (
          <section className="empty-state">
            <ShieldCheck className="text-slate-300" size={30} />
            <p>请先选择项目</p>
          </section>
        ) : null}
        {expectations.isLoading ? (
          <section aria-busy="true" className="space-y-3">
            {[0, 1, 2].map((item) => (
              <div
                className="h-24 animate-pulse rounded-lg border border-line bg-white"
                key={item}
              />
            ))}
          </section>
        ) : null}
        {expectations.isError ? (
          <section
            className="rounded-lg border border-coral-200 bg-coral-50 p-4 text-sm text-coral-800"
            role="alert"
          >
            质量期望加载失败。请检查权限或稍后重试。
          </section>
        ) : null}
        {projectId &&
        !expectations.isLoading &&
        !expectations.isError &&
        !expectations.data?.length ? (
          <section className="empty-state">
            <ShieldCheck className="text-slate-300" size={30} />
            <h2 className="text-base font-semibold text-ink">
              当前项目还没有质量期望
            </h2>
            <p>从可确认的规则开始，逐步复用到需求、映射、UAT 和生产监控。</p>
          </section>
        ) : null}
        {expectations.data?.map((item) => (
          <article className="panel p-5" key={item.id}>
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <div className="flex flex-wrap gap-2">
                  <span className="badge-neutral">
                    {RULE_LABELS[item.rule_type] || item.rule_type}
                  </span>
                  <StatusBadge status={item.status} />
                  <span
                    className={
                      item.severity === "error"
                        ? "badge-danger"
                        : item.severity === "warning"
                          ? "badge-warning"
                          : "badge-neutral"
                    }
                  >
                    {item.severity}
                  </span>
                </div>
                <h2 className="mt-3 text-base font-semibold text-ink">
                  {item.rule_name}
                </h2>
                <p className="mt-1 font-mono text-xs text-slate-500">
                  {item.rule_code}
                </p>
              </div>
              {["draft", "ai_suggested"].includes(item.status) ? (
                <button
                  className="button-secondary"
                  disabled={confirm.isPending}
                  onClick={() => confirm.mutate(item.id)}
                  type="button"
                >
                  <CheckCircle2 size={15} />
                  确认规则
                </button>
              ) : null}
            </div>
            <p className="mt-3 text-sm text-slate-600">
              {item.description || "暂无规则说明"}
            </p>
            <div className="mt-4 flex flex-wrap gap-2 border-t border-line pt-3 text-xs text-slate-600">
              {item.bindings.length ? (
                item.bindings.map((binding) => (
                  <span
                    className="rounded-full bg-mist px-2.5 py-1"
                    key={binding.id}
                  >
                    {SCOPE_LABELS[binding.scope_type] || binding.scope_type} ·{" "}
                    {binding.entity_key ||
                      `${binding.entity_type} #${binding.entity_id}`}
                  </span>
                ))
              ) : (
                <span>尚未绑定使用范围</span>
              )}
            </div>
          </article>
        ))}
      </div>
      <ModalDialog
        description="规则仅被治理和复用；自定义表达式不会在此页面执行。AI 建议需要人工确认后才会成为已确认规则。"
        onClose={() => setCreateOpen(false)}
        open={createOpen}
        title="新建质量期望"
      >
        <form className="space-y-4" onSubmit={create}>
          {formError ? (
            <p
              className="rounded-lg border border-coral-200 bg-coral-50 p-3 text-sm text-coral-800"
              role="alert"
            >
              {formError}
            </p>
          ) : null}
          <div className="grid gap-3 sm:grid-cols-2">
            <input
              className="control"
              name="rule_code"
              placeholder="规则代码，例如 CUSTOMER_NO_NOT_NULL"
              required
            />
            <input
              className="control"
              name="rule_name"
              placeholder="规则名称"
              required
            />
          </div>
          <textarea
            className="control min-h-20"
            name="description"
            placeholder="业务与监管说明"
          />
          <div className="grid gap-3 sm:grid-cols-3">
            <select
              className="control"
              defaultValue="not_null"
              name="rule_type"
            >
              {Object.entries(RULE_LABELS).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
            <select className="control" defaultValue="warning" name="severity">
              <option value="info">提示</option>
              <option value="warning">警告</option>
              <option value="error">错误</option>
            </select>
            <select className="control" defaultValue="draft" name="status">
              <option value="draft">人工草稿</option>
              <option value="ai_suggested">AI 建议</option>
            </select>
          </div>
          <textarea
            className="control min-h-16"
            name="expression"
            placeholder="一致性/自定义表达式需要填写；此处不会执行"
          />
          <input
            className="control"
            name="parameters"
            placeholder={'参数 JSON，例如 {"min": 0, "max": 100}'}
          />
          <div className="grid gap-3 sm:grid-cols-2">
            <input
              className="control"
              defaultValue="manual"
              name="source_type"
              placeholder="来源类型"
            />
            <select
              className="control"
              defaultValue="medium"
              name="confidence_level"
            >
              <option value="low">低置信度</option>
              <option value="medium">中置信度</option>
              <option value="high">高置信度</option>
            </select>
          </div>
          <fieldset className="rounded-lg border border-line p-3">
            <legend className="px-1 text-sm font-medium text-ink">
              可选：首次绑定使用范围
            </legend>
            <div className="mt-2 grid gap-3 sm:grid-cols-2">
              <select
                className="control"
                defaultValue="requirement"
                name="scope_type"
              >
                <option value="requirement">需求口径</option>
                <option value="mapping">映射</option>
                <option value="uat">UAT</option>
                <option value="monitoring">生产监控</option>
              </select>
              <input
                className="control"
                name="entity_type"
                placeholder="实体类型，例如 target_field"
              />
            </div>
            <div className="mt-3 grid gap-3 sm:grid-cols-2">
              <input
                className="control"
                min="1"
                name="entity_id"
                placeholder="实体 ID（监控范围留空）"
                type="number"
              />
              <input
                className="control"
                name="entity_key"
                placeholder="监控范围标识（仅监控范围）"
              />
            </div>
          </fieldset>
          <div className="flex justify-end gap-2">
            <button
              className="button-secondary"
              onClick={() => setCreateOpen(false)}
              type="button"
            >
              取消
            </button>
            <button className="button-primary" type="submit">
              <Plus size={16} />
              创建规则
            </button>
          </div>
        </form>
      </ModalDialog>
    </main>
  );
}

function StatusBadge({ status }: { status: string }) {
  const className =
    status === "confirmed"
      ? "badge-success"
      : status === "ai_suggested"
        ? "badge-warning"
        : status === "rejected"
          ? "badge-danger"
          : "badge-neutral";
  const label =
    (
      {
        draft: "草稿",
        ai_suggested: "AI 建议",
        confirmed: "已确认",
        rejected: "已拒绝",
        retired: "已退役",
      } as Record<string, string>
    )[status] || status;
  return <span className={className}>{label}</span>;
}
function parseParameters(value: string) {
  if (!value.trim()) return {};
  try {
    const parsed = JSON.parse(value);
    if (!parsed || Array.isArray(parsed) || typeof parsed !== "object")
      throw new Error();
    return parsed;
  } catch {
    throw new Error("参数必须是 JSON 对象");
  }
}

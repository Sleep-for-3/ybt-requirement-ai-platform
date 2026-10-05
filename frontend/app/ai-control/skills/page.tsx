"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useProjectWorkspace } from "@/components/ProjectContext";
import { WorkspaceHeader } from "@/components/WorkspaceHeader";
import { apiGet, apiPatch, apiPost } from "@/lib/api";
import { SkillValidationDetail } from "@/components/SkillValidationDetail";
import { useUnsavedChanges } from "@/hooks/useUnsavedChanges";
import { clearDraft, readDraft, saveDraft } from "@/lib/unsaved-changes.mjs";

type Scope = { scope_type: "platform" | "institution" | "project" | "task"; institution_id?: number; project_id?: number; invocation_key?: string };
const SCOPE_LABELS = { platform: "平台", institution: "机构", project: "项目", task: "任务" };
const TASK_LABELS: Record<string, string> = { requirement_document_assistance: "固定版本文档辅助", lineage_edge_explanation: "血缘关系解释", policy_comparison: "制度比较", requirement_candidate_generation: "需求候选", scenario_business_mapping: "场景业务映射", scenario_technical_lineage: "场景技术溯源", source_to_mart_mapping: "源到集市映射", mart_to_ybt_mapping: "集市到一表通映射", regulatory_qa: "监管问答", data_field_explanation: "字段解释", field_semantic_matching: "字段语义匹配", change_impact_explanation: "变更影响解释", quality_rule_suggestion: "质量规则建议", uat_suggestion: "UAT 建议", project_assistant: "项目助手" };
type Definition = { skill_key: string; task_key: string; display_name: string };
type Model = { id: number; name: string; provider_type: string; model_name: string };
type Content = { system_prompt: string; user_prompt_template: string; model_profile_id: number; [key: string]: unknown };
type ContextPolicy = { providers: string[]; max_input_bytes: number; max_depth: number; max_paths: number; max_policy_clauses: number; overflow_policy: string };
const DEFAULT_POLICY: ContextPolicy = { providers: ["lineage_edge_facts", "script_evidence", "asset_identity", "regulatory_clauses", "bounded_lineage_paths"], max_input_bytes: 64000, max_depth: 4, max_paths: 20, max_policy_clauses: 12, overflow_policy: "fail_with_breakdown" };
const OPTIONAL_PROVIDERS = { bounded_lineage_paths: "有界上下游路径", field_constraints: "历史字段约束", quality_profile: "已有质量画像", prior_human_decisions: "历史人工决策", script_diff: "固定版本差异" };
type Version = { id: number; version_no: number; status: string; lock_version: number; content: Content; content_hash: string; created_by: number; edited_by: number | null };
type Capabilities = { actor_id: number; can_register: boolean; can_edit: boolean; can_publish: boolean };
type BindingOption = { id: number; version_no: number; scope_type: string; content_hash: string; available: boolean };
type Run = { id: number; version_id: number; created_by: number; mode: string; status: string; metrics: { total: number; passed: number; real_model_successes: number; review_comment?: string } };
const STATUS: Record<string, string> = { draft: "草稿", testing: "测试中", pending_approval: "待独立审批", published: "已发布", deprecated: "已停用", archived: "已归档" };
const MODES: Record<string, string> = { deterministic: "确定性验证", mock_model: "Mock 测试", real_model: "真实模型测试", replay: "回放", human_review: "人工评审" };
const inputClass = "mt-1 w-full rounded border border-slate-300 bg-white p-2 text-sm";
const buttonClass = "rounded border border-slate-300 bg-white px-3 py-2 text-sm disabled:cursor-not-allowed disabled:opacity-40";
function errorMessage(error: unknown) { return error instanceof Error ? error.message : "操作失败，请刷新后重试。"; }
function query(scope: Scope) { return new URLSearchParams(Object.entries(scope).map(([key, value]) => [key, String(value)])).toString(); }
const MAPPING_TASKS = ["source_to_mart_mapping", "mart_to_ybt_mapping", "scenario_business_mapping", "scenario_technical_lineage"];
function initialContent(model = 0, task = "lineage_edge_explanation"): Content {
  const requirement = task === "requirement_candidate_generation";
  const mapping = MAPPING_TASKS.includes(task);
  return { system_prompt: requirement ? "依据固定需求输入生成候选。物理字段、证据与脚本规则必须在输入白名单内；报告缺口，不改变人工正文或确认结果。" : mapping ? "依据已授权的固定上下文生成映射草稿。引用必须属于输入；不得编造物理来源或覆盖人工确认，证据不足明确列为问题。" : task === "lineage_edge_explanation" ? "依据提供的固定版本事实和有效制度条款解释血缘。所有声明必须有引用；明确报告缺口，制度结论待人工确认。" : `依据已授权的固定事实和有效制度条款完成${TASK_LABELS[task] || "当前任务"}。所有声明必须引用输入中的依据；证据不足明确报告缺口，结果等待人工确认。`,
    user_prompt_template: "{subject}\n{facts}\n{policy_evidence}\n{gaps}", model_profile_id: model,
    output_schema_key: task === "requirement_document_assistance" ? "document_assistance_v1" : requirement ? "requirement_candidate_v1" : mapping ? "mapping_candidate_v1" : "grounded_claims_v1" };
}

export default function Page() {
  const { selectedProject } = useProjectWorkspace();
  return <main><WorkspaceHeader title="AI Skill 配置中心" meta="范围配置 · 测试门禁 · 独立审批"/>
    <div className="mx-auto max-w-6xl space-y-4 p-4 lg:p-6">
      <p className="text-sm text-slate-600">先保存草稿与测试用例，再运行确定性及对应模型测试，通过后提交独立审批。发布后固定版本绑定到所选配置范围。<Link className="ml-2 underline" href="/prompt-versions">查看兼容 Prompt 记录</Link></p>
      {selectedProject?.institution_id ? <ScopeWorkspace key={`${selectedProject.institution_id}:${selectedProject.id}`} institutionId={selectedProject.institution_id} projectId={selectedProject.id}/> : <p className="panel p-4">请先选择已归属机构的项目。</p>}
    </div></main>;
}

function ScopeWorkspace({ institutionId, projectId }: { institutionId: number; projectId: number }) {
  const [kind, setKind] = useState<Scope["scope_type"]>("project");
  const [invocation, setInvocation] = useState("lineage_graph");
  const [locked, setLocked] = useState(false);
  const scope = useMemo<Scope>(() => kind === "platform" ? { scope_type: kind } : kind === "institution" ? { scope_type: kind, institution_id: institutionId } : {
    scope_type: kind, institution_id: institutionId, project_id: projectId, ...(kind === "task" ? { invocation_key: invocation } : {}),
  }, [kind, institutionId, projectId, invocation]);
  return <>
    <section className="panel space-y-2 p-3" aria-label="配置范围">
      <label className="block text-sm">配置范围<select aria-label="配置范围" className={inputClass} value={kind} disabled={locked} onChange={event => setKind(event.target.value as Scope["scope_type"])}>{Object.entries(SCOPE_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
      {kind === "task" && <label className="block text-sm">任务调用标识<input aria-label="任务调用标识" className={inputClass} value={invocation} disabled={locked} maxLength={100} pattern="[a-z][a-z0-9_]*" onChange={event => setInvocation(event.target.value)}/></label>}
      <p className="text-xs text-slate-600">当前编辑{SCOPE_LABELS[kind]}配置，测试使用所选项目 #{projectId} 的固定用例。发布绑定到当前配置范围；项目采用上级版本需明确选择。</p>
      {kind === "task" && <p className="text-xs text-slate-600">调用标识需与业务入口一致，例如血缘 lineage_graph、需求 requirement_fields。固定用例也必须具有相同任务范围。</p>}
    </section>
    {kind !== "task" || /^[a-z][a-z0-9_]{0,99}$/.test(invocation) ? <ProjectSkills key={query(scope)} scope={scope} testProjectId={projectId} onLockedChange={setLocked}/> : <p role="alert">任务标识须以小写字母开头，仅含小写字母、数字和下划线。</p>}
  </>;
}

function ProjectSkills({ scope, testProjectId, onLockedChange }: { scope: Scope; testProjectId: number; onLockedChange: (locked: boolean) => void }) {
  const [skills, setSkills] = useState<Definition[]>([]);
  const [models, setModels] = useState<Model[]>([]);
  const [selected, setSelected] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [capabilities, setCapabilities] = useState<Capabilities | null>(null);
  const [editorLocked, setEditorLocked] = useState(false);
  const [registerTask, setRegisterTask] = useState("requirement_candidate_generation");
  useEffect(() => { onLockedChange(loading || editorLocked); }, [loading, editorLocked, onLockedChange]);
  useEffect(() => {
    let alive = true;
    Promise.all([apiGet<Definition[]>(`/ai-skills?${query(scope)}`), apiGet<Model[]>(`/ai-skills/model-options?${query(scope)}`), apiGet<Capabilities>(`/ai-skills/capabilities?${query(scope)}`)])
      .then(([definitions, options, permissions]) => { if (alive) { setSkills(definitions); setModels(options); setCapabilities(permissions); setSelected(definitions[0]?.skill_key || ""); } })
      .catch(error => { if (alive) setError(errorMessage(error)); }).finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [scope]);
  async function registerSkill() {
    setLoading(true); setError("");
    try {
      const item = await apiPost<Definition>("/ai-skills", { skill_key: registerTask, task_key: registerTask, display_name: TASK_LABELS[registerTask] });
      setSkills(previous => [...previous, item]); setSelected(item.skill_key);
    } catch (error) { setError(errorMessage(error)); } finally { setLoading(false); }
  }
  return <>
    {error && <p role="alert" className="rounded bg-red-50 p-3 text-sm text-red-800">{error}</p>}
    {loading ? <p role="status">正在读取配置…</p> : !skills.length && !error ? <p className="panel p-4">尚未注册 Skill。请由平台管理员注册能力。</p> : null}
    {capabilities?.can_register && <details className="panel p-3"><summary className="cursor-pointer text-sm">注册能力（平台管理员）</summary><label className="block text-sm">能力类型<select aria-label="注册能力类型" className={inputClass} disabled={loading || editorLocked} value={registerTask} onChange={event => setRegisterTask(event.target.value)}>{Object.entries(TASK_LABELS).map(([value, label]) => <option key={value} value={value} disabled={skills.some(skill => skill.skill_key === value)}>{label}{skills.some(skill => skill.skill_key === value) ? " · 已注册" : ""}</option>)}</select></label><button className={buttonClass} disabled={loading || editorLocked || skills.some(skill => skill.skill_key === registerTask)} onClick={registerSkill}>注册所选能力</button></details>}
    {skills.length > 0 && <label className="block text-sm">选择能力<select className={inputClass} value={selected} disabled={editorLocked} onChange={event => setSelected(event.target.value)}>{skills.map(skill => <option key={skill.skill_key} value={skill.skill_key}>{skill.display_name}</option>)}</select></label>}
    {capabilities && skills.find(skill => skill.skill_key === selected) && <SkillEditor key={selected} scope={scope} testProjectId={testProjectId} skill={skills.find(skill => skill.skill_key === selected)!} models={models} capabilities={capabilities} onLockedChange={setEditorLocked}/>}
  </>;
}

function SkillEditor({ scope, testProjectId, skill, models, capabilities, onLockedChange }: { scope: Scope; testProjectId: number; skill: Definition; models: Model[]; capabilities: Capabilities; onLockedChange: (locked: boolean) => void }) {
  const root = `/ai-skills/${encodeURIComponent(skill.skill_key)}`;
  const [versions, setVersions] = useState<Version[]>([]);
  const [active, setActive] = useState<Version | null>(null);
  const [content, setContent] = useState<Content>(initialContent(models[0]?.id, skill.task_key));
  const [binding, setBinding] = useState<{ version_id: number; lock_version: number } | null>(null);
  const [bindingOptions, setBindingOptions] = useState<BindingOption[]>([]);
  const [adoptVersion, setAdoptVersion] = useState("");
  const [runs, setRuns] = useState<Run[]>([]);
  const [cases, setCases] = useState<{ id: number; name: string }[]>([]);
  const [caseText, setCaseText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [detail, setDetail] = useState<unknown>(null);
  const [mode, setMode] = useState("deterministic");
  const [compareVersion, setCompareVersion] = useState("");
  const [reviewComment, setReviewComment] = useState("");
  const selectedRun = runs.find(run => run.id === (detail as Run | null)?.id);
  useEffect(() => { setReviewComment(""); }, [selectedRun?.id]);
  const templateRef = useRef<HTMLTextAreaElement>(null);
  const readOnly = !capabilities.can_edit || (!!active && active.status !== "draft");
  const policy = (content.context_policy || DEFAULT_POLICY) as ContextPolicy;
  const dirty = JSON.stringify(content) !== JSON.stringify(active?.content || initialContent(models[0]?.id, skill.task_key));
  const canApprove = capabilities.can_publish && active?.created_by !== capabilities.actor_id && active?.edited_by !== capabilities.actor_id;
  // F02: one stable draft key per editor instance (scope + skill), shared by the registry below and
  // the local draft persistence.
  // C02: 草稿按**可信登录用户**隔离。actor 来自服务端 /ai-skills/permissions 返回的 actor_id；
  // 未取得身份时（actor 为 null）不拼 key、不读写草稿，避免把上一个账号的内容归属给下一位登录者。
  const actorId = capabilities.actor_id ?? null;
  const skillDraftKey = actorId === null ? null
    : `skill-draft:actor:${actorId}:${scope.scope_type}:${scope.project_id ?? "none"}:${scope.institution_id ?? "none"}:${skill.skill_key}`;
  useEffect(() => { onLockedChange(busy || dirty); }, [busy, dirty, onLockedChange]);
  // F02: register the Skill draft with the shared unsaved-changes registry. Previously this page only
  // installed its own `beforeunload` listener, so the global project switch / in-app link guard could
  // not see the edit and leaving silently dropped it.
  useUnsavedChanges(`skill-editor:${scope.project_id ?? "none"}:${scope.institution_id ?? "none"}:${skill.skill_key}`, dirty);
  useEffect(() => {
    if (!dirty) return;
    const warn = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ""; };
    window.addEventListener("beforeunload", warn);
    // F02: persist a local draft so an accidental discard is recoverable. The draft records the
    // server version it was based on, so a stale draft is flagged rather than silently overwriting
    // newer content.
    if (!skillDraftKey) return () => window.removeEventListener("beforeunload", warn);
    saveDraft(window.localStorage, skillDraftKey, { content, basedOnVersionId: active?.id ?? null }, actorId);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty, content, active?.id, skillDraftKey, actorId]);
  const refresh = useCallback(async (selectedId?: number) => {
    const [items, currentBinding, history, samples, options] = await Promise.all([
      apiGet<Version[]>(`${root}/versions?${query(scope)}`), apiGet<typeof binding>(`${root}/bindings?${query(scope)}`),
      apiGet<Run[]>(`${root}/test-runs?project_id=${testProjectId}`), apiGet<typeof cases>(`${root}/test-cases?project_id=${testProjectId}`),
      apiGet<BindingOption[]>(`${root}/binding-options?${query(scope)}`)]);
    setBindingOptions(options); setAdoptVersion("");
    setVersions(items); setBinding(currentBinding); setRuns(history); setCases(samples);
    const next = items.find(item => item.id === selectedId) || items[0] || null;
    setActive(next); setContent(next?.content || initialContent(models[0]?.id, skill.task_key));
  }, [root, scope, testProjectId, models, skill.task_key]);
  // F02: surface a locally saved draft so an accidental discard is recoverable. The draft carries the
  // version it was based on, so a draft older than the server content is flagged instead of silently
  // overwriting newer content.
  const [pendingDraft, setPendingDraft] = useState<{ content: Content; basedOnVersionId: number | null; savedAt: string } | null>(null);
  useEffect(() => {
    // C02: 未取得身份时不读取草稿（否则可能读到上一位登录者的内容）。
    if (!skillDraftKey) { setPendingDraft(null); return; }
    const saved = readDraft(window.localStorage, skillDraftKey, actorId) as { savedAt?: string; owner?: string; payload?: { content?: Content; basedOnVersionId?: number | null } } | null;
    const payload = saved?.payload;
    if (!payload?.content || dirty) { setPendingDraft(null); return; }
    setPendingDraft({ content: payload.content, basedOnVersionId: payload.basedOnVersionId ?? null, savedAt: saved?.savedAt || "" });
  }, [skillDraftKey, dirty, active?.id, actorId]);
  useEffect(() => {
    setBusy(true);
    void refresh().catch(error => setError(errorMessage(error))).finally(() => setBusy(false));
  }, [refresh]);
  async function action(work: () => Promise<void>) {
    setBusy(true); setError(""); setNotice("");
    try { await work(); } catch (error) { setError(errorMessage(error)); } finally { setBusy(false); }
  }
  async function save() {
    const item = active ? await apiPatch<Version>(`${root}/versions/${active.version_no}`, { expected_lock_version: active.lock_version, content })
      : await apiPost<Version>(`${root}/versions`, { scope, content });
    // F02: a saved draft is no longer a recovery candidate.
    if (skillDraftKey) clearDraft(window.localStorage, skillDraftKey, actorId);
    await refresh(item.id); setNotice("草稿已保存。修改后需要重新测试。");
  }
  async function transition(kind: string) {
    if (!active) return;
    const item = await apiPost<Version>(`${root}/versions/${active.version_no}/${kind}`, { expected_lock_version: active.lock_version,
      ...(kind === "submit" || kind === "publish" ? { test_project_id: testProjectId, expected_binding_lock: binding?.lock_version ?? null } : {}) });
    await refresh(item.id); setNotice(`当前状态：${STATUS[item.status] || item.status}`);
  }
  function insertVariable(variable: string) {
    const textarea = templateRef.current;
    const start = textarea?.selectionStart ?? content.user_prompt_template.length;
    const end = textarea?.selectionEnd ?? start;
    const token = `{${variable}}`;
    setContent({ ...content, user_prompt_template: content.user_prompt_template.slice(0, start) + token + content.user_prompt_template.slice(end) });
    requestAnimationFrame(() => { textarea?.focus(); textarea?.setSelectionRange(start + token.length, start + token.length); });
  }
  return <div className="grid gap-4 lg:grid-cols-[240px_1fr]">
    <aside className="panel space-y-2 p-3"><h2 className="font-semibold">{SCOPE_LABELS[scope.scope_type]}版本</h2><button disabled={busy || dirty || !capabilities.can_edit} className={buttonClass} onClick={() => { setActive(null); setContent(initialContent(models[0]?.id, skill.task_key)); setDetail(null); }}>新建草稿</button>
      {versions.map(item => <button key={item.id} disabled={busy || dirty} className={`block w-full rounded border p-3 text-left text-sm ${active?.id === item.id ? "border-emerald-700 bg-emerald-50" : "border-slate-200"}`} onClick={() => { setActive(item); setContent(item.content); setDetail(null); }}>v{item.version_no} · {STATUS[item.status] || item.status}{binding?.version_id === item.id && <span className="mt-1 block text-xs text-emerald-800">当前{SCOPE_LABELS[scope.scope_type]}固定绑定</span>}</button>)}
      {!versions.length && <p className="text-sm text-slate-500">当前范围暂无版本。</p>}
      <section aria-label="项目版本绑定" className="space-y-2 border-t pt-3 text-xs">
        <h3 className="font-semibold">固定采用已发布版本</h3>
        <p>{binding ? `当前绑定版本记录 #${binding.version_id}` : "当前范围未固定绑定。"}</p>
        <p>可采用当前范围及可兼容上级范围的已发布版本。上级更新不会自动改变当前绑定。</p>
        <label className="block">采用版本<select aria-label="采用版本" className={inputClass} value={adoptVersion} disabled={busy || dirty || !capabilities.can_publish} onChange={event => setAdoptVersion(event.target.value)}>
          <option value="">请选择已发布版本</option>{bindingOptions.map(item => <option key={item.id} value={item.version_no} disabled={!item.available || item.id === binding?.version_id}>v{item.version_no} · {({ platform: "平台", institution: "机构", project: "项目", task: "任务" } as Record<string, string>)[item.scope_type]}{!item.available ? " · 依赖已变化" : item.id === binding?.version_id ? " · 已绑定" : ""}</option>)}
        </select></label>
        {adoptVersion && <p className="break-all">配置哈希：{bindingOptions.find(item => String(item.version_no) === adoptVersion)?.content_hash}</p>}
        <button className={buttonClass} disabled={busy || dirty || !capabilities.can_publish || !adoptVersion} onClick={() => void action(async () => {
          await apiPost(`${root}/bindings`, { version: Number(adoptVersion), scope, expected_binding_lock: binding?.lock_version ?? null });
          await refresh(active?.id); setNotice("已固定采用所选发布版本，后续更新需再次明确采用。");
        })}>确认固定采用</button>
        {!capabilities.can_publish && <p>更改绑定需要机构审批权限。</p>}
      </section>
    </aside>
    <section className="panel space-y-4 p-4">
      <h2 className="font-semibold">{active ? `v${active.version_no} · ${STATUS[active.status] || active.status}` : "新草稿"}</h2>
      {error && <p role="alert" className="rounded bg-red-50 p-3 text-sm text-red-800">{error}<button className="ml-2 underline" disabled={busy} onClick={() => void action(() => refresh(active?.id))}>重新读取服务端版本</button></p>}
      {notice && <p role="status" className="text-sm text-emerald-800">{notice}</p>}
      {busy && <p role="status" className="text-sm">操作处理中，请等待结果…</p>}
      {dirty && <div className="text-sm text-amber-800"><p>有未保存的修改，请先保存或放弃修改，再切换能力、版本或运行测试。</p><button className="mt-1 underline" disabled={busy} onClick={() => setContent(active?.content || initialContent(models[0]?.id, skill.task_key))}>放弃未保存修改</button></div>}
      {pendingDraft && <div className="text-sm text-sky-800" role="status"><p>发现本地保存的草稿（{pendingDraft.savedAt || "时间未知"}，基于版本 #{pendingDraft.basedOnVersionId ?? "新草稿"}）。{active && pendingDraft.basedOnVersionId !== active.id ? "该草稿基于其他版本，恢复前请核对基线。" : ""}</p><div className="mt-1 flex gap-3"><button className="underline" disabled={busy || readOnly} onClick={() => { setContent(pendingDraft.content); setPendingDraft(null); }}>恢复草稿</button><button className="underline" disabled={busy} onClick={() => { if (skillDraftKey) clearDraft(window.localStorage, skillDraftKey, actorId); setPendingDraft(null); }}>丢弃草稿</button></div></div>}
      <fieldset disabled={busy || readOnly} className="space-y-3 disabled:opacity-75">
        <label className="block text-sm">模型配置<select className={inputClass} value={content.model_profile_id} onChange={event => setContent({ ...content, model_profile_id: Number(event.target.value) })}><option value={0}>请选择模型</option>{models.map(model => <option key={model.id} value={model.id}>{model.name} · {model.provider_type}/{model.model_name}</option>)}</select></label>
        <label className="block text-sm">系统提示词<textarea className={inputClass} rows={5} value={content.system_prompt} onChange={event => setContent({ ...content, system_prompt: event.target.value })}/></label>
        <label className="block text-sm">输入模板<textarea ref={templateRef} className={`${inputClass} font-mono`} rows={5} value={content.user_prompt_template} onChange={event => setContent({ ...content, user_prompt_template: event.target.value })}/></label>
        <div className="flex flex-wrap gap-2" aria-label="插入模板变量">{["subject", "facts", "policy_evidence", "gaps"].map(variable => <button key={variable} className={buttonClass} onClick={() => insertVariable(variable)}>插入 {variable}</button>)}</div>
        <p className="text-xs text-slate-500">必须保留 subject、facts、policy_evidence、gaps 四个变量。引用校验与禁用工具策略由服务端强制执行。</p>
        <details><summary className="cursor-pointer text-sm">{(skill.task_key === "requirement_candidate_generation" || skill.task_key === "requirement_document_assistance" || MAPPING_TASKS.includes(skill.task_key)) ? "固定业务输入与预算" : "血缘上下文范围与预算"}</summary><div className="mt-2 grid gap-2 sm:grid-cols-2">
          {skill.task_key === "requirement_document_assistance" ? <p className="text-sm sm:col-span-2">使用明确的固定需求修订，整理四类带引用的文档候选，仅允许本地模型，不自动写回正文。</p> : skill.task_key === "requirement_candidate_generation" ? <p className="text-sm sm:col-span-2">使用需求生成任务已经固定的字段、章节与资料；只生成待人工采纳的候选。</p> : MAPPING_TASKS.includes(skill.task_key) ? <p className="text-sm sm:col-span-2">使用映射任务已有的授权上下文与固定快照；生成后仍检查人工内容、权限及并发变化。</p> : <>
          {Object.entries(OPTIONAL_PROVIDERS).map(([key, label]) => <label className="flex items-center gap-2 text-sm" key={key}><input type="checkbox" checked={policy.providers.includes(key)} onChange={event => setContent({ ...content, context_policy: { ...policy, providers: event.target.checked ? [...policy.providers, key] : policy.providers.filter(value => value !== key) } })}/>{label}</label>)}
          <label className="text-sm">最大路径深度<input type="number" min={1} max={10} className={inputClass} value={policy.max_depth} onChange={event => setContent({ ...content, context_policy: { ...policy, max_depth: Number(event.target.value) } })}/></label>
          <label className="text-sm">最多路径数<input type="number" min={1} max={100} className={inputClass} value={policy.max_paths} onChange={event => setContent({ ...content, context_policy: { ...policy, max_paths: Number(event.target.value) } })}/></label>
          </>}
          <label className="text-sm">输入字节预算上限<input type="number" min={256} max={256000} className={inputClass} value={policy.max_input_bytes} onChange={event => setContent({ ...content, context_policy: { ...policy, max_input_bytes: Number(event.target.value) } })}/></label>
        </div><p className="mt-2 text-xs text-slate-500">仍受模型上下文上限约束。超限会阻断并提示缩小范围；画像只读已有统计，历史缺失明确列为缺口。</p></details>
        <button className={buttonClass} disabled={!content.model_profile_id} onClick={() => void action(save)}>保存草稿</button>
      </fieldset>
      {active && <div className="flex flex-wrap gap-2">
        <button disabled={busy} className={buttonClass} onClick={() => void action(async () => { setDetail(await apiPost(`${root}/versions/${active.version_no}/validate?test_project_id=${testProjectId}`, {})); })}>校验发布条件</button>
        {active.status === "testing" && <button disabled={busy || !capabilities.can_edit} className={buttonClass} onClick={() => void action(() => transition("submit"))}>提交独立审批</button>}
        {active.status === "pending_approval" && <><button disabled={busy || !canApprove} className={buttonClass} onClick={() => void action(() => transition("publish"))}>审批并发布绑定（机构审批人）</button>{!canApprove && <p className="w-full text-sm text-slate-600">需要具有本机构审批权限且未创建或编辑此版本的独立审批人处理。</p>}</>}
        {["testing", "pending_approval"].includes(active.status) && <button disabled={busy || !capabilities.can_edit} className={buttonClass} onClick={() => void action(() => transition("return-to-draft"))}>退回草稿并使测试失效</button>}
        {active.status === "published" && <button disabled={busy || !capabilities.can_publish} className={buttonClass} onClick={() => void action(() => transition("deprecate"))}>停用新增绑定</button>}
        {["published", "deprecated", "archived"].includes(active.status) && <button disabled={busy || !capabilities.can_edit} className={buttonClass} onClick={() => void action(async () => { const item = await apiPost<Version>(`${root}/versions/${active.version_no}/restore`, {}); await refresh(item.id); setNotice("已恢复为新草稿，需要重新测试和审批。"); })}>恢复为新草稿</button>}
      </div>}
      {active && versions.length > 1 && <div className="flex flex-wrap items-end gap-2"><label className="text-sm">对比版本<select aria-label="对比版本" className={inputClass} value={compareVersion} disabled={busy} onChange={event => setCompareVersion(event.target.value)}><option value="">请选择版本</option>{versions.filter(item => item.id !== active.id).map(item => <option key={item.id} value={item.version_no}>v{item.version_no} · {STATUS[item.status]}</option>)}</select></label><button className={buttonClass} disabled={busy || dirty || !compareVersion || Number(compareVersion) === active.version_no} onClick={() => void action(async () => setDetail(await apiPost(`${root}/versions/${active.version_no}/diff`, { other_version: Number(compareVersion) })))}>查看版本差异</button></div>}
      <section className="space-y-3 border-t pt-4"><h3 className="font-semibold">固定测试用例与运行</h3>
        <p className="text-xs text-slate-500">当前项目有 {cases.length} 个用例。真实模型测试会调用所选模型服务；Mock 与回放不能代替真实模型结果。</p>
        <details><summary className="cursor-pointer text-sm">添加固定用例（技术配置）</summary><label className="mt-2 block text-sm">用例 JSON（name、input、assertions）<textarea aria-label="测试用例 JSON" className={`${inputClass} font-mono`} rows={8} value={caseText} onChange={event => setCaseText(event.target.value)} disabled={busy}/></label><button className={buttonClass} disabled={busy || !capabilities.can_edit || !caseText.trim()} onClick={() => void action(async () => { await apiPost(`${root}/test-cases`, JSON.parse(caseText)); await refresh(active?.id); setCaseText(""); setNotice("固定用例已保存，发布前需重新测试。"); })}>保存测试用例</button></details>
        <div className="flex flex-wrap items-center gap-2"><label className="text-sm">验证类型<select className={inputClass} value={mode} disabled={busy} onChange={event => setMode(event.target.value)}>{Object.entries(MODES).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
          <button className={buttonClass} disabled={busy || dirty || !capabilities.can_edit || !active || !["draft", "testing"].includes(active.status) || !cases.length} onClick={() => void action(async () => { if (!active) return; const run = await apiPost<Run>(`${root}/test-runs`, { version: active.version_no, project_id: testProjectId, mode, expected_lock_version: active.lock_version }); await refresh(active.id); setDetail(run); })}>运行所选测试</button></div>
        <div className="space-y-2">{runs.filter(run => run.version_id === active?.id).map(run => <button key={run.id} disabled={busy} className="block w-full rounded border p-2 text-left text-sm" onClick={() => void action(async () => { setDetail({ ...run, results: await apiGet(`/ai-skill-test-runs/${run.id}/results`) }); })}>#{run.id} · {MODES[run.mode]} · {run.status} · {run.metrics.passed}/{run.metrics.total}</button>)}</div>
      </section>
      {detail !== null && <><SkillValidationDetail value={detail}/><details><summary className="cursor-pointer text-sm">完整验证记录</summary><pre aria-label="服务端验证结果" className="max-h-96 overflow-auto whitespace-pre-wrap break-all rounded bg-slate-50 p-3 text-xs">{JSON.stringify(detail, null, 2)}</pre></details></>}
      {selectedRun?.mode === "human_review" && <section aria-label="独立人工评审" className="space-y-2 rounded border p-3 text-sm">
        <h3 className="font-semibold">人工评审 #{selectedRun.id}</h3>
        <p>请核对上方用例与完整验证记录。人工评审不计作真实模型测试，也不直接发布版本。</p>
        {selectedRun.status === "pending_review" ? <>
          <label className="block">评审意见<textarea aria-label="评审意见" className={inputClass} maxLength={2000} value={reviewComment} disabled={busy || !capabilities.can_publish || selectedRun.created_by === capabilities.actor_id} onChange={event => setReviewComment(event.target.value)}/></label>
          {(!capabilities.can_publish || selectedRun.created_by === capabilities.actor_id) && <p>需要具有机构审批权限且未发起本次评审的独立评审人处理。</p>}
          <div className="flex gap-2">{[true, false].map(passed => <button key={String(passed)} className={buttonClass} disabled={busy || dirty || !reviewComment.trim() || !capabilities.can_publish || selectedRun.created_by === capabilities.actor_id} onClick={() => void action(async () => {
            const reviewed = await apiPost<Run>(`/ai-skill-test-runs/${selectedRun.id}/human-review`, { passed, comment: reviewComment.trim() });
            await refresh(active?.id); setDetail({ ...reviewed, results: await apiGet(`/ai-skill-test-runs/${selectedRun.id}/results`) }); setReviewComment(""); setNotice("人工评审意见已记录。");
          })}>{passed ? "评审通过" : "评审不通过"}</button>)}</div>
        </> : <p>已完成：{selectedRun.status === "passed" ? "通过" : "不通过"}。{selectedRun.metrics.review_comment}</p>}
      </section>}
    </section>
  </div>;
}

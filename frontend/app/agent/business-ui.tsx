"use client";

import {
  ArrowRight, BookOpen, Check, ChevronDown, ClipboardCheck, Clock3, ExternalLink, FileText, ListChecks,
  Play, RefreshCw, ShieldAlert, X,
} from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import {
  decisionPayload, subjectChoicePayload,
  type ArtifactView, type BasisKind, type CitationView, type ConclusionView, type ProcessPhaseView,
  type StatusTone, type TaskDetailView, type TaskRowView, type WaitingGateView,
} from "@/app/agent/view-model";
import { gapCodeLabel } from "@/lib/user-message.mjs";

function textOrNull(value: unknown): string {
  return typeof value === "string" && value.trim() ? value : "";
}

/** 静态字面量类名：Tailwind 只会保留源码里出现过的类名。 */
export const TONE_CLASS: Record<StatusTone, string> = {
  success: "badge-success",
  danger: "badge-danger",
  warning: "badge-warning",
  info: "badge-info",
  neutral: "badge-neutral",
};

export function ToneBadge({ tone, label, ariaLabel }: { tone: StatusTone; label: string; ariaLabel?: string }) {
  return <span aria-label={ariaLabel || `状态：${label}`} className={TONE_CLASS[tone]}>{label}</span>;
}

export function LoadingBlock({ text }: { text: string }) {
  return (
    <p aria-live="polite" className="empty-state">
      <RefreshCw aria-hidden className="animate-spin text-slate-400" size={16} />
      {text}
    </p>
  );
}

/** 加载失败 ≠ 没有数据：必须给“重新加载”，不能显示空态。 */
export function ErrorBlock({ title, message, onRetry }: { title: string; message: string; onRetry?: () => void }) {
  return (
    <div className="empty-state border-coral-200 bg-coral-50/60 text-coral-800" role="alert">
      <ShieldAlert aria-hidden size={18} />
      <p className="font-medium">{title}</p>
      <p className="max-w-xl text-xs text-coral-700">{message}</p>
      {onRetry ? (
        <button className="button-secondary mt-1" onClick={onRetry} type="button">
          <RefreshCw size={14} />重新加载
        </button>
      ) : null}
    </div>
  );
}

export function EmptyBlock({ title, hint, action }: { title: string; hint: string; action?: React.ReactNode }) {
  return (
    <div className="empty-state">
      <p className="font-medium text-slate-700">{title}</p>
      <p className="max-w-xl text-xs text-slate-500">{hint}</p>
      {action}
    </div>
  );
}

/** 列表一行：业务对象、状态、结果摘要、更新时间、唯一的主动作。 */
/**
 * 列表行：整行可点进详情。用原生 <a> + 内部路由回调，既支持中键/新标签打开，
 * 也避免 Next Link 客户端跳转绕过页面的 URL 状态同步（否则点击后仍停在列表）。
 */
export function TaskListRow({ view, href, active, onOpen }: {
  view: TaskRowView; href: string; active: boolean; onOpen?: (event: React.MouseEvent<HTMLAnchorElement>) => void;
}) {
  return (
    <div className={`border-b border-line px-5 py-3 last:border-0 ${active ? "bg-pine-50/70" : "hover:bg-mist/70"}`}>
      <div className="flex flex-wrap items-start gap-x-3 gap-y-1">
        <a className="min-w-0 flex-1 text-sm font-medium text-ink hover:text-pine-700 hover:underline"
          href={href} onClick={onOpen}>
          {view.title}
        </a>
        <ToneBadge label={view.stateLabel} tone={view.stateTone} />
        {view.signals.map((signal) => (
          <span className="badge-neutral" key={signal}>{signal}</span>
        ))}
      </div>
      <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-slate-500">
        <span>业务对象：{view.objectLabel}</span>
        <span className="text-slate-300">|</span>
        <span>{view.summaryLabel}</span>
        <span className="text-slate-300">|</span>
        <span className="inline-flex items-center gap-1"><Clock3 aria-hidden size={12} />{view.updatedLabel}</span>
      </div>
      <p className="mt-1 text-sm text-slate-700">{view.summary}</p>
      <div className="mt-2">
        <a className="button-secondary h-8 px-3 text-xs" href={href} onClick={onOpen}>
          {view.action.label}
          <ArrowRight size={13} />
        </a>
      </div>
    </div>
  );
}

const ACTION_ICON: Record<string, typeof Play> = {
  retry: RefreshCw,
  handle: ClipboardCheck,
  review: ClipboardCheck,
  artifacts: FileText,
  process: ListChecks,
  refresh: RefreshCw,
};

/**
 * 首屏主卡：业务状态 + 任务标题 + 结论 + 依据信号 + 唯一主操作。
 * 状态、结论、下一步动作必须在同一屏内，不拆成多张卡片把它们挤下去。
 */
export function ConclusionCard({
  detail, busy, canHandle = true, onAction, fullTextOpen, onToggleFullText, moreActions,
}: {
  detail: TaskDetailView;
  busy: boolean;
  /** 当前账号是否有“批准/复核”权限；没有时主操作置灰并说明原因，而不是让用户点了才报错。 */
  canHandle?: boolean;
  onAction: (key: string) => void;
  fullTextOpen: boolean;
  onToggleFullText: () => void;
  moreActions?: React.ReactNode;
}) {
  const conclusion: ConclusionView = detail.conclusion;
  const PrimaryIcon = ACTION_ICON[conclusion.primaryAction.key] || Play;
  const needsPermission = conclusion.primaryAction.key === "handle" || conclusion.primaryAction.key === "review";
  const primaryBlocked = needsPermission && !canHandle;
  return (
    <section aria-label="任务结论" className="panel">
      <div className="panel-body space-y-2">
        <div className="flex flex-wrap items-center gap-2">
          <ToneBadge label={detail.stateLabel} tone={detail.stateTone} />
          {conclusion.signals.map((signal) => (
            <ToneBadge key={signal.label} label={signal.label} tone={signal.tone} />
          ))}
          <span className="ml-auto inline-flex items-center gap-1 text-xs text-slate-500">
            <Clock3 aria-hidden size={12} />更新于 {detail.updatedLabel}
          </span>
          {moreActions}
        </div>
        <div>
          <h2 className="text-xl font-semibold tracking-tight text-ink break-words">{detail.title}</h2>
          <p className="mt-1 text-xs text-slate-500">业务对象：{detail.objectLabel}</p>
        </div>
        <div>
          <h3 className="text-base font-semibold text-ink">{conclusion.heading}</h3>
          <p className="mt-1 whitespace-pre-wrap text-sm leading-6 text-slate-700">
            {fullTextOpen && conclusion.fullText ? conclusion.fullText : conclusion.body}
          </p>
          {conclusion.hasFullText ? (
            <button className="mt-1 inline-flex items-center gap-1 text-xs font-medium text-pine-700 hover:underline"
              onClick={onToggleFullText} type="button">
              {fullTextOpen ? "收起全文" : "查看全文"}
              <ChevronDown aria-hidden className={fullTextOpen ? "rotate-180 transition-transform" : "transition-transform"} size={13} />
            </button>
          ) : null}
        </div>
        <p className="text-xs text-slate-500">{conclusion.sourceLabel}</p>
        {detail.conflicts.length ? (
          <div className="rounded-lg border border-gold-200 bg-gold-50 px-3 py-2 text-xs text-gold-800" role="status">
            <p className="font-medium">存在未解决的口径冲突，结论待人工确认。</p>
            <p className="mt-0.5">
              {detail.conflicts.map((conflict) => conflict.message).join("；")} 请到「依据」中打开双方原文核对。
            </p>
          </div>
        ) : null}
        <div className="flex flex-wrap items-center gap-2 border-t border-line pt-2">
          <button className="button-primary" disabled={busy || primaryBlocked}
            onClick={() => onAction(conclusion.primaryAction.key)} type="button">
            <PrimaryIcon size={15} />{busy ? "处理中…" : conclusion.primaryAction.label}
          </button>
          {primaryBlocked ? (
            <span className="text-xs text-coral-700">
              当前账号没有“终审”权限，请联系项目负责人在「任务」中处理。
            </span>
          ) : null}
          {conclusion.secondaryActions.map((action) => (
            <button className="button-secondary" key={action.key} onClick={() => onAction(action.key)} type="button">
              {action.label}
            </button>
          ))}
          <span className="text-[11px] text-slate-400">AI 只生成建议，结论与产出物须经人工确认后才能用于报送。</span>
        </div>
      </div>
    </section>
  );
}

/** 依据区：真实引用逐条可读；没有引用时按依据强度说明，不用模型生成内容填充。 */
export function EvidenceSection({
  citations, gaps, evidenceCount, basisKind, onOpenSource, candidates = [], conflicts = [],
}: {
  citations: CitationView[];
  gaps: Array<{ code: string; message: string; stepKey?: string | null }>;
  evidenceCount: number;
  basisKind: BasisKind;
  onOpenSource?: (citation: CitationView) => void;
  candidates?: CitationView[];
  conflicts?: Array<{ topic: string; message: string; citations: CitationView[] }>;
}) {
  const emptyBasisText: Record<string, string> = {
    metadata_only: "本次结论依据项目元数据目录（表/字段信息），没有引用监管制度原文，属于口径参考，需人工确认。",
    insufficient: "证据不足：没有找到足够依据，这条结论不能直接使用，建议补充资料后重新运行。",
    missing: "本次没有可追溯的引用依据。结论仅来自执行过程，需人工确认后再使用。",
    none: "本次没有产出结论，因此没有依据可展示。",
    cited: "",
  };
  // 四状态分开：送进模型上下文 ≠ 答案实际引用。页面必须能看出哪些只是上下文候选。
  const citedCount = citations.filter((citation) => citation.usage === "cited").length;
  return (
    <section aria-label="结论依据" className="panel" id="agent-evidence">
      <div className="panel-header flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-sm font-semibold text-ink">依据</h2>
        <span className="text-xs text-slate-500">
          {citations.length
            ? `可追溯引用 ${citations.length} 条${citedCount ? `（结论实际引用 ${citedCount} 条）` : "（结论未直接引用编号）"}`
            : "无可追溯引用"} · 证据 {evidenceCount} 条
        </span>
      </div>
      <div className="panel-body space-y-3">
        {conflicts.length ? (
          <div className="rounded-lg border border-gold-200 bg-gold-50 p-3" role="status">
            <p className="text-sm font-medium text-gold-900">存在未解决的口径冲突</p>
            {conflicts.map((conflict, index) => (
              <div className="mt-2" key={`${conflict.topic}-${index}`}>
                <p className="text-xs text-gold-800">{conflict.message}</p>
                <div className="mt-1 flex flex-wrap gap-2">
                  {conflict.citations.map((citation, side) => (
                    <button className="button-secondary text-xs" key={`${citation.title}-${side}`}
                      onClick={() => onOpenSource?.(citation)} type="button">
                      <BookOpen size={14} />打开原文：{citation.title}
                    </button>
                  ))}
                </div>
              </div>
            ))}
          </div>
        ) : null}
        {citations.length ? (
          <ol className="space-y-2">
            {citations.map((citation, index) => {
              const locator = citation.locator || {};
              const location = [
                textOrNull(locator.sheet_name),
                textOrNull(locator.cell_range),
                locator.page_no ? `第 ${locator.page_no} 页` : "",
                locator.paragraph_index ? `段落 ${locator.paragraph_index}` : "",
                textOrNull(locator.heading),
              ].filter(Boolean).join(" · ");
              const canOpen = Boolean(citation.documentId || citation.knowledgeUnitId);
              return (
                <li className="rounded-lg border border-line px-3 py-2" key={`${citation.title}-${index}`}>
                  <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
                    <span className="badge-neutral">{citation.sourceLabel}</span>
                    {citation.usage === "cited" ? (
                      <span className="badge-success">结论已引用</span>
                    ) : (
                      <span className="badge-neutral">上下文候选</span>
                    )}
                    {citation.sourceKind === "institution_question" ? (
                      <span className="badge-warning">机构答疑</span>
                    ) : null}
                    {citation.sourceKind === "reference_material" ? (
                      <span className="badge-warning">参考材料</span>
                    ) : null}
                    <span className="text-[11px] text-slate-400">依据 {index + 1}</span>
                    {canOpen && onOpenSource ? (
                      <button className="button-secondary ml-auto text-xs" onClick={() => onOpenSource(citation)} type="button">
                        <BookOpen size={14} />查看原文
                      </button>
                    ) : null}
                  </div>
                  <p className="mt-1 text-sm font-medium text-ink">{citation.title}</p>
                  {location ? <p className="mt-0.5 text-[11px] text-slate-500">定位：{location}</p> : null}
                  {citation.quote ? <p className="mt-1 text-sm text-slate-600">“{citation.quote}”</p> : null}
                </li>
              );
            })}
          </ol>
        ) : (
          <p className="rounded-lg border border-dashed border-line bg-mist/60 px-3 py-2 text-sm text-slate-600">
            {emptyBasisText[basisKind] || emptyBasisText.missing}
          </p>
        )}
        {candidates.length ? (
          <details className="rounded-lg border border-line bg-mist/30 px-3 py-2">
            <summary className="cursor-pointer text-xs font-medium text-slate-600">
              相关候选材料（{candidates.length} 条，检索命中但未直接引用）
            </summary>
            <ul className="mt-2 space-y-2">
              {candidates.map((candidate, index) => (
                <li className="flex flex-wrap items-center justify-between gap-2 text-xs text-slate-600"
                  key={`${candidate.title}-${index}`}>
                  <span className="min-w-0 break-words">
                    {candidate.title}
                    {candidate.quote ? `：${candidate.quote.slice(0, 60)}` : ""}
                  </span>
                  <button className="button-secondary text-xs" onClick={() => onOpenSource?.(candidate)} type="button">
                    <BookOpen size={14} />查看原文
                  </button>
                </li>
              ))}
            </ul>
          </details>
        ) : null}
        {gaps.length ? (
          <div>
            <div className="text-xs font-medium text-slate-500">依据缺口（{gaps.length}）</div>
            <ul className="mt-1 list-disc space-y-1 pl-5 text-sm text-slate-700">
              {gaps.map((gap, index) => (
                <li key={`${gap.code}-${index}`}>
                  {gapCodeLabel(gap.code)}{gap.message ? `：${gap.message}` : ""}
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </div>
    </section>
  );
}

/** 产出区：草稿预览 + 审核状态 + 全文入口 + 关联记录。 */
export function ArtifactSection({ artifacts, canReview = false, running = false }: {
  artifacts: ArtifactView[]; canReview?: boolean; running?: boolean;
}) {
  // 没有产出物时不占一整块面板，只留一行说明，避免把依据/过程挤到首屏之外。
  if (!artifacts.length) {
    return (
      <p className="rounded-lg border border-dashed border-line bg-mist/60 px-3 py-2 text-sm text-slate-600" id="agent-artifacts">
        {running ? "任务仍在执行，产出物尚未生成。" : "本次执行没有生成产出物。"}
      </p>
    );
  }
  return (
    <section aria-label="产出物" className="panel" id="agent-artifacts">
      <div className="panel-header flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-sm font-semibold text-ink">产出物</h2>
        <span className="text-xs text-slate-500">{running ? "任务仍在执行，内容会继续更新" : `${artifacts.length} 份`}</span>
      </div>
      <div className="panel-body space-y-3">
        {artifacts.map((artifact) => (
          <article className="rounded-lg border border-line px-4 py-3" key={artifact.id}>
            <div className="flex flex-wrap items-center gap-2">
              <span className="badge-info">{artifact.typeLabel}</span>
              <ToneBadge label={artifact.statusLabel} tone={artifact.statusTone} />
              <h3 className="min-w-0 flex-1 text-sm font-medium text-ink">{artifact.title}</h3>
            </div>
            <p className="mt-2 whitespace-pre-wrap text-sm text-slate-700">{artifact.summary || "（无摘要）"}</p>
            {artifact.fullText && artifact.fullText.length > artifact.summary.length ? (
              <details className="mt-2">
                <summary className="cursor-pointer text-xs font-medium text-pine-700">查看完整内容</summary>
                <div className="mt-2 max-h-72 overflow-y-auto whitespace-pre-wrap rounded-lg bg-mist/60 px-3 py-2 text-sm text-slate-700">
                  {artifact.fullText}
                </div>
              </details>
            ) : null}
            <div className="mt-2 flex flex-wrap items-center gap-3 text-xs text-slate-500">
              {artifact.citations.length ? <span>引用依据 {artifact.citations.length} 条</span> : <span>无引用依据</span>}
              {artifact.statusTone === "warning" ? <span className="text-gold-700">等待人工复核后才能正式使用</span> : null}
              {artifact.reviewTaskId && canReview ? (
                <Link className="inline-flex items-center gap-1 font-medium text-pine-700 hover:underline"
                  href={`/tasks/${artifact.reviewTaskId}`}>
                  去复核<ExternalLink aria-hidden size={12} />
                </Link>
              ) : null}
              {artifact.reviewTaskId && !canReview ? (
                <span className="text-slate-500">待项目负责人复核</span>
              ) : null}
              {artifact.refHref ? (
                <Link className="inline-flex items-center gap-1 text-pine-700 hover:underline" href={artifact.refHref}>
                  查看关联记录<ExternalLink aria-hidden size={12} />
                </Link>
              ) : null}
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}

/** 执行过程：默认收起，业务语言表达，不含工具名/模型/异常栈。 */
export function ProcessDisclosure({
  phases, open, onToggle,
}: {
  phases: ProcessPhaseView[];
  open: boolean;
  onToggle: () => void;
}) {
  return (
    <section aria-label="执行过程" className="panel" id="agent-process">
      <button aria-expanded={open} className="panel-header flex w-full items-center justify-between gap-2 text-left"
        onClick={onToggle} type="button">
        <span className="text-sm font-semibold text-ink">执行过程（{phases.length} 个环节）</span>
        <span className="inline-flex items-center gap-1 text-xs text-slate-500">
          {open ? "收起" : "展开查看"}
          <ChevronDown aria-hidden className={open ? "rotate-180 transition-transform" : "transition-transform"} size={14} />
        </span>
      </button>
      {open ? (
        <ol className="panel-body space-y-2">
          {phases.length ? phases.map((phase, index) => (
            <li className="flex flex-wrap items-start gap-x-3 gap-y-1 rounded-lg border border-line px-3 py-2" key={`${phase.key}-${index}`}>
              <span className="font-mono text-xs text-slate-400">{String(index + 1).padStart(2, "0")}</span>
              <span className="min-w-0 flex-1 text-sm font-medium text-ink">{phase.label}</span>
              <ToneBadge label={phase.stateLabel} tone={phase.tone} />
              {phase.detail ? <p className="w-full text-xs text-slate-600">{phase.detail}</p> : null}
            </li>
          )) : <li className="text-sm text-slate-500">尚无执行环节。</li>}
        </ol>
      ) : null}
    </section>
  );
}

/** 人工确认：说明为什么需要人、需要人做什么，并给出真实候选对象。 */
export function WaitingGateCard({
  waiting, busy, canAct, onSubmit,
}: {
  waiting: WaitingGateView;
  busy: boolean;
  canAct: boolean;
  onSubmit: (body: Record<string, unknown>) => Promise<unknown>;
}) {
  // 业务确认必须由人做出：不预先替用户勾选任何候选。
  const [fieldId, setFieldId] = useState<number | null>(null);
  const [comment, setComment] = useState("");
  const [error, setError] = useState("");

  async function submit(decision: "edit_and_approve" | "reject") {
    setError("");
    if (decision === "reject" && !comment.trim()) {
      setError("拒绝时需要填写原因，原因会写入审计记录。");
      return;
    }
    if (decision === "edit_and_approve" && fieldId === null) {
      setError("请先选择一个分析对象。");
      return;
    }
    try {
      const edited = decision === "edit_and_approve" ? JSON.stringify(subjectChoicePayload(fieldId)) : "{}";
      await onSubmit(decisionPayload(decision, comment, edited));
      setComment("");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "提交失败，请稍后重试。");
    }
  }

  return (
    <section aria-label="待你处理" className="panel border-gold-200" id="agent-waiting">
      <div className="panel-body space-y-2">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="text-sm font-semibold text-gold-800">{waiting.title}</h2>
          <span className="text-xs text-gold-700">任务已暂停，未确认前不会继续执行下游步骤。</span>
        </div>
        <div className="grid gap-x-4 gap-y-1 text-sm md:grid-cols-2">
          <p className="text-slate-700"><span className="text-xs font-medium text-slate-500">为什么需要你处理：</span>{waiting.reason}</p>
          <p className="text-slate-700"><span className="text-xs font-medium text-slate-500">需要你做什么：</span>{waiting.requirement}</p>
        </div>
        {waiting.candidates.length ? (
          <fieldset className="space-y-2">
            <legend className="text-xs font-medium text-slate-500">请选择分析对象（{waiting.candidates.length} 个候选）</legend>
            <div className="grid gap-2 md:grid-cols-2">
              {waiting.candidates.map((candidate) => (
                <label className={`flex cursor-pointer items-center gap-2 rounded-lg border px-3 py-1.5 text-sm ${
                  fieldId === candidate.id ? "border-pine-300 bg-pine-50" : "border-line bg-white hover:bg-mist/70"}`}
                  key={candidate.id}>
                  <input checked={fieldId === candidate.id} name="agent-candidate" onChange={() => setFieldId(candidate.id)}
                    type="radio" value={candidate.id} />
                  <span className="min-w-0 flex-1">
                    <span className="font-medium text-ink">{candidate.name}</span>
                    <span className="ml-2 font-mono text-xs text-slate-500">{candidate.code}</span>
                  </span>
                  {candidate.score !== null ? (
                    <span className="text-xs text-slate-500">匹配度 {(candidate.score * 100).toFixed(0)}%</span>
                  ) : null}
                </label>
              ))}
            </div>
          </fieldset>
        ) : (
          <p className="rounded-lg border border-dashed border-line bg-mist/60 px-3 py-2 text-sm text-slate-600">
            系统没有给出可选项。请填写原因后拒绝，或联系项目负责人补充资料。
          </p>
        )}
        <textarea aria-label="处理说明" className="control min-h-16" onChange={(event) => setComment(event.target.value)}
          placeholder="处理说明（拒绝时必须填写原因，会写入审计）" value={comment} />
        {error ? <p className="rounded-lg border border-coral-200 bg-coral-50 px-3 py-2 text-xs text-coral-700" role="alert">{error}</p> : null}
        {canAct ? (
          <div className="flex flex-wrap items-center gap-2">
            {waiting.candidates.length ? (
              <button className="button-primary" disabled={busy || fieldId === null}
                onClick={() => void submit("edit_and_approve")} type="button">
                <Check size={15} />{busy ? "正在提交…" : "按所选对象继续"}
              </button>
            ) : null}
            <button className="button-secondary" disabled={busy} onClick={() => void submit("reject")} type="button">
              <X size={15} />拒绝该对象
            </button>
            {waiting.candidates.length && fieldId === null ? (
              <span className="text-xs text-slate-500">请先在候选中选择分析对象，再继续。</span>
            ) : null}
          </div>
        ) : (
          <p className="rounded-lg border border-gold-200 bg-gold-50 px-3 py-2 text-xs text-gold-800">
            当前账号没有此环节的处理权限，请联系项目负责人处理（需要“终审”权限）。
          </p>
        )}
      </div>
    </section>
  );
}

export type ScenarioCard = {
  key: string;
  title: string;
  description: string;
  output: string;
  example: string;
  needsHuman: string;
};

export const TASK_SCENARIOS: ScenarioCard[] = [
  {
    key: "knowledge_question", title: "查口径 / 字段清单",
    description: "问某张表有哪些字段、某个字段的填报口径是什么。",
    output: "问答结论 + 引用依据",
    example: "互联网贷款合作机构信息表都有哪些字段？",
    needsHuman: "只读问答，通常不需要人工确认。",
  },
  {
    key: "policy_comparison", title: "制度与实现比对",
    description: "对比监管要求与当前 SQL 实现，找出差异与缺口。",
    output: "差异清单 + 监管依据",
    example: "比对合作机构信息报送要求与当前实现是否一致。",
    needsHuman: "涉及结论定稿时可能需要人工确认。",
  },
  {
    key: "sql_impact_analysis", title: "字段变更影响分析",
    description: "评估字段或 SQL 变更会影响哪些下游对象。",
    output: "受影响对象 + 变更点",
    example: "分析 hyf_ln_pa_online_info 字段变更对下游报表的影响。",
    needsHuman: "影响范围结论需业务复核。",
  },
  {
    key: "report_drafting", title: "生成口径说明草稿",
    description: "按模板起草字段口径说明，提交人工复核。",
    output: "草稿 + 审核状态",
    example: "生成互联网贷款合作机构信息表的字段口径说明草稿。",
    needsHuman: "会生成草稿，必须人工复核后才能使用。",
  },
];

/** 新建任务：先讲业务场景与预期产出，技术配置收在“高级设置”里。 */
export function CreateTaskPanel({
  objective, onObjectiveChange, onSubmit, busy, scenarioKey, onScenarioChange, canRun,
}: {
  objective: string;
  onObjectiveChange: (value: string) => void;
  onSubmit: () => void;
  busy: boolean;
  scenarioKey: string;
  onScenarioChange: (value: string) => void;
  canRun: boolean;
}) {
  const [open, setOpen] = useState(false);
  return (
    <section aria-label="新建任务" className="panel">
      <button aria-expanded={open} className="panel-header flex w-full items-center justify-between gap-2 text-left"
        onClick={() => setOpen((value) => !value)} type="button">
        <span className="text-sm font-semibold text-ink">新建任务</span>
        <span className="inline-flex items-center gap-1 text-xs text-slate-500">
          {open ? "收起" : "展开填写业务目标"}
          <ChevronDown aria-hidden className={open ? "rotate-180 transition-transform" : "transition-transform"} size={14} />
        </span>
      </button>
      {open ? (
        <div className="panel-body space-y-3">
          <p className="text-xs text-slate-500">选一个业务场景作为起点，再补充具体对象。提交后立即返回，规划与执行在后台进行。</p>
          <div className="grid gap-2 sm:grid-cols-2">
            {TASK_SCENARIOS.map((scenario) => (
              <button className={`rounded-lg border px-3 py-2 text-left ${
                scenarioKey === scenario.key ? "border-pine-300 bg-pine-50" : "border-line bg-white hover:bg-mist/70"}`}
                key={scenario.key} onClick={() => {
                  onScenarioChange(scenario.key);
                  if (!objective.trim()) onObjectiveChange(scenario.example);
                }} type="button">
                <span className="block text-sm font-medium text-ink">{scenario.title}</span>
                <span className="mt-0.5 block text-xs text-slate-600">{scenario.description}</span>
                <span className="mt-1 block text-[11px] text-slate-500">预期产出：{scenario.output}</span>
                <span className="block text-[11px] text-slate-500">{scenario.needsHuman}</span>
              </button>
            ))}
          </div>
          <label className="block">
            <span className="text-xs font-medium text-slate-500">业务目标（必填，至少 4 个字）</span>
            <textarea className="control mt-1 min-h-20" onChange={(event) => onObjectiveChange(event.target.value)}
              placeholder="例如：互联网贷款合作机构信息表都有哪些字段？" value={objective} />
          </label>
          {canRun ? (
            <details className="rounded-lg border border-line bg-mist/40 px-3 py-2">
              <summary className="cursor-pointer text-xs font-medium text-slate-600">高级设置（技术选项，一般不用改）</summary>
              <ul className="mt-2 space-y-1 text-[11px] text-slate-500">
                <li>执行方式：创建后在后台规划并执行，可在详情页查看进度。</li>
                <li>规划失败时：自动回退到固定执行计划，不会中断任务。</li>
                <li>失败重试：最多 3 次；仍失败会标记为“处理失败”并给出原因。</li>
              </ul>
              <p className="mt-2 text-[11px] text-slate-400">以上由平台统一配置，需要调整请联系平台管理员。</p>
            </details>
          ) : null}
          <div className="flex flex-wrap items-center gap-2">
            <button className="button-primary" disabled={busy || !canRun} onClick={onSubmit} type="button">
              <Play size={15} />{busy ? "正在创建…" : "创建并执行任务"}
            </button>
            <span className="text-xs text-slate-500">只读问答直接给结论；生成交付物的环节会停下来等人工确认。</span>
          </div>
          {canRun ? null : (
            <p className="rounded-lg border border-gold-200 bg-gold-50 px-3 py-2 text-xs text-gold-800">
              当前账号没有创建任务的权限，请联系项目负责人。
            </p>
          )}
        </div>
      ) : null}
    </section>
  );
}


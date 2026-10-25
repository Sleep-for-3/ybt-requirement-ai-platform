"use client";

import { Download, FileCheck2 } from "lucide-react";
import Link from "next/link";
import { useMemo, useState, useEffect, useRef } from "react";

import { SelectedFieldEditor } from "@/components/requirement-workspace/SelectedFieldEditor";
import { AiExplanationPanel } from "@/components/requirement-workspace/AiExplanationPanel";
import { RequirementLineagePanel } from "@/components/requirement-workspace/RequirementLineagePanel";
import type {
  MartField,
  MartTable,
  PendingQuestion,
  ProductScenario,
  TargetTable
} from "@/lib/api";
import { combinedFieldStatus, mappingStatusLabel, mappingStatusTone, preferredMappingContent } from "@/lib/workspace-view-model.mjs";
import { lineageStatusLabel, priorityLabel, questionTypeLabel, resourceKindLabel, statusLabel } from "@/lib/product-language";
import type { FieldWorkspaceRecord, SourceMappingIndex } from "@/components/requirement-workspace/types";
import type { RequirementScope } from "./RequirementScopePanel";
import { RequirementContentEditor } from "./RequirementContentEditor";
import { describeUserMessage } from "@/lib/user-message.mjs";
import { TRACE_FILTERS, fieldTraceStats, filterFieldTrace, traceFilterCount, type TraceFilterKey } from "@/lib/field-trace";
import type { SnapshotDiff } from "@/lib/snapshot-diff";

export type ExportOutcome = {
  fileName: string;
  snapshotId: string;
  snapshotCreated: boolean;
  artifactId: string;
  fileSha256: string;
};

export type RequirementGap = {id:string; field_id:number|null; origin:string; message:string; status:string};
export type RequirementResourceSummary = {kind:string; name:string; code:string; status:string};

type WorkspaceTab = "structured" | "lineage" | "evidence" | "questions" | "document";

const WORKSPACE_TABS: Array<{ id: WorkspaceTab; label: string }> = [
  { id: "structured", label: "结构化口径" },
  { id: "lineage", label: "血缘" },
  { id: "evidence", label: "证据" },
  { id: "questions", label: "待确认" },
  { id: "document", label: "文档预览" }
];

export function DocumentPreview({
  requirementId,
  requirementBackground,
  requirementScope,
  requirementGaps,
  requirementResources,
  contentVersion,
  contentStatus,
  projectName,
  activeTab,
  table,
  scenario,
  records,
  selectedFieldId,
  onSelectField,
  onTabChange,
  martFields,
  martTables,
  sourceMappings,
  evidenceCountByField,
  evidenceForSelected,
  questions,
  detailReady,
  editorDirty,
  onAdoptBusiness,
  onAdoptTechnical,
  onEditorDirtyChange,
  onEditorError,
  onEditorNotice,
  onEditorSaved,
  onShowEvidence,
  onExport,
  onFreezeAndExport,
  snapshotDiffLoader,
  exporting,
  initialFocusFieldId
}: {
  requirementId?: number;
  requirementBackground?: string;
  requirementScope?: RequirementScope;
  requirementGaps?: RequirementGap[];
  requirementResources?: RequirementResourceSummary[];
  contentVersion?: number;
  contentStatus?: string;
  projectName: string;
  activeTab: WorkspaceTab;
  table: TargetTable | null;
  scenario: ProductScenario | null;
  records: FieldWorkspaceRecord[];
  selectedFieldId: number | null;
  onSelectField: (id: number) => void;
  onTabChange: (tab: WorkspaceTab) => void;
  martFields: MartField[];
  martTables: MartTable[];
  sourceMappings: SourceMappingIndex;
  evidenceCountByField: Record<number, number>;
  evidenceForSelected: number;
  questions: PendingQuestion[];
  detailReady: boolean;
  editorDirty?: boolean;
  onAdoptBusiness: () => void;
  onAdoptTechnical: () => void;
  onEditorDirtyChange: (dirty: boolean) => void;
  onEditorError: (message: string) => void;
  onEditorNotice: (message: string) => void;
  onEditorSaved: () => void;
  onShowEvidence: () => void;
  onExport: () => void;
  // 需求模式下导出必须先冻结：调用方负责"冻结 + 导出"，并回报身份信息。
  onFreezeAndExport?: (options: { format: "xlsx" | "docx"; layout: "survey" | "standard" }) => Promise<ExportOutcome | null>;
  // 与"最近一次冻结"的字段级差异；打开预检时现算，避免把过期差异当成事实。
  snapshotDiffLoader?: () => Promise<SnapshotDiff | null>;
  /** 从看板深链进来时带的字段：进入后要定位到它（切到文档预览并高亮）。 */
  initialFocusFieldId?: number | null;
  exporting: boolean;
}) {
  const [traceFilter, setTraceFilter] = useState<TraceFilterKey>("all");
  const [focusedFieldId, setFocusedFieldId] = useState<number | null>(null);
  const [showPreflight, setShowPreflight] = useState(false);
  const [exportFormat, setExportFormat] = useState<"xlsx" | "docx">("xlsx");
  const [exportLayout, setExportLayout] = useState<"survey" | "standard">("survey");
  const [exportOutcome, setExportOutcome] = useState<ExportOutcome | null>(null);
  const [freezing, setFreezing] = useState(false);
  const [snapshotDiff, setSnapshotDiff] = useState<SnapshotDiff | null>(null);
  const [snapshotDiffLoading, setSnapshotDiffLoading] = useState(false);
  const [snapshotDiffError, setSnapshotDiffError] = useState("");
  const openPreflight = async () => {
    setShowPreflight(true);
    if (!snapshotDiffLoader) return;
    setSnapshotDiffLoading(true);
    setSnapshotDiffError("");
    try {
      setSnapshotDiff(await snapshotDiffLoader());
    } catch {
      // 读不到快照内容与"从没冻结过"是两件事：不能把读取失败说成"没有快照"。
      setSnapshotDiff(null);
      setSnapshotDiffError("读取最近一次冻结的快照失败，本次差异暂不可用（不影响导出）。");
    } finally {
      setSnapshotDiffLoading(false);
    }
  };
  const surveyBlocked = exportLayout === "survey" && exportFormat !== "xlsx";
  const runFreezeAndExport = async () => {
    if (!onFreezeAndExport || surveyBlocked) return;
    setFreezing(true);
    try {
      const outcome = await onFreezeAndExport({ format: exportFormat, layout: exportLayout });
      if (outcome) setExportOutcome(outcome);
    } finally {
      setFreezing(false);
    }
  };
  const rowRefs = useRef<Record<number, HTMLTableRowElement | null>>({});
  const traceStats = useMemo(() => fieldTraceStats(records, requirementGaps || []), [records, requirementGaps]);
  const visibleRecords = useMemo(() => filterFieldTrace(records, traceFilter, requirementGaps || []), [records, traceFilter, requirementGaps]);
  // 定位必须"落在看得见的行上"：如果当前覆盖度筛选把这个字段过滤掉了，先切回全部字段，
  // 否则用户点了"定位字段"却看不到它，会以为按钮没生效。
  const focusField = (fieldId: number) => {
    setFocusedFieldId(fieldId);
    onSelectField(fieldId);
    // 从"待确认"页签点定位时，字段表在"文档预览"里；不切页签用户会觉得按钮没反应。
    onTabChange("document");
    if (!visibleRecords.some((record) => record.field.id === fieldId)) setTraceFilter("all");
  };
  // 深链进来时只应用一次：否则用户之后手动切字段/切筛选会被反复拉回去。
  const initialFocusApplied = useRef(false);
  useEffect(() => {
    if (initialFocusApplied.current || !initialFocusFieldId) return;
    if (!records.some((record) => record.field.id === initialFocusFieldId)) return;
    initialFocusApplied.current = true;
    focusField(initialFocusFieldId);
  }, [initialFocusFieldId, records]);
  useEffect(() => {
    if (focusedFieldId === null) return;
    const row = rowRefs.current[focusedFieldId];
    if (row && typeof row.scrollIntoView === "function") row.scrollIntoView({ block: "center" });
  }, [focusedFieldId, visibleRecords]);
  const recordsByFieldId = useMemo(() => new Map(records.map((record) => [record.field.id, record])), [records]);
  const martFieldsById = useMemo(() => new Map(martFields.map((field) => [field.id, field])), [martFields]);
  const martTablesById = useMemo(() => new Map(martTables.map((table) => [table.id, table])), [martTables]);
  const selected = selectedFieldId ? recordsByFieldId.get(selectedFieldId) || null : null;
  const openQuestions = useMemo(() => questions.filter((item) => (!["resolved", "rejected", "closed"].includes(item.question_status) || !item.resolution_text?.trim())), [questions]);
  const selectedQuestions = useMemo(() => openQuestions.filter((item) => !item.target_field_id || item.target_field_id === selectedFieldId), [openQuestions, selectedFieldId]);
  const versionLabel = requirementScope
    ? `需求 v${requirementScope.version}${contentVersion ? ` · 内容 v${contentVersion}` : ""} · ${statusLabel(contentStatus || "draft")}`
    : "工作草稿";
  const confirmed = contentStatus === "confirmed";

  return (
    <section className="panel min-w-0 overflow-hidden">
      <div className="flex min-h-14 flex-wrap items-center gap-2 border-b border-line bg-slate-50/70 px-4 py-2.5">
        <div className="min-w-0">
          <h2 className="text-[13px] font-semibold text-ink">{confirmed ? "已确认需求文档" : "需求文档草稿预览"}</h2>
          <p className="text-[10px] text-slate-500">{confirmed ? "当前内容已通过三阶段审核，修订将建立新版本" : "AI 草稿必须经人工采用、编辑和现有治理流程确认"}</p>
        </div>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          <button className="badge-info cursor-pointer" onClick={onShowEvidence} type="button">证据 {evidenceForSelected} 条</button>
          {requirementId ? <button className="badge-warning" onClick={()=>onTabChange("questions")}>{requirementGaps ? `待确认 ${requirementGaps.length} 项` : "完整性待评估"}</button> : <Link className="badge-warning" href="/questions">人工问题 {openQuestions.length} 项 · 完整性待评估</Link>}
          <span className="badge-neutral">{versionLabel}</span>
          <button className="button-primary" disabled={!table || exporting} onClick={() => void openPreflight()} type="button"><Download size={15} />{exporting ? "导出中…" : "导出需求文档"}</button>
        </div>
      </div>

      {showPreflight ? (
        <div className="fixed inset-0 z-40 flex items-center justify-center bg-slate-900/40 p-4" role="presentation">
          <div aria-label="导出前预检" aria-modal="true" className="w-full max-w-lg rounded-lg border border-line bg-white p-5 shadow-xl" role="dialog">
            <h3 className="text-sm font-semibold text-ink">导出前预检</h3>
            <p className="mt-1 text-xs text-slate-500">
              {onFreezeAndExport
                ? "只做统计；继续导出会先把当前内容冻结为快照，再按该快照导出——同一内容重复导出得到同一份文件。"
                : "只做统计，不冻结版本、不修改任何内容。"}
            </p>
            {onFreezeAndExport ? (
              <div className="mt-3 rounded border border-line bg-slate-50/70 px-3 py-2 text-xs">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-slate-500">导出格式</span>
                  <select aria-label="导出格式" className="rounded border border-line px-2 py-1" onChange={(event) => setExportFormat(event.target.value as "xlsx" | "docx")} value={exportFormat}>
                    <option value="xlsx">Excel（xlsx）</option>
                    <option value="docx">Word（docx）</option>
                  </select>
                  <span className="text-slate-500">版式</span>
                  <select aria-label="导出版式" className="rounded border border-line px-2 py-1" onChange={(event) => setExportLayout(event.target.value as "survey" | "standard")} value={exportLayout}>
                    <option value="survey">一表通调研表式（仅 xlsx）</option>
                    <option value="standard">平台内置版式</option>
                  </select>
                  <span className="text-slate-500">冻结后导出，快照号可在"生成轮次/快照"里复查</span>
                </div>
                {surveyBlocked ? <p className="mt-1 text-amber-700">一表通调研表式只支持 xlsx；要导出 Word 请选平台内置版式。</p> : null}
              </div>
            ) : null}
            {onFreezeAndExport && snapshotDiffLoader ? (
              <section aria-label="与上次冻结相比" className="mt-3 rounded border border-line bg-white px-3 py-2 text-xs">
                <p className="font-medium text-slate-700">与上次冻结相比</p>
                {snapshotDiffLoading ? (
                  <p className="mt-1 text-slate-500">正在读取最近一次冻结的快照…</p>
                ) : snapshotDiffError ? (
                  <p className="mt-1 text-amber-700">{snapshotDiffError}</p>
                ) : !snapshotDiff ? (
                  <p className="mt-1 text-slate-500">这个需求还没有冻结过快照；本次冻结会是第 1 份。</p>
                ) : snapshotDiff.sameContentHash ? (
                  <p className="mt-1 text-slate-600">
                    与快照 #{snapshotDiff.previousSnapshotId ?? "-"} 内容完全一致（{snapshotDiff.currentFieldCount} 个字段，内容 hash 相同）——本次导出会复用这份快照，不会新建。
                  </p>
                ) : snapshotDiff.identical ? (
                  <p className="mt-1 text-slate-600">
                    字段口径与快照 #{snapshotDiff.previousSnapshotId ?? "-"} 相同（{snapshotDiff.currentFieldCount} 个字段），但快照之后还有其他内容改动（缺口、资料范围或脚本依据），本次导出会新建快照。
                  </p>
                ) : (
                  <>
                    <p className="mt-1 text-slate-600">
                      与快照 #{snapshotDiff.previousSnapshotId ?? "-"} 相比：
                      字段口径变化 {snapshotDiff.changed.length} 个 · 新增字段 {snapshotDiff.added.length} 个 · 删除字段 {snapshotDiff.removed.length} 个（快照 {snapshotDiff.previousFieldCount} → 当前 {snapshotDiff.currentFieldCount}）；本次导出会新建快照。
                    </p>
                    {snapshotDiff.changed.length > 0 ? (
                      <ul className="mt-1 space-y-0.5 text-slate-600">
                        {snapshotDiff.changed.slice(0, 5).map((item) => (
                          <li key={item.fieldCode}>· {item.fieldCode} {item.fieldName}：{item.sections.join("、")}发生变化</li>
                        ))}
                        {snapshotDiff.changed.length > 5 ? <li>· …另有 {snapshotDiff.changed.length - 5} 个字段有变化</li> : null}
                      </ul>
                    ) : null}
                    <p className="mt-1 text-slate-500">差异按字段口径逐项比较（业务定义/业务正文/技术加工/技术正文），不比较格式与空白。</p>
                  </>
                )}
              </section>
            ) : null}
            {exportOutcome ? (
              <div aria-label="导出身份" className="mt-3 rounded border border-pine-200 bg-pine-50 px-3 py-2 text-xs text-pine-900">
                <p className="font-medium">已导出 {exportOutcome.fileName}</p>
                <p>快照 #{exportOutcome.snapshotId}（{exportOutcome.snapshotCreated ? "本次新建" : "内容未变，复用已有快照"}） · 产物 #{exportOutcome.artifactId}</p>
                <p className="break-all">文件 hash {exportOutcome.fileSha256}</p>
                <p className="text-pine-800">凭快照号可重新导出同一份文件；改动内容需要新的快照。</p>
              </div>
            ) : null}
            <dl className="mt-4 grid grid-cols-2 gap-2 text-xs">
              <div className="rounded border border-line px-3 py-2"><dt className="text-slate-500">字段总数</dt><dd className="text-base font-semibold text-ink">{traceStats.total}</dd></div>
              <div className="rounded border border-line px-3 py-2"><dt className="text-slate-500">会带"待业务补充"占位</dt><dd className={`text-base font-semibold ${traceStats.pendingBusiness ? "text-amber-700" : "text-ink"}`}>{traceStats.pendingBusiness}</dd></div>
              <div className="rounded border border-line px-3 py-2"><dt className="text-slate-500">无集市映射（溯源列组留空）</dt><dd className="text-base font-semibold text-ink">{traceStats.unmapped}</dd></div>
              <div className="rounded border border-line px-3 py-2"><dt className="text-slate-500">多来源字段（需业务确认口径）</dt><dd className="text-base font-semibold text-ink">{traceStats.multiMapping}</dd></div>
              <div className="rounded border border-line px-3 py-2"><dt className="text-slate-500">仍打开的字段级缺口</dt><dd className={`text-base font-semibold ${traceStats.withGaps ? "text-amber-700" : "text-ink"}`}>{traceStats.withGaps} 个字段</dd></div>
              <div className="rounded border border-line px-3 py-2"><dt className="text-slate-500">缺口条数（含范围级）</dt><dd className="text-base font-semibold text-ink">{requirementGaps ? requirementGaps.length : 0}</dd></div>
            </dl>
            <ul className="mt-4 space-y-1 text-xs text-slate-600">
              {traceStats.pendingBusiness ? <li>· 有 {traceStats.pendingBusiness} 个字段没有业务口径正文，导出文档会写"待业务补充"——审阅者会看到你没有给出口径，而不是看到空白。</li> : null}
              {traceStats.unmapped ? <li>· 有 {traceStats.unmapped} 个字段没有固定的集市映射，导出的溯源列组会留空。</li> : null}
              {traceStats.multiMapping ? <li>· 有 {traceStats.multiMapping} 个字段来自多个集市字段，导出后需业务确认取数口径，不能默认取第一条。</li> : null}
              {traceStats.withGaps ? <li>· 有 {traceStats.withGaps} 个字段仍带打开状态的缺口，导出不等于关闭缺口，送审仍会被阻断。</li> : null}
            </ul>
            <div className="mt-5 flex justify-end gap-2">
              <button className="button-secondary" onClick={() => setShowPreflight(false)} type="button">返回修改</button>
              {onFreezeAndExport ? (
                <button className="button-primary" disabled={exporting || freezing || surveyBlocked} onClick={() => void runFreezeAndExport()} type="button">{freezing ? "冻结并导出…" : "冻结并导出"}</button>
              ) : (
                <button className="button-primary" disabled={exporting} onClick={() => { setShowPreflight(false); onExport(); }} type="button">{exporting ? "导出中…" : "继续导出"}</button>
              )}
            </div>
          </div>
        </div>
      ) : null}

      {!table ? (
        <div className="m-5 empty-state min-h-[620px]"><FileCheck2 className="text-slate-300" size={38} /><p>请先选择一表通目标表</p></div>
      ) : (
        <div className="bg-[#eef2f5] p-5 2xl:p-7">
          <article className="mx-auto min-h-[760px] max-w-[1180px] border border-slate-200 bg-white px-7 py-7 shadow-[0_8px_24px_rgba(33,47,61,0.08)] 2xl:px-9">
            <div className="mb-4 h-1 w-12 rounded-full bg-pine" />
            <h1 className="text-xl font-semibold tracking-tight text-ink">{requirementScope?.name || `${table.table_code} ${table.table_name} — 业务口径及技术溯源需求`}</h1>
            <p className="mt-1 text-xs text-slate-500">{projectName} · {scenario?.scenario_name || "未选择业务场景"} · AI 辅助需求工作稿</p>

            <div className="mt-5 grid grid-cols-4 overflow-hidden rounded-lg border border-line bg-slate-50/70 text-[10px] text-slate-500">
              <DocMeta label="项目" value={projectName} />
              <DocMeta label="目标表" value={`${table.table_code} ${table.table_name}`} />
              <DocMeta label="字段范围" value={`${records.length} 个字段`} />
              <DocMeta label="状态" value="草稿（待审核交付）" last />
            </div>

            <WorkspaceTabs activeTab={activeTab} onChange={onTabChange} />
            {selected ? <div className={activeTab === "structured" || activeTab === "document" ? "mt-5" : "hidden"}>{requirementId && requirementScope ? <RequirementContentEditor
              key={`${requirementId}:${selected.field.id}`} requirementId={requirementId} scopeVersion={requirementScope.version}
              contentVersion={contentVersion||0} record={selected} onSaved={onEditorSaved} onDirty={onEditorDirtyChange}/>:<SelectedFieldEditor
              detailReady={detailReady}
              key={`${selected.field.id}:${selected.business?.id || 0}:${selected.lineage?.id || 0}`}
              onAdoptBusiness={onAdoptBusiness}
              onAdoptTechnical={onAdoptTechnical}
              onDirtyChange={onEditorDirtyChange}
              onError={onEditorError}
              onNotice={onEditorNotice}
              onSaved={onEditorSaved}
              record={selected}
            />}</div> : null}
            {!requirementId && selected && detailReady && <section aria-label="当前跨层映射入口" className="mt-3 flex flex-wrap gap-3 text-xs">
              {editorDirty ? <p>先保存当前字段的人工编辑，再打开跨层映射。</p> : <>
              {selected.martMappings.map(mapping => <Link key={`mart:${mapping.id}`} className="text-teal-800 underline"
                href={`/mapping-drafts/mart_to_ybt/${mapping.id}`}>核验集市到一表通映射 #{mapping.id}</Link>)}
              {Array.from(new Set(selected.martMappings.flatMap(mapping => mapping.mart_field_id ? (sourceMappings[mapping.mart_field_id] || []).map(row => row.id) : []))).map(id =>
                <Link key={`source:${id}`} className="text-teal-800 underline" href={`/mapping-drafts/source_to_mart/${id}`}>核验源到集市映射 #{id}</Link>)}</>}
            </section>}
            {activeTab === "document" ? <>
            <SectionTitle number="1" title="需求背景与范围" />
            <p className="whitespace-pre-wrap text-xs leading-6 text-slate-600">{requirementId ? requirementBackground || "业务背景待补充" : table.description || "整体背景待补充；字段定义不替代需求背景。"}</p>
            {requirementScope ? <dl className="mt-3 space-y-2 text-xs">{([
              ["业务目标",requirementScope.objective], ["口径生效日期",requirementScope.effective_date],
              ["纳入范围",requirementScope.inclusion], ["排除条件",requirementScope.exclusion]
            ] as const).map(([label,value])=><div key={label}><dt className="font-semibold">{label}</dt><dd className="whitespace-pre-wrap text-slate-600">{value||"待确认"}</dd></div>)}
              <div><dt className="font-semibold">资料与数据范围</dt><dd>{requirementResources?.length ? requirementResources.map((item,index)=><p key={index}>{resourceKindLabel(item.kind)}：{item.name} {item.code!==item.name?item.code:""} · {item.status==="selected"?"已选，待核验":"不可用，待重新选择"}</p>) : "未指定，不代表允许使用全部资料"}</dd></div>
            </dl> : null}

            <SectionTitle number="2" title="字段级业务口径与技术溯源" />
            <div className="mb-2 flex flex-wrap items-center gap-2 text-[10px]">
              <span className="text-slate-500">覆盖度</span>
              {TRACE_FILTERS.map((filter) => {
                const count = traceFilterCount(traceStats, filter.key);
                const active = traceFilter === filter.key;
                return (
                  <button
                    key={filter.key}
                    type="button"
                    aria-pressed={active}
                    className={`rounded-full border px-2 py-0.5 ${active ? "border-pine-400 bg-pine-50 text-pine-700" : "border-line text-slate-600 hover:bg-slate-50"}`}
                    onClick={() => setTraceFilter(filter.key)}
                  >
                    {filter.label} {count}
                  </button>
                );
              })}
              <span className="text-slate-400">当前显示 {visibleRecords.length} / {traceStats.total} 个字段（与导出文档的完整度统计同口径）</span>
              {traceFilter !== "all" && traceStats.total ? <span className="text-slate-400">· 该条件下各字段都处理掉后这一项才归零（当前还剩 {traceFilterCount(traceStats, traceFilter)} 个）</span> : null}
            </div>
            <div className="overflow-x-auto border border-line">
              <table className="w-full min-w-[900px] table-fixed border-collapse text-[10px]">
                <colgroup><col className="w-[12%]" /><col className="w-[20%]" /><col className="w-[11%]" /><col className="w-[15%]" /><col className="w-[14%]" /><col className="w-[19%]" /><col className="w-[9%]" /></colgroup>
                <thead><tr className="bg-slate-50 text-left text-slate-600"><Th>目标字段</Th><Th>业务口径</Th><Th>源系统</Th><Th>源表 / 字段</Th><Th>加工路径 / 集市字段</Th><Th>加工与取数规则</Th><Th>状态</Th></tr></thead>
                <tbody>
                  {visibleRecords.map((record) => {
                    const martMapping = record.martMappings[0] || null;
                    const martField = martMapping?.mart_field_id ? martFieldsById.get(martMapping.mart_field_id) || null : null;
                    const martTable = martField ? martTablesById.get(martField.mart_table_id) || null : null;
                    const sourceMapping = martField ? sourceMappings[martField.id]?.[0] || null : null;
                    const mappingStatus = combinedFieldStatus({
                      businessStatus: record.business?.business_confirm_status,
                      technicalStatus: record.lineage?.tech_confirm_status,
                      pathConfirmed: record.pathConfirmed,
                      martStatuses: record.martMappings.map((mapping) => mapping.mapping_status)
                    });
                    const sourcesApproved = record.pathConfirmed || (record.martMappings.length > 0 && record.martMappings.every(mapping=>{
                      const sources=mapping.mart_field_id?sourceMappings[mapping.mart_field_id]||[]:[];
                      return sources.length>0 && sources.every(source=>["approved","confirmed"].includes(source.mapping_status));
                    }));
                    const hasScopeGap=Boolean(requirementId && (!requirementGaps || requirementGaps.some(gap=>gap.field_id===null||gap.field_id===record.field.id)));
                    const combinedStatus=mappingStatus==="approved"&&(!sourcesApproved||hasScopeGap)?"draft":mappingStatus;
                    const tone = mappingStatusTone(combinedStatus);
                    const status = mappingStatusLabel(combinedStatus);
                    const selectedRow = record.field.id === selectedFieldId;
                    return (
                      <tr ref={(element) => { rowRefs.current[record.field.id] = element; }} className={`cursor-pointer align-top transition ${selectedRow ? "bg-pine-50/70" : "hover:bg-slate-50/70"} ${focusedFieldId === record.field.id ? "ring-2 ring-pine-400 ring-inset" : ""}`} data-focused={focusedFieldId === record.field.id ? "true" : undefined} key={record.field.id} onClick={() => { setFocusedFieldId(record.field.id); onSelectField(record.field.id); }}>
                        <Td><strong className="block text-ink">{record.field.field_name}</strong><span className="mt-1 block font-mono text-[9px] text-slate-400">{record.field.field_code}</span></Td>
                        <Td>{preferredMappingContent(record.business, record.field.regulatory_refined_definition || record.field.regulatory_description || "待维护")}</Td>
                        <Td>{record.lineage?.source_system_name || sourceMapping?.source_system_summary || "待确认"}</Td>
                        <Td>{sourcePath(record)}</Td>
                        <Td>{record.confirmedPath ? <><p>{record.pathConfirmed?"已确认路径":"路径待重新确认"}</p><p className="break-all">{record.confirmedPath.nodes.map(node=>[node.table_name,node.column_name].filter(Boolean).join(".")).join("；")}</p></> : martField ? `${martTable?.table_code || martTable?.table_name || "集市表"}.${martField.field_code}` : martMapping?.mart_field_summary || "待确认"}</Td>
                        <Td><RuleLayers source={sourceMapping?.final_content || sourceMapping?.business_rule} target={martMapping?.final_content || martMapping?.business_rule || record.lineage?.processing_logic} /><button className="mt-1 text-[9px] font-medium text-sky-700 hover:underline" onClick={(event) => { event.stopPropagation(); onSelectField(record.field.id); onShowEvidence(); }} type="button">查看 {evidenceCountByField[record.field.id] || 0} 条证据</button></Td>
                        <Td><StatusBadge tone={tone} value={status} /></Td>
                      </tr>
                    );
                  })}
                  {!visibleRecords.length ? <tr><td className="px-4 py-10 text-center text-xs text-slate-500" colSpan={7}>{records.length ? `当前筛选没有字段（共 ${records.length} 个）。换一个覆盖度条件，或选择“全部字段”。` : "当前目标表没有可展示字段"}</td></tr> : null}
                </tbody>
              </table>
            </div>

            {selected ? (
              <>
                <SectionTitle number="3" title="当前字段技术溯源" />
                <p className="text-xs">已登记来源：{sourcePath(selected)}</p>
                <button className="button-secondary mt-2" onClick={()=>onTabChange("lineage")}>查看表字段关系与加工依据</button>
              </>
            ) : null}

            <SectionTitle number={selected ? "4" : "3"} title="待业务 / 技术确认问题" />
            {requirementId ? <RequirementGapList gaps={requirementGaps} records={records} onFocusField={focusField} /> : selectedQuestions.length ? (
              <ul className="space-y-2">
                {selectedQuestions.map((question) => (
                  <li className="border-l-2 border-gold-300 bg-gold-50 px-3 py-2 text-[10px] leading-5 text-slate-700" key={question.id}>
                    <strong className="text-gold-800">{priorityLabel(question.priority)} · {questionTypeLabel(question.question_type)}：</strong>{question.question_text}
                    <span className="ml-2 text-slate-400">{statusLabel(question.question_status)}</span>
                  </li>
                ))}
              </ul>
            ) : <p className="text-xs text-slate-500">未登记人工问题；这不代表定义、来源、加工规则和证据已完整。</p>}

            <footer className="mt-7 flex justify-between border-t border-line pt-3 text-[9px] text-slate-400">
              <span>来源：监管目标字段 + 场景口径 + 双层 Mapping + 已绑定证据</span>
              <span>AI 草稿不等于人工最终监管口径</span>
            </footer>
            </> : null}
            {activeTab === "structured" ? <StructuredCaliber onSelectField={onSelectField} records={records} selected={selected} /> : null}
            {activeTab === "structured" && selected ? <AiExplanationPanel evidenceCount={evidenceForSelected} martFieldsById={martFieldsById} martTablesById={martTablesById} record={selected} sourceMappings={sourceMappings} /> : null}
            {activeTab === "lineage" ? <RequirementLineagePanel tableId={table.id} fieldId={selectedFieldId} requirementId={requirementId} scenarioId={scenario?.id} onSelectField={onSelectField} contentVersion={contentVersion} /> : null}
            {activeTab === "evidence" ? <EvidencePanel evidenceCountByField={evidenceCountByField} onSelectField={onSelectField} onShowEvidence={onShowEvidence} records={records} selectedFieldId={selectedFieldId} /> : null}
            {activeTab === "questions" ? requirementId ? <RequirementGapList gaps={requirementGaps} records={records} onFocusField={focusField} /> : <QuestionsPanel questions={selectedQuestions} /> : null}
          </article>
        </div>
      )}
    </section>
  );
}

function RequirementGapList({gaps, records, onFocusField}: {gaps?:RequirementGap[]; records:FieldWorkspaceRecord[]; onFocusField:(id:number)=>void}) {
  if(!gaps)return <p role="status" className="my-3 text-xs">缺口尚未完成评估或读取，请刷新后核验。</p>;
  if(!gaps.length)return <p className="my-3 text-xs">本次完整性检查未发现缺口，仍需完成审核确认。</p>;
  const fieldById = new Map(records.map((record) => [record.field.id, record]));
  const groups = new Map<number | null, RequirementGap[]>();
  for (const gap of gaps) {
    const key = gap.field_id ?? null;
    const bucket = groups.get(key);
    if (bucket) bucket.push(gap); else groups.set(key, [gap]);
  }
  const ordered = Array.from(groups.entries()).sort((a, b) => (b[1].length - a[1].length));
  return (
    <div aria-label="当前需求全部缺口" className="my-3 space-y-2">
      <p className="text-xs text-slate-500">
        共 {gaps.length} 项缺口，按字段归并为 {ordered.length} 组（{ordered.filter(([id]) => id !== null).length} 个字段 + {ordered.filter(([id]) => id === null).length} 组范围级）。
        条数会远多于字段数：同一字段的重复问题不重复定位。
      </p>
      {ordered.map(([fieldId, bucket]) => {
        const field = fieldId !== null ? fieldById.get(fieldId) : undefined;
        return (
          <details className="rounded border border-gold-200 bg-gold-50 p-3 text-xs" key={String(fieldId)} open={bucket.length <= 2}>
            <summary className="flex cursor-pointer items-center gap-2 font-semibold">
              <span>
                {field ? `${field.field.field_name || field.field.field_code}` : "需求范围"} · {bucket.length} 项
                {field && bucket.some((gap: RequirementGap) => gap.origin === "manual") ? " · 含人工问题" : ""}
              </span>
              {fieldId !== null ? (
                <button
                  className="ml-auto rounded border border-gold-300 bg-white px-2 py-0.5 text-[11px] hover:bg-gold-100"
                  onClick={(event) => { event.preventDefault(); event.stopPropagation(); onFocusField(fieldId); }}
                  type="button"
                >
                  定位该字段
                </button>
              ) : (
                <span className="ml-auto text-[11px] font-normal text-slate-500">范围级，不对应单个字段</span>
              )}
            </summary>
            <ul className="mt-2 space-y-1.5">
              {bucket.slice(0, 5).map((gap: RequirementGap) => (
                <li key={gap.id} className="whitespace-pre-wrap">{describeUserMessage(gap.message, "该问题说明待补充，请人工核验。")}</li>
              ))}
              {bucket.length > 5 ? <li className="text-slate-500">…另有 {bucket.length - 5} 项同类缺口（同一字段）。</li> : null}
            </ul>
            {fieldId === null ? <p className="mt-2 text-slate-500">范围级缺口请在需求范围里处理，不对应单个字段。</p> : null}
          </details>
        );
      })}
    </div>
  );
}

function WorkspaceTabs({ activeTab, onChange }: { activeTab: WorkspaceTab; onChange: (tab: WorkspaceTab) => void }) {
  return <div aria-label="需求工作台视图" className="mt-5 flex gap-1 overflow-x-auto border-b border-line" role="tablist">
    {WORKSPACE_TABS.map((tab) => <button aria-selected={tab.id === activeTab} className={`min-h-10 shrink-0 border-b-2 px-3 text-xs font-semibold ${tab.id === activeTab ? "border-pine-600 text-pine-700" : "border-transparent text-slate-500 hover:text-ink"}`} key={tab.id} onClick={() => onChange(tab.id)} role="tab" type="button">{tab.label}</button>)}
  </div>;
}

function StructuredCaliber({ records, selected, onSelectField }: {
  records: FieldWorkspaceRecord[]; selected: FieldWorkspaceRecord | null; onSelectField: (id: number) => void;
}) {
  return <div className="mt-5 space-y-4"><div className="rounded-lg border border-pine-100 bg-pine-50/50 px-4 py-3 text-xs text-pine-900">结构化口径是当前事实视图：监管字段、业务定义、技术溯源、双层 Mapping 和治理状态均来自服务器真实记录；文档预览不会反向修改这些事实。</div>
    <div className="grid gap-3 md:grid-cols-2">{records.map((record) => <button className={`rounded-lg border p-3 text-left ${record.field.id === selected?.field.id ? "border-pine-400 bg-pine-50" : "border-line bg-white"}`} key={record.field.id} onClick={() => onSelectField(record.field.id)} type="button"><strong className="block text-xs text-ink">{record.field.field_name}</strong><span className="mt-1 block font-mono text-[10px] text-slate-400">{record.field.field_code}</span><span className="mt-2 block text-[11px] text-slate-600">业务：{record.business?.final_content || record.business?.ai_generated_content || "待维护"}</span><span className="mt-1 block text-[11px] text-slate-600">血缘：{record.lineage?.source_system_name || "待确认"} · {record.lineage?.lineage_status ? lineageStatusLabel(record.lineage.lineage_status) : "未关联"}</span></button>)}</div>
    {!selected ? <p className="text-xs text-slate-500">请选择字段查看完整口径。</p> : null}
  </div>;
}


function EvidencePanel({ records, selectedFieldId, evidenceCountByField, onSelectField, onShowEvidence }: { records: FieldWorkspaceRecord[]; selectedFieldId: number | null; evidenceCountByField: Record<number, number>; onSelectField: (id: number) => void; onShowEvidence: () => void }) {
  return <div className="mt-5 space-y-2"><p className="text-xs text-slate-500">按字段查看证据出处与原文。</p>{records.map((record) => <div className="flex items-center justify-between rounded-lg border border-line bg-white px-3 py-2" key={record.field.id}><span className="text-xs text-ink">{record.field.field_name}</span><button className="button-secondary h-8 text-xs" onClick={() => { onSelectField(record.field.id); onShowEvidence(); }} type="button">查看 {evidenceCountByField[record.field.id] || 0} 条证据</button></div>)}</div>;
}

function QuestionsPanel({ questions }: { questions: PendingQuestion[] }) {
  return <div className="mt-5">{questions.length ? <ul className="space-y-2">{questions.map((question) => <li className="rounded-lg border border-gold-200 bg-gold-50 px-3 py-2 text-xs text-slate-700" key={question.id}><strong>{priorityLabel(question.priority)} · {questionTypeLabel(question.question_type)}</strong><span className="ml-2">{question.question_text}</span><span className="ml-2 text-slate-400">{statusLabel(question.question_status)}</span></li>)}</ul> : <div className="empty-state min-h-[180px]"><p>未登记人工问题；事实完整性仍需评估</p></div>}</div>;
}

function DocMeta({ label, value, last = false }: { label: string; value: string; last?: boolean }) {
  return <div className={`min-w-0 px-3 py-2 ${last ? "" : "border-r border-line"}`}><span>{label}</span><strong className="mt-0.5 block truncate text-[11px] text-ink">{value}</strong></div>;
}

function SectionTitle({ number, title }: { number: string; title: string }) {
  return <h2 className="mb-2 mt-5 flex items-center gap-2 text-xs font-bold text-ink"><span className="flex h-5 w-5 items-center justify-center rounded bg-pine-100 text-[9px] text-pine-700">{number}</span>{title}</h2>;
}

function Th({ children }: { children: React.ReactNode }) { return <th className="border-b border-r border-line px-2 py-2 font-semibold last:border-r-0">{children}</th>; }
function Td({ children }: { children: React.ReactNode }) { return <td className="border-b border-r border-line px-2 py-2 leading-[1.55] text-slate-600 last:border-r-0">{children}</td>; }

function sourcePath(record: FieldWorkspaceRecord) {
  const lineage = record.lineage;
  if (!lineage) return "待确认";
  return [lineage.source_schema_name, lineage.source_table_english_name, lineage.source_field_english_name].filter(Boolean).join(".") || lineage.source_table_chinese_name || "待确认";
}

function RuleLayers({ source, target }: { source?: string | null; target?: string | null }) {
  return (
    <div className="space-y-1">
      <p><span className="font-semibold text-pine-700">来源表→数据集市：</span>{source || "待维护"}</p>
      <p><span className="font-semibold text-sky-700">数据集市→报送目标：</span>{target || "待维护"}</p>
    </div>
  );
}

function StatusBadge({ tone, value }: { tone: string; value: string }) {
  const className = tone === "success" ? "badge-success" : tone === "danger" ? "badge-danger" : tone === "warning" ? "badge-warning" : tone === "info" ? "badge-info" : "badge-neutral";
  return <span className={`${className} whitespace-normal text-center text-[9px]`}>{value}</span>;
}

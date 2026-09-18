"use client";

import { Download, FileCheck2 } from "lucide-react";
import Link from "next/link";
import { useMemo } from "react";

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
import { questionTypeLabel, statusLabel } from "@/lib/product-language";
import type { FieldWorkspaceRecord, SourceMappingIndex } from "@/components/requirement-workspace/types";
import type { RequirementScope } from "./RequirementScopePanel";
import { RequirementContentEditor } from "./RequirementContentEditor";

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
  onAdoptBusiness,
  onAdoptTechnical,
  onEditorDirtyChange,
  onEditorError,
  onEditorNotice,
  onEditorSaved,
  onShowEvidence,
  onExport,
  exporting
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
  onAdoptBusiness: () => void;
  onAdoptTechnical: () => void;
  onEditorDirtyChange: (dirty: boolean) => void;
  onEditorError: (message: string) => void;
  onEditorNotice: (message: string) => void;
  onEditorSaved: () => void;
  onShowEvidence: () => void;
  onExport: () => void;
  exporting: boolean;
}) {
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
          <button className="button-primary" disabled={!table || exporting} onClick={onExport} type="button"><Download size={15} />{exporting ? "导出中…" : "导出需求文档"}</button>
        </div>
      </div>

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
            {activeTab === "document" ? <>
            <SectionTitle number="1" title="需求背景与范围" />
            <p className="whitespace-pre-wrap text-xs leading-6 text-slate-600">{requirementId ? requirementBackground || "业务背景待补充" : table.description || "整体背景待补充；字段定义不替代需求背景。"}</p>
            {requirementScope ? <dl className="mt-3 space-y-2 text-xs">{([
              ["业务目标",requirementScope.objective], ["口径生效日期",requirementScope.effective_date],
              ["纳入范围",requirementScope.inclusion], ["排除条件",requirementScope.exclusion]
            ] as const).map(([label,value])=><div key={label}><dt className="font-semibold">{label}</dt><dd className="whitespace-pre-wrap text-slate-600">{value||"待确认"}</dd></div>)}
              <div><dt className="font-semibold">资料与数据范围</dt><dd>{requirementResources?.length ? requirementResources.map((item,index)=><p key={index}>{item.kind}：{item.name} {item.code!==item.name?item.code:""} · {item.status==="selected"?"已选，待核验":"不可用，待重新选择"}</p>) : "未指定，不代表允许使用全部资料"}</dd></div>
            </dl> : null}

            <SectionTitle number="2" title="字段级业务口径与技术溯源" />
            <div className="overflow-x-auto border border-line">
              <table className="w-full min-w-[900px] table-fixed border-collapse text-[10px]">
                <colgroup><col className="w-[12%]" /><col className="w-[20%]" /><col className="w-[11%]" /><col className="w-[15%]" /><col className="w-[14%]" /><col className="w-[19%]" /><col className="w-[9%]" /></colgroup>
                <thead><tr className="bg-slate-50 text-left text-slate-600"><Th>目标字段</Th><Th>业务口径</Th><Th>源系统</Th><Th>源表 / 字段</Th><Th>加工路径 / 集市字段</Th><Th>加工与取数规则</Th><Th>状态</Th></tr></thead>
                <tbody>
                  {records.map((record) => {
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
                      <tr className={`cursor-pointer align-top transition ${selectedRow ? "bg-pine-50/70" : "hover:bg-slate-50/70"}`} key={record.field.id} onClick={() => onSelectField(record.field.id)}>
                        <Td><strong className="block text-ink">{record.field.field_name}</strong><span className="mt-1 block font-mono text-[9px] text-slate-400">{record.field.field_code}</span></Td>
                        <Td>{preferredMappingContent(record.business, record.field.regulatory_refined_definition || record.field.regulatory_description || "待维护")}</Td>
                        <Td>{record.lineage?.source_system_name || sourceMapping?.source_system_summary || "待确认"}</Td>
                        <Td>{sourcePath(record)}</Td>
                        <Td>{record.confirmedPath ? <><p>{record.pathConfirmed?"已确认路径":"路径待重新确认"}</p><p className="break-all">{record.confirmedPath.nodes.map(node=>[node.table_name,node.column_name].filter(Boolean).join(".")).join("；")}</p></> : martField ? `${martTable?.table_code || martTable?.table_name || "MART"}.${martField.field_code}` : martMapping?.mart_field_summary || "待确认"}</Td>
                        <Td><RuleLayers source={sourceMapping?.final_content || sourceMapping?.business_rule} target={martMapping?.final_content || martMapping?.business_rule || record.lineage?.processing_logic} /><button className="mt-1 text-[9px] font-medium text-sky-700 hover:underline" onClick={(event) => { event.stopPropagation(); onSelectField(record.field.id); onShowEvidence(); }} type="button">查看 {evidenceCountByField[record.field.id] || 0} 条证据</button></Td>
                        <Td><StatusBadge tone={tone} value={status} /></Td>
                      </tr>
                    );
                  })}
                  {!records.length ? <tr><td className="px-4 py-10 text-center text-xs text-slate-500" colSpan={7}>当前目标表没有可展示字段</td></tr> : null}
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
            {requirementId ? <RequirementGapList gaps={requirementGaps} records={records} onSelectField={onSelectField} /> : selectedQuestions.length ? (
              <ul className="space-y-2">
                {selectedQuestions.map((question) => (
                  <li className="border-l-2 border-gold-300 bg-gold-50 px-3 py-2 text-[10px] leading-5 text-slate-700" key={question.id}>
                    <strong className="text-gold-800">{question.priority.toUpperCase()} · {questionTypeLabel(question.question_type)}：</strong>{question.question_text}
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
            {activeTab === "questions" ? requirementId ? <RequirementGapList gaps={requirementGaps} records={records} onSelectField={onSelectField} /> : <QuestionsPanel questions={selectedQuestions} /> : null}
          </article>
        </div>
      )}
    </section>
  );
}

function RequirementGapList({gaps, records, onSelectField}: {gaps?:RequirementGap[]; records:FieldWorkspaceRecord[]; onSelectField:(id:number)=>void}) {
  if(!gaps)return <p role="status" className="my-3 text-xs">缺口尚未完成评估或读取，请刷新后核验。</p>;
  if(!gaps.length)return <p className="my-3 text-xs">本次完整性检查未发现缺口，仍需完成审核确认。</p>;
  return <ul aria-label="当前需求全部缺口" className="my-3 space-y-2">{gaps.map(gap=>{
    const field=records.find(item=>item.field.id===gap.field_id)?.field;
    return <li key={gap.id} className="rounded border border-gold-200 bg-gold-50 p-3 text-xs"><strong>{gap.origin==="manual"?"人工问题":"分析发现"} · {field?.field_name||"需求范围"}</strong><p className="my-1 whitespace-pre-wrap">{gap.message}</p>{field?<button className="underline" onClick={()=>onSelectField(field.id)}>定位字段</button>:null}<span className="ml-2">待核验闭环</span></li>;
  })}</ul>;
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
    <div className="grid gap-3 md:grid-cols-2">{records.map((record) => <button className={`rounded-lg border p-3 text-left ${record.field.id === selected?.field.id ? "border-pine-400 bg-pine-50" : "border-line bg-white"}`} key={record.field.id} onClick={() => onSelectField(record.field.id)} type="button"><strong className="block text-xs text-ink">{record.field.field_name}</strong><span className="mt-1 block font-mono text-[10px] text-slate-400">{record.field.field_code}</span><span className="mt-2 block text-[11px] text-slate-600">业务：{record.business?.final_content || record.business?.ai_generated_content || "待维护"}</span><span className="mt-1 block text-[11px] text-slate-600">血缘：{record.lineage?.source_system_name || "待确认"} · {record.lineage?.lineage_status || "未关联"}</span></button>)}</div>
    {!selected ? <p className="text-xs text-slate-500">请选择字段查看完整口径。</p> : null}
  </div>;
}


function EvidencePanel({ records, selectedFieldId, evidenceCountByField, onSelectField, onShowEvidence }: { records: FieldWorkspaceRecord[]; selectedFieldId: number | null; evidenceCountByField: Record<number, number>; onSelectField: (id: number) => void; onShowEvidence: () => void }) {
  return <div className="mt-5 space-y-2"><p className="text-xs text-slate-500">按字段查看证据出处与原文。</p>{records.map((record) => <div className="flex items-center justify-between rounded-lg border border-line bg-white px-3 py-2" key={record.field.id}><span className="text-xs text-ink">{record.field.field_name}</span><button className="button-secondary h-8 text-xs" onClick={() => { onSelectField(record.field.id); onShowEvidence(); }} type="button">查看 {evidenceCountByField[record.field.id] || 0} 条证据</button></div>)}</div>;
}

function QuestionsPanel({ questions }: { questions: PendingQuestion[] }) {
  return <div className="mt-5">{questions.length ? <ul className="space-y-2">{questions.map((question) => <li className="rounded-lg border border-gold-200 bg-gold-50 px-3 py-2 text-xs text-slate-700" key={question.id}><strong>{question.priority.toUpperCase()} · {questionTypeLabel(question.question_type)}</strong><span className="ml-2">{question.question_text}</span><span className="ml-2 text-slate-400">{statusLabel(question.question_status)}</span></li>)}</ul> : <div className="empty-state min-h-[180px]"><p>未登记人工问题；事实完整性仍需评估</p></div>}</div>;
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
      <p><span className="font-semibold text-pine-700">Source→Mart：</span>{source || "待维护"}</p>
      <p><span className="font-semibold text-sky-700">Mart→YBT：</span>{target || "待维护"}</p>
    </div>
  );
}

function StatusBadge({ tone, value }: { tone: string; value: string }) {
  const className = tone === "success" ? "badge-success" : tone === "danger" ? "badge-danger" : tone === "warning" ? "badge-warning" : tone === "info" ? "badge-info" : "badge-neutral";
  return <span className={`${className} whitespace-normal text-center text-[9px]`}>{value}</span>;
}

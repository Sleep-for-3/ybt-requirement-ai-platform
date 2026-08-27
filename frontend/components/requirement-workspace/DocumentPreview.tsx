"use client";

import { ArrowDown, Check, Download, FileCheck2, Save, ShieldAlert } from "lucide-react";
import Link from "next/link";

import type {
  MartField,
  MartTable,
  PendingQuestion,
  ProductScenario,
  TargetTable
} from "@/lib/api";
import { buildLineageLabels, combinedFieldStatus, mappingStatusLabel, mappingStatusTone, preferredMappingContent } from "@/lib/workspace-view-model.mjs";
import type { FieldWorkspaceRecord, SaveState, SourceMappingIndex } from "@/components/requirement-workspace/types";

type WorkspaceTab = "structured" | "lineage" | "evidence" | "questions" | "document";

const WORKSPACE_TABS: Array<{ id: WorkspaceTab; label: string }> = [
  { id: "structured", label: "结构化口径" },
  { id: "lineage", label: "血缘" },
  { id: "evidence", label: "证据" },
  { id: "questions", label: "待确认" },
  { id: "document", label: "文档预览" }
];

export function DocumentPreview({
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
  deliverable,
  businessFinal,
  technicalFinal,
  onBusinessFinalChange,
  onTechnicalFinalChange,
  businessLocked,
  technicalLocked,
  saveState,
  onSave,
  onAdoptBusiness,
  onAdoptTechnical,
  onShowEvidence,
  onExport,
  exporting
}: {
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
  deliverable: {id:number;target_table_id:number;status:string;version_no:number} | null;
  businessFinal: string;
  technicalFinal: string;
  onBusinessFinalChange: (value: string) => void;
  onTechnicalFinalChange: (value: string) => void;
  businessLocked: boolean;
  technicalLocked: boolean;
  saveState: SaveState;
  onSave: () => void;
  onAdoptBusiness: () => void;
  onAdoptTechnical: () => void;
  onShowEvidence: () => void;
  onExport: () => void;
  exporting: boolean;
}) {
  const selected = records.find((record) => record.field.id === selectedFieldId) || null;
  const openQuestions = questions.filter((item) => !["accepted", "rejected", "closed"].includes(item.question_status));
  const selectedQuestions = openQuestions.filter((item) => !item.target_field_id || item.target_field_id === selectedFieldId);
  const versionLabel = deliverable ? `正式交付 v${deliverable.version_no}` : "工作草稿";

  return (
    <section className="panel min-w-0 overflow-hidden">
      <div className="flex min-h-14 flex-wrap items-center gap-2 border-b border-line bg-slate-50/70 px-4 py-2.5">
        <div className="min-w-0">
          <h2 className="text-[13px] font-semibold text-ink">需求文档草稿预览</h2>
          <p className="text-[10px] text-slate-500">AI 草稿必须经人工采用、编辑和现有治理流程确认</p>
        </div>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          <button className="badge-info cursor-pointer" onClick={onShowEvidence} type="button">证据 {evidenceForSelected} 条</button>
          <Link className="badge-warning" href="/questions">待确认 {openQuestions.length} 项</Link>
          <span className={deliverable?.status === "approved" ? "badge-success" : "badge-neutral"}>{versionLabel}</span>
          <Link className="button-secondary" href="/deliverables"><FileCheck2 size={15} />正式交付</Link>
          <button className="button-primary" disabled={!table || exporting} onClick={onExport} type="button"><Download size={15} />{exporting ? "导出中…" : "导出需求文档"}</button>
        </div>
      </div>

      {!table ? (
        <div className="m-5 empty-state min-h-[620px]"><FileCheck2 className="text-slate-300" size={38} /><p>请先选择一表通目标表</p></div>
      ) : (
        <div className="bg-[#eef2f5] p-5 2xl:p-7">
          <article className="mx-auto min-h-[760px] max-w-[1180px] border border-slate-200 bg-white px-7 py-7 shadow-[0_8px_24px_rgba(33,47,61,0.08)] 2xl:px-9">
            <div className="mb-4 h-1 w-12 rounded-full bg-pine" />
            <h1 className="text-xl font-semibold tracking-tight text-ink">{table.table_code} {table.table_name} — 业务口径及技术溯源需求</h1>
            <p className="mt-1 text-xs text-slate-500">{projectName} · {scenario?.scenario_name || "未选择业务场景"} · AI 辅助需求工作稿</p>

            <div className="mt-5 grid grid-cols-4 overflow-hidden rounded-lg border border-line bg-slate-50/70 text-[10px] text-slate-500">
              <DocMeta label="项目" value={projectName} />
              <DocMeta label="目标表" value={`${table.table_code} ${table.table_name}`} />
              <DocMeta label="字段范围" value={`${records.length} 个真实字段`} />
              <DocMeta label="状态" value={deliverable ? mappingStatusLabel(deliverable.status) : "工作草稿"} last />
            </div>

            <WorkspaceTabs activeTab={activeTab} onChange={onTabChange} />
            {activeTab === "document" ? <>
            <SectionTitle number="1" title="需求背景与范围" />
            <p className="text-xs leading-6 text-slate-600">{table.description || selected?.field.regulatory_refined_definition || selected?.field.regulatory_description || "当前目标表尚未维护整体说明，字段级监管定义与人工口径见下表。"}</p>

            <SectionTitle number="2" title="字段级业务口径与技术溯源" />
            <div className="overflow-x-auto border border-line">
              <table className="w-full min-w-[900px] table-fixed border-collapse text-[10px]">
                <colgroup><col className="w-[12%]" /><col className="w-[20%]" /><col className="w-[11%]" /><col className="w-[15%]" /><col className="w-[14%]" /><col className="w-[19%]" /><col className="w-[9%]" /></colgroup>
                <thead><tr className="bg-slate-50 text-left text-slate-600"><Th>目标字段</Th><Th>业务口径</Th><Th>源系统</Th><Th>源表 / 字段</Th><Th>集市字段</Th><Th>双层加工与取数规则</Th><Th>状态</Th></tr></thead>
                <tbody>
                  {records.map((record) => {
                    const martMapping = record.martMappings[0] || null;
                    const martField = martFields.find((item) => item.id === martMapping?.mart_field_id) || null;
                    const martTable = martTables.find((item) => item.id === martField?.mart_table_id) || null;
                    const sourceMapping = martField ? sourceMappings[martField.id]?.[0] || null : null;
                    const combinedStatus = combinedFieldStatus({
                      businessStatus: record.business?.business_confirm_status,
                      technicalStatus: record.lineage?.tech_confirm_status,
                      martStatuses: record.martMappings.map((mapping) => mapping.mapping_status)
                    });
                    const tone = mappingStatusTone(combinedStatus);
                    const status = mappingStatusLabel(combinedStatus);
                    const selectedRow = record.field.id === selectedFieldId;
                    return (
                      <tr className={`cursor-pointer align-top transition ${selectedRow ? "bg-pine-50/70" : "hover:bg-slate-50/70"}`} key={record.field.id} onClick={() => onSelectField(record.field.id)}>
                        <Td><strong className="block text-ink">{record.field.field_name}</strong><span className="mt-1 block font-mono text-[9px] text-slate-400">{record.field.field_code}</span></Td>
                        <Td>{preferredMappingContent(record.business, record.field.regulatory_refined_definition || record.field.regulatory_description || "待维护")}</Td>
                        <Td>{record.lineage?.source_system_name || sourceMapping?.source_system_summary || "待确认"}</Td>
                        <Td>{sourcePath(record)}</Td>
                        <Td>{martField ? `${martTable?.table_code || martTable?.table_name || "MART"}.${martField.field_code}` : martMapping?.mart_field_summary || "待确认"}</Td>
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
                <SectionTitle number="3" title="当前字段双层技术溯源" />
                <LineageFlow record={selected} martFields={martFields} martTables={martTables} sourceMappings={sourceMappings} />

                <SectionTitle number="4" title="AI 草稿与人工最终口径" />
                <div className="grid gap-3 lg:grid-cols-2">
                  <MappingEditor
                    aiDraft={selected.business?.ai_generated_content || ""}
                    finalContent={businessFinal}
                    label="业务口径"
                    locked={businessLocked}
                    onAdopt={onAdoptBusiness}
                    onChange={onBusinessFinalChange}
                    status={selected.business?.business_confirm_status || "未维护"}
                  />
                  <MappingEditor
                    aiDraft={selected.lineage?.ai_generated_content || ""}
                    finalContent={technicalFinal}
                    label="技术溯源"
                    locked={technicalLocked}
                    onAdopt={onAdoptTechnical}
                    onChange={onTechnicalFinalChange}
                    status={selected.lineage?.tech_confirm_status || "未维护"}
                  />
                </div>
                <div className="mt-3 flex items-center justify-between rounded-lg border border-line bg-slate-50 px-3 py-2">
                  <SaveStateText state={saveState} />
                  <button className="button-primary" disabled={saveState === "saving" || (businessLocked && technicalLocked) || (!selected.business && !selected.lineage)} onClick={onSave} type="button"><Save size={15} />保存人工最终内容</button>
                </div>
              </>
            ) : null}

            <SectionTitle number="5" title="待业务 / 技术确认问题" />
            {selectedQuestions.length ? (
              <ul className="space-y-2">
                {selectedQuestions.slice(0, 6).map((question) => (
                  <li className="border-l-2 border-gold-300 bg-gold-50 px-3 py-2 text-[10px] leading-5 text-slate-700" key={question.id}>
                    <strong className="text-gold-800">{question.priority.toUpperCase()} · {question.question_type}：</strong>{question.question_text}
                    <span className="ml-2 text-slate-400">{question.question_status}</span>
                  </li>
                ))}
              </ul>
            ) : <p className="text-xs text-slate-500">当前目标表 / 字段没有未闭环问题。</p>}

            <footer className="mt-7 flex justify-between border-t border-line pt-3 text-[9px] text-slate-400">
              <span>来源：监管目标字段 + 场景口径 + 双层 Mapping + 已绑定证据</span>
              <span>AI 草稿不等于人工最终监管口径</span>
            </footer>
            </> : null}
            {activeTab === "structured" ? <StructuredCaliber
              businessFinal={businessFinal} businessLocked={businessLocked} onAdoptBusiness={onAdoptBusiness}
              onAdoptTechnical={onAdoptTechnical} onBusinessFinalChange={onBusinessFinalChange}
              onSave={onSave} onSelectField={onSelectField} onTechnicalFinalChange={onTechnicalFinalChange}
              records={records} saveState={saveState} selected={selected} technicalFinal={technicalFinal} technicalLocked={technicalLocked}
            /> : null}
            {activeTab === "lineage" ? <LineagePanel record={selected} martFields={martFields} martTables={martTables} sourceMappings={sourceMappings} /> : null}
            {activeTab === "evidence" ? <EvidencePanel evidenceCountByField={evidenceCountByField} onSelectField={onSelectField} onShowEvidence={onShowEvidence} records={records} selectedFieldId={selectedFieldId} /> : null}
            {activeTab === "questions" ? <QuestionsPanel questions={selectedQuestions} /> : null}
          </article>
        </div>
      )}
    </section>
  );
}

function WorkspaceTabs({ activeTab, onChange }: { activeTab: WorkspaceTab; onChange: (tab: WorkspaceTab) => void }) {
  return <div aria-label="需求工作台视图" className="mt-5 flex gap-1 overflow-x-auto border-b border-line" role="tablist">
    {WORKSPACE_TABS.map((tab) => <button aria-selected={tab.id === activeTab} className={`min-h-10 shrink-0 border-b-2 px-3 text-xs font-semibold ${tab.id === activeTab ? "border-pine-600 text-pine-700" : "border-transparent text-slate-500 hover:text-ink"}`} key={tab.id} onClick={() => onChange(tab.id)} role="tab" type="button">{tab.label}</button>)}
  </div>;
}

function StructuredCaliber({ records, selected, onSelectField, businessFinal, technicalFinal, onBusinessFinalChange, onTechnicalFinalChange, businessLocked, technicalLocked, saveState, onSave, onAdoptBusiness, onAdoptTechnical }: {
  records: FieldWorkspaceRecord[]; selected: FieldWorkspaceRecord | null; onSelectField: (id: number) => void;
  businessFinal: string; technicalFinal: string; onBusinessFinalChange: (value: string) => void; onTechnicalFinalChange: (value: string) => void;
  businessLocked: boolean; technicalLocked: boolean; saveState: SaveState; onSave: () => void; onAdoptBusiness: () => void; onAdoptTechnical: () => void;
}) {
  return <div className="mt-5 space-y-4"><div className="rounded-lg border border-pine-100 bg-pine-50/50 px-4 py-3 text-xs text-pine-900">结构化口径是当前事实视图：监管字段、业务定义、技术溯源、双层 Mapping 和治理状态均来自服务器真实记录；文档预览不会反向修改这些事实。</div>
    <div className="grid gap-3 md:grid-cols-2">{records.map((record) => <button className={`rounded-lg border p-3 text-left ${record.field.id === selected?.field.id ? "border-pine-400 bg-pine-50" : "border-line bg-white"}`} key={record.field.id} onClick={() => onSelectField(record.field.id)} type="button"><strong className="block text-xs text-ink">{record.field.field_name}</strong><span className="mt-1 block font-mono text-[10px] text-slate-400">{record.field.field_code}</span><span className="mt-2 block text-[11px] text-slate-600">业务：{record.business?.final_content || record.business?.ai_generated_content || "待维护"}</span><span className="mt-1 block text-[11px] text-slate-600">血缘：{record.lineage?.source_system_name || "待确认"} · {record.lineage?.lineage_status || "未关联"}</span></button>)}</div>
    {selected ? <div className="grid gap-3 lg:grid-cols-2"><MappingEditor aiDraft={selected.business?.ai_generated_content || ""} finalContent={businessFinal} label="业务口径" locked={businessLocked} onAdopt={onAdoptBusiness} onChange={onBusinessFinalChange} status={selected.business?.business_confirm_status || "未维护"} /><MappingEditor aiDraft={selected.lineage?.ai_generated_content || ""} finalContent={technicalFinal} label="技术溯源" locked={technicalLocked} onAdopt={onAdoptTechnical} onChange={onTechnicalFinalChange} status={selected.lineage?.tech_confirm_status || "未维护"} /><div className="flex items-center justify-between rounded-lg border border-line bg-slate-50 px-3 py-2 lg:col-span-2"><SaveStateText state={saveState} /><button className="button-primary" disabled={saveState === "saving" || (businessLocked && technicalLocked)} onClick={onSave} type="button"><Save size={15} />保存人工最终内容</button></div></div> : <p className="text-xs text-slate-500">请选择字段查看完整口径。</p>}
  </div>;
}

function LineagePanel({ record, martFields, martTables, sourceMappings }: { record: FieldWorkspaceRecord | null; martFields: MartField[]; martTables: MartTable[]; sourceMappings: SourceMappingIndex }) {
  return <div className="mt-5">{record ? <><p className="mb-3 text-xs text-slate-500">当前字段的 Source → Mart → YBT 可追溯链路</p><LineageFlow record={record} martFields={martFields} martTables={martTables} sourceMappings={sourceMappings} /></> : <p className="text-xs text-slate-500">请选择字段查看血缘。</p>}</div>;
}

function EvidencePanel({ records, selectedFieldId, evidenceCountByField, onSelectField, onShowEvidence }: { records: FieldWorkspaceRecord[]; selectedFieldId: number | null; evidenceCountByField: Record<number, number>; onSelectField: (id: number) => void; onShowEvidence: () => void }) {
  return <div className="mt-5 space-y-2"><p className="text-xs text-slate-500">证据正文按字段懒加载，避免首屏返回大文本。</p>{records.map((record) => <div className="flex items-center justify-between rounded-lg border border-line bg-white px-3 py-2" key={record.field.id}><span className="text-xs text-ink">{record.field.field_name}</span><button className="button-secondary h-8 text-xs" onClick={() => { onSelectField(record.field.id); onShowEvidence(); }} type="button">查看 {evidenceCountByField[record.field.id] || 0} 条证据</button></div>)}</div>;
}

function QuestionsPanel({ questions }: { questions: PendingQuestion[] }) {
  return <div className="mt-5">{questions.length ? <ul className="space-y-2">{questions.map((question) => <li className="rounded-lg border border-gold-200 bg-gold-50 px-3 py-2 text-xs text-slate-700" key={question.id}><strong>{question.priority.toUpperCase()} · {question.question_type}</strong><span className="ml-2">{question.question_text}</span><span className="ml-2 text-slate-400">{question.question_status}</span></li>)}</ul> : <div className="empty-state min-h-[180px]"><p>当前没有未闭环问题</p></div>}</div>;
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

function LineageFlow({ record, martFields, martTables, sourceMappings }: { record: FieldWorkspaceRecord; martFields: MartField[]; martTables: MartTable[]; sourceMappings: SourceMappingIndex }) {
  const martMapping = record.martMappings[0] || null;
  const martField = martFields.find((item) => item.id === martMapping?.mart_field_id) || null;
  const martTable = martTables.find((item) => item.id === martField?.mart_table_id) || null;
  const sourceMapping = martField ? sourceMappings[martField.id]?.[0] || null : null;
  const labels = buildLineageLabels({ lineage: record.lineage, sourceToMart: sourceMapping, martField, martTable, targetField: record.field });
  return (
    <div className="grid items-stretch gap-2 rounded-lg border border-line bg-slate-50/70 p-3 lg:grid-cols-[1fr_34px_1fr_34px_1fr]">
      <LineageNode eyebrow="业务源系统" title={record.lineage?.source_system_name || "来源待确认"} detail={labels.source} />
      <div className="flex items-center justify-center text-pine"><ArrowDown className="lg:-rotate-90" size={18} /></div>
      <LineageNode eyebrow="监管集市" title={martTable?.table_name || "集市字段待确认"} detail={labels.mart} />
      <div className="flex items-center justify-center text-pine"><ArrowDown className="lg:-rotate-90" size={18} /></div>
      <LineageNode eyebrow="一表通目标" title={record.field.field_name} detail={labels.target} />
    </div>
  );
}

function LineageNode({ eyebrow, title, detail }: { eyebrow: string; title: string; detail: string }) {
  return <div className="rounded-lg border border-line bg-white p-3"><span className="text-[9px] font-semibold uppercase tracking-wider text-slate-400">{eyebrow}</span><strong className="mt-1 block text-xs text-ink">{title}</strong><p className="mt-1 break-all font-mono text-[9px] leading-4 text-slate-500">{detail}</p></div>;
}

function MappingEditor({ label, status, aiDraft, finalContent, locked, onAdopt, onChange }: { label: string; status: string; aiDraft: string; finalContent: string; locked: boolean; onAdopt: () => void; onChange: (value: string) => void }) {
  return (
    <div className="rounded-lg border border-line bg-white p-3">
      <div className="flex items-center gap-2"><strong className="text-xs text-ink">{label}</strong><StatusBadge tone={mappingStatusTone(status)} value={mappingStatusLabel(status)} />{locked ? <span className="ml-auto flex items-center gap-1 text-[10px] text-gold-700"><ShieldAlert size={13} />治理态保护</span> : null}</div>
      <label className="mt-3 block text-[10px] font-semibold text-slate-500">AI 建议（只读）</label>
      <textarea className="control mt-1 min-h-24 resize-y bg-pine-50/40 text-xs leading-5" readOnly value={aiDraft} placeholder="尚未生成 AI 草稿" />
      <button className="button-secondary mt-2 h-8 text-xs" disabled={!aiDraft || locked} onClick={onAdopt} type="button"><Check size={14} />采用 AI 草稿</button>
      <label className="mt-3 block text-[10px] font-semibold text-slate-500">人工最终内容</label>
      <textarea className="control mt-1 min-h-28 resize-y text-xs leading-5" disabled={locked} onChange={(event) => onChange(event.target.value)} value={finalContent} placeholder="输入经人工校核的最终内容" />
    </div>
  );
}

function SaveStateText({ state }: { state: SaveState }) {
  const copy = state === "saving" ? "保存中…" : state === "dirty" ? "有未保存修改" : state === "saved" ? "已保存" : state === "error" ? "保存失败，人工内容未丢失" : "当前内容与服务器一致";
  const tone = state === "error" ? "text-coral-700" : state === "dirty" ? "text-gold-700" : state === "saved" ? "text-pine-700" : "text-slate-500";
  return <span className={`flex items-center gap-1.5 text-xs ${tone}`}>{state === "saved" ? <Check size={14} /> : state === "error" ? <ShieldAlert size={14} /> : <Save size={14} />}{copy}</span>;
}

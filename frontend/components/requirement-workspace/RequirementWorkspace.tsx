"use client";

import { AlertTriangle, RefreshCw } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { useProjectWorkspace } from "@/components/ProjectContext";
import { DocumentPreview } from "@/components/requirement-workspace/DocumentPreview";
import { EvidenceDrawer } from "@/components/requirement-workspace/EvidenceDrawer";
import { RequirementInputPanel } from "@/components/requirement-workspace/RequirementInputPanel";
import type { FieldWorkspaceRecord, SaveState, SourceMappingIndex } from "@/components/requirement-workspace/types";
import { useJobPolling } from "@/hooks/useJobPolling";
import {
  BackgroundJobSummary,
  BusinessSystem,
  DataSource,
  DeliverablePackage,
  MappingEvidence,
  MartField,
  MartTable,
  MartToYbtMapping,
  PendingQuestion,
  ProductScenario,
  ScenarioBusinessMapping,
  ScenarioTechnicalLineage,
  SourceToMartMapping,
  TargetField,
  TargetTable,
  apiDownload,
  apiGet,
  apiPost,
  apiPut
} from "@/lib/api";
import { isMappingLocked } from "@/lib/workspace-view-model.mjs";

type EvidenceIndex = Record<number, MappingEvidence[]>;

export function RequirementWorkspace() {
  const { projectId, selectedProject } = useProjectWorkspace();
  const [tables, setTables] = useState<TargetTable[]>([]);
  const [allFields, setAllFields] = useState<TargetField[]>([]);
  const [scenarios, setScenarios] = useState<ProductScenario[]>([]);
  const [businessSystems, setBusinessSystems] = useState<BusinessSystem[]>([]);
  const [datasources, setDatasources] = useState<DataSource[]>([]);
  const [martTables, setMartTables] = useState<MartTable[]>([]);
  const [martFields, setMartFields] = useState<MartField[]>([]);
  const [questions, setQuestions] = useState<PendingQuestion[]>([]);
  const [deliverables, setDeliverables] = useState<DeliverablePackage[]>([]);
  const [records, setRecords] = useState<FieldWorkspaceRecord[]>([]);
  const [sourceMappings, setSourceMappings] = useState<SourceMappingIndex>({});
  const [evidenceByField, setEvidenceByField] = useState<EvidenceIndex>({});
  const [tableId, setTableId] = useState<number | null>(null);
  const [fieldId, setFieldId] = useState<number | null>(null);
  const [scenarioId, setScenarioId] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [recordsLoading, setRecordsLoading] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [evidenceOpen, setEvidenceOpen] = useState(false);
  const [businessFinal, setBusinessFinal] = useState("");
  const [technicalFinal, setTechnicalFinal] = useState("");
  const [saveState, setSaveState] = useState<SaveState>("idle");
  const [businessJobId, setBusinessJobId] = useState<number | null>(null);
  const [technicalJobId, setTechnicalJobId] = useState<number | null>(null);
  const [businessJobSeed, setBusinessJobSeed] = useState<BackgroundJobSummary | null>(null);
  const [technicalJobSeed, setTechnicalJobSeed] = useState<BackgroundJobSummary | null>(null);
  const requestVersion = useRef(0);

  const fields = useMemo(() => allFields.filter((field) => field.target_table_id === tableId), [allFields, tableId]);
  const selectedTable = tables.find((table) => table.id === tableId) || null;
  const selectedScenario = scenarios.find((scenario) => scenario.id === scenarioId) || null;
  const selectedRecord = records.find((record) => record.field.id === fieldId) || null;
  const selectedField = selectedRecord?.field || fields.find((field) => field.id === fieldId) || null;
  const tableQuestions = questions.filter((question) => question.target_table_id === tableId && (!question.scenario_id || question.scenario_id === scenarioId));
  const selectedEvidence = fieldId ? evidenceByField[fieldId] || [] : [];
  const evidenceCountByField = useMemo(() => Object.fromEntries(Object.entries(evidenceByField).map(([key, value]) => [key, value.length])), [evidenceByField]);
  const deliverable = useMemo(() => deliverables
    .filter((item) => item.target_table_id === tableId)
    .sort((left, right) => right.version_no - left.version_no || right.id - left.id)[0] || null, [deliverables, tableId]);

  const loadRecords = useCallback(async () => {
    if (!projectId || !tableId) {
      setRecords([]);
      setSourceMappings({});
      setEvidenceByField({});
      return;
    }
    const version = ++requestVersion.current;
    setRecordsLoading(true);
    setError("");
    try {
      const tableFields = allFields.filter((field) => field.target_table_id === tableId);
      const nextRecords = await Promise.all(tableFields.map(async (field): Promise<FieldWorkspaceRecord> => {
        const [businessRows, lineageRows, martMappings] = await Promise.all([
          apiGet<ScenarioBusinessMapping[]>(`/target-fields/${field.id}/scenario-business-mappings`),
          apiGet<ScenarioTechnicalLineage[]>(`/target-fields/${field.id}/scenario-technical-lineages`),
          apiGet<MartToYbtMapping[]>(`/target-fields/${field.id}/mart-to-ybt-mappings`)
        ]);
        return {
          field,
          business: scenarioId ? businessRows.find((item) => item.scenario_id === scenarioId) || null : null,
          lineage: scenarioId ? lineageRows.find((item) => item.scenario_id === scenarioId) || null : null,
          martMappings
        };
      }));

      const martFieldIds = Array.from(new Set(nextRecords.flatMap((record) => record.martMappings.map((mapping) => mapping.mart_field_id).filter((id): id is number => Boolean(id)))));
      const sourceEntries = await Promise.all(martFieldIds.map(async (martFieldId) => [martFieldId, await apiGet<SourceToMartMapping[]>(`/mart-fields/${martFieldId}/source-to-mart-mappings`)] as const));
      const nextSourceMappings: SourceMappingIndex = Object.fromEntries(sourceEntries);
      const nextEvidenceEntries = await Promise.all(nextRecords.map(async (record) => {
        const refs: Array<[string, number]> = [];
        if (record.business) refs.push(["scenario_business", record.business.id]);
        if (record.lineage) refs.push(["scenario_technical", record.lineage.id]);
        for (const mapping of record.martMappings) refs.push(["mart_to_ybt", mapping.id]);
        for (const mapping of record.martMappings) {
          if (!mapping.mart_field_id) continue;
          for (const sourceMapping of nextSourceMappings[mapping.mart_field_id] || []) refs.push(["source_to_mart", sourceMapping.id]);
        }
        const groups = await Promise.all(refs.map(([type, id]) => apiGet<MappingEvidence[]>(`/mappings/${type}/${id}/evidence`).catch(() => [])));
        return [record.field.id, groups.flat()] as const;
      }));
      if (version !== requestVersion.current) return;
      setRecords(nextRecords);
      setSourceMappings(nextSourceMappings);
      setEvidenceByField(Object.fromEntries(nextEvidenceEntries));
    } catch (cause) {
      if (version === requestVersion.current) setError(readError(cause, "无法加载当前目标表的真实口径与溯源数据"));
    } finally {
      if (version === requestVersion.current) setRecordsLoading(false);
    }
  }, [allFields, projectId, scenarioId, tableId]);

  const businessJob = useJobPolling(businessJobId, { initialJob: businessJobSeed, onTerminal: () => loadRecords() }) || businessJobSeed;
  const technicalJob = useJobPolling(technicalJobId, { initialJob: technicalJobSeed, onTerminal: () => loadRecords() }) || technicalJobSeed;

  const loadWorkspace = useCallback(async () => {
    if (!projectId) {
      setTables([]); setAllFields([]); setRecords([]); setTableId(null); setFieldId(null); setScenarioId(null);
      return;
    }
    setLoading(true); setError(""); setNotice("");
    try {
      const [nextTables, nextFields, nextScenarios] = await Promise.all([
        apiGet<TargetTable[]>(`/target-tables?project_id=${projectId}`),
        apiGet<TargetField[]>(`/fields?project_id=${projectId}`),
        apiGet<ProductScenario[]>(`/projects/${projectId}/scenarios?enabled=true`)
      ]);
      const optional = await Promise.all([
        safeGet<BusinessSystem[]>(`/projects/${projectId}/business-systems`, []),
        safeGet<DataSource[]>(`/projects/${projectId}/datasources`, []),
        safeGet<MartTable[]>(`/projects/${projectId}/mart-tables`, []),
        safeGet<PendingQuestion[]>(`/projects/${projectId}/questions`, []),
        safeGet<DeliverablePackage[]>(`/projects/${projectId}/deliverables`, []),
        safeGet<BackgroundJobSummary[]>(`/jobs?project_id=${projectId}`, [])
      ]);
      const [nextSystems, nextDatasources, nextMartTables, nextQuestions, nextDeliverables, jobs] = optional;
      const nextMartFields = (await Promise.all(nextMartTables.map((table) => safeGet<MartField[]>(`/mart-tables/${table.id}/mart-fields`, [])))).flat();
      setTables(nextTables); setAllFields(nextFields); setScenarios(nextScenarios); setBusinessSystems(nextSystems);
      setDatasources(nextDatasources); setMartTables(nextMartTables); setMartFields(nextMartFields); setQuestions(nextQuestions); setDeliverables(nextDeliverables);
      setTableId((current) => current && nextTables.some((table) => table.id === current) ? current : nextTables[0]?.id || null);
      setScenarioId((current) => current && nextScenarios.some((scenario) => scenario.id === current) ? current : nextScenarios[0]?.id || null);
      const recentBusiness = jobs.find((job) => job.job_type === "batch_ai_generation_business") || null;
      const recentTechnical = jobs.find((job) => job.job_type === "batch_ai_generation_technical") || null;
      setBusinessJobSeed(recentBusiness); setBusinessJobId(recentBusiness?.id || null);
      setTechnicalJobSeed(recentTechnical); setTechnicalJobId(recentTechnical?.id || null);
      if (!nextTables.length) setNotice("当前项目没有目标表，请先导入并应用一表通监管模板。");
    } catch (cause) {
      setError(readError(cause, "无法加载当前项目，请确认后端服务和项目权限"));
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => { void loadWorkspace(); }, [loadWorkspace]);
  useEffect(() => { void loadRecords(); }, [loadRecords]);
  useEffect(() => {
    if (!fields.length) { setFieldId(null); return; }
    setFieldId((current) => current && fields.some((field) => field.id === current) ? current : fields[0].id);
  }, [fields]);
  useEffect(() => {
    setBusinessFinal(selectedRecord?.business?.final_content || "");
    setTechnicalFinal(selectedRecord?.lineage?.final_content || "");
    setSaveState("idle");
  }, [fieldId, scenarioId, selectedRecord?.business?.id, selectedRecord?.business?.final_content, selectedRecord?.lineage?.id, selectedRecord?.lineage?.final_content]);
  useEffect(() => {
    const beforeUnload = (event: BeforeUnloadEvent) => {
      if (saveState !== "dirty") return;
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", beforeUnload);
    return () => window.removeEventListener("beforeunload", beforeUnload);
  }, [saveState]);

  function guardUnsaved(action: () => void) {
    if (saveState === "dirty" && !window.confirm("当前字段有未保存修改。放弃修改并切换吗？")) return;
    setSaveState("idle");
    action();
  }

  function changeTable(nextTableId: number | null) {
    guardUnsaved(() => { setTableId(nextTableId); setFieldId(null); });
  }

  function changeScenario(nextScenarioId: number | null) {
    guardUnsaved(() => setScenarioId(nextScenarioId));
  }

  function changeField(nextFieldId: number) {
    guardUnsaved(() => setFieldId(nextFieldId));
  }

  async function generateDrafts() {
    if (!projectId || !selectedField || !scenarioId) return;
    if (saveState === "dirty") { setError("请先保存当前人工修改，再触发 AI 草稿任务。"); return; }
    setGenerating(true); setError(""); setNotice("");
    try {
      let business = selectedRecord?.business || null;
      if (!business) {
        business = await apiPost<ScenarioBusinessMapping>(`/target-fields/${selectedField.id}/scenarios/${scenarioId}/business-mapping`, {
          business_definition: selectedField.regulatory_refined_definition || selectedField.regulatory_description || selectedField.field_definition || null
        });
      }
      let lineage = selectedRecord?.lineage || null;
      if (!lineage) {
        lineage = await apiPost<ScenarioTechnicalLineage>(`/target-fields/${selectedField.id}/scenarios/${scenarioId}/technical-lineage`, {
          business_mapping_id: business.id,
          processing_logic_type: "pending_confirmation"
        });
      }
      const [nextBusinessJob, nextTechnicalJob] = await Promise.all([
        apiPost<BackgroundJobSummary>(`/projects/${projectId}/batch/generate-business-drafts`, { field_ids: [selectedField.id], scenario_id: scenarioId }),
        apiPost<BackgroundJobSummary>(`/projects/${projectId}/batch/generate-technical-drafts`, { field_ids: [selectedField.id], scenario_id: scenarioId })
      ]);
      setBusinessJobSeed(nextBusinessJob); setBusinessJobId(nextBusinessJob.id);
      setTechnicalJobSeed(nextTechnicalJob); setTechnicalJobId(nextTechnicalJob.id);
      setNotice("真实 AI 草稿任务已提交；人工最终内容没有被自动修改。");
      await loadRecords();
    } catch (cause) {
      setError(readError(cause, "AI 分析任务提交失败，现有人工口径未被修改"));
    } finally {
      setGenerating(false);
    }
  }

  async function adoptDraft(kind: "business" | "technical") {
    const mapping = kind === "business" ? selectedRecord?.business : selectedRecord?.lineage;
    if (!mapping) return;
    try {
      const path = kind === "business" ? `/scenario-business-mappings/${mapping.id}/adopt-ai-draft` : `/scenario-technical-lineages/${mapping.id}/adopt-ai-draft`;
      await apiPost(path, {});
      setNotice(`${kind === "business" ? "业务口径" : "技术溯源"} AI 草稿已显式采用为人工可编辑内容，尚未确认。`);
      await loadRecords();
    } catch (cause) { setError(readError(cause, "采用 AI 草稿失败")); }
  }

  async function saveFinalContent() {
    if (!selectedRecord) return;
    setSaveState("saving"); setError("");
    try {
      const actions: Promise<unknown>[] = [];
      if (selectedRecord.business && !isMappingLocked(selectedRecord.business.business_confirm_status)) actions.push(apiPut(`/scenario-business-mappings/${selectedRecord.business.id}`, { final_content: businessFinal }));
      if (selectedRecord.lineage && !isMappingLocked(selectedRecord.lineage.tech_confirm_status)) actions.push(apiPut(`/scenario-technical-lineages/${selectedRecord.lineage.id}`, { final_content: technicalFinal }));
      if (!actions.length) throw new Error("当前内容已进入确认或审核流程，不能在工作台直接修改。请进入字段场景审核任务处理。");
      await Promise.all(actions);
      setSaveState("saved"); setNotice("人工最终内容已保存。AI 草稿仍独立保留。" );
      await loadRecords();
    } catch (cause) {
      setSaveState("error"); setError(readError(cause, "保存失败，当前输入仍保留在页面中"));
    }
  }

  async function exportWorkbook() {
    if (!projectId) return;
    setExporting(true); setError("");
    try {
      const file = await apiDownload(`/projects/${projectId}/export/traceability-workbook`);
      const url = URL.createObjectURL(file.blob);
      const anchor = document.createElement("a"); anchor.href = url; anchor.download = file.fileName; anchor.click();
      URL.revokeObjectURL(url); setNotice(`已生成 ${file.fileName}`);
    } catch (cause) { setError(readError(cause, "需求文档导出失败")); }
    finally { setExporting(false); }
  }

  if (!projectId) {
    return <div className="p-6"><div className="empty-state min-h-[420px]"><AlertTriangle className="text-gold-400" size={32} /><p>当前未选择项目</p><p className="text-xs">请先在顶栏选择一个真实项目，再进入需求文档工作台。</p></div></div>;
  }

  if (loading) return <WorkspaceSkeleton />;

  return (
    <>
      <main className="min-w-[1180px]">
        <div className="border-b border-line bg-white px-5 py-4">
          <div className="flex items-end gap-4">
            <div className="min-w-0 flex-1"><h1 className="text-xl font-semibold tracking-tight text-ink">生成监管需求文档</h1><p className="mt-1 text-xs text-slate-500">基于真实监管目标、源系统、监管集市、历史知识与双层 Mapping，形成字段级需求文档草稿并交由人工校核。</p></div>
            <button className="button-secondary" onClick={() => { void loadWorkspace(); void loadRecords(); }} type="button"><RefreshCw size={15} />刷新真实数据</button>
          </div>
        </div>
        <div className="px-5 pt-4">
          <StepBar hasTable={Boolean(tableId)} hasScenario={Boolean(scenarioId)} hasDraft={records.some((record) => Boolean(record.business?.ai_generated_content || record.lineage?.ai_generated_content))} hasFinal={records.some((record) => Boolean(record.business?.final_content || record.lineage?.final_content))} />
          {error ? <div className="mt-3 flex items-start gap-2 rounded-lg border border-coral-200 bg-coral-50 px-3 py-2 text-sm text-coral-700" role="alert"><AlertTriangle className="mt-0.5 shrink-0" size={16} />{error}</div> : null}
          {notice ? <div className="mt-3 rounded-lg border border-pine-100 bg-pine-50 px-3 py-2 text-sm text-pine-800">{notice}</div> : null}
        </div>
        <div className="grid grid-cols-[390px_minmax(720px,1fr)] items-start gap-4 p-5">
          <RequirementInputPanel
            businessJob={businessJob}
            businessSystems={businessSystems}
            datasources={datasources}
            fieldId={fieldId}
            fields={fields}
            generating={generating}
            martTables={martTables}
            onFieldChange={changeField}
            onGenerate={() => void generateDrafts()}
            onScenarioChange={changeScenario}
            onTableChange={changeTable}
            scenarioId={scenarioId}
            scenarios={scenarios}
            selectedBusiness={selectedRecord?.business || null}
            selectedField={selectedField}
            selectedLineage={selectedRecord?.lineage || null}
            tableId={tableId}
            tables={tables}
            technicalJob={technicalJob}
          />
          <div className="relative min-w-0">
            {recordsLoading ? <div className="absolute inset-x-0 top-0 z-20 flex h-14 items-center justify-center border-b border-line bg-white/90 text-xs text-slate-500 backdrop-blur">正在装载真实字段口径、双层 Mapping 与证据…</div> : null}
            <DocumentPreview
              businessFinal={businessFinal}
              businessLocked={isMappingLocked(selectedRecord?.business?.business_confirm_status)}
              deliverable={deliverable}
              evidenceCountByField={evidenceCountByField}
              evidenceForSelected={selectedEvidence.length}
              exporting={exporting}
              martFields={martFields}
              martTables={martTables}
              onAdoptBusiness={() => void adoptDraft("business")}
              onAdoptTechnical={() => void adoptDraft("technical")}
              onBusinessFinalChange={(value) => { setBusinessFinal(value); setSaveState("dirty"); }}
              onExport={() => void exportWorkbook()}
              onSave={() => void saveFinalContent()}
              onSelectField={changeField}
              onShowEvidence={() => setEvidenceOpen(true)}
              onTechnicalFinalChange={(value) => { setTechnicalFinal(value); setSaveState("dirty"); }}
              projectName={selectedProject?.name || "当前项目"}
              questions={tableQuestions}
              records={records}
              saveState={saveState}
              scenario={selectedScenario}
              selectedFieldId={fieldId}
              sourceMappings={sourceMappings}
              table={selectedTable}
              technicalFinal={technicalFinal}
              technicalLocked={isMappingLocked(selectedRecord?.lineage?.tech_confirm_status)}
            />
          </div>
        </div>
      </main>
      <EvidenceDrawer items={selectedEvidence} onClose={() => setEvidenceOpen(false)} open={evidenceOpen} />
    </>
  );
}

function StepBar({ hasTable, hasScenario, hasDraft, hasFinal }: { hasTable: boolean; hasScenario: boolean; hasDraft: boolean; hasFinal: boolean }) {
  const steps = [
    { label: "选择监管目标", done: hasTable },
    { label: "配置分析范围", done: hasTable && hasScenario },
    { label: "AI 口径分析", done: hasDraft },
    { label: "人工校核与导出", done: hasFinal }
  ];
  const active = Math.max(0, steps.findIndex((step) => !step.done));
  return <div className="panel flex items-center px-4 py-3">{steps.map((step, index) => <div className="contents" key={step.label}><div className="flex min-w-[145px] items-center gap-2"><span className={`flex h-6 w-6 items-center justify-center rounded-full border text-[10px] font-bold ${step.done || index === active ? "border-pine bg-pine text-white" : "border-slate-300 bg-white text-slate-400"}`}>{step.done ? "✓" : index + 1}</span><span className={`text-xs font-semibold ${step.done ? "text-pine-700" : index === active ? "text-ink" : "text-slate-400"}`}>{step.label}</span></div>{index < steps.length - 1 ? <div className={`mx-2 h-px flex-1 ${step.done ? "bg-pine-300" : "bg-line"}`} /> : null}</div>)}</div>;
}

function WorkspaceSkeleton() {
  return <div className="min-w-[1180px] p-5"><div className="h-16 animate-pulse rounded-xl bg-white" /><div className="mt-4 grid grid-cols-[390px_1fr] gap-4"><div className="h-[700px] animate-pulse rounded-xl bg-white" /><div className="h-[760px] animate-pulse rounded-xl bg-white" /></div></div>;
}

async function safeGet<T>(path: string, fallback: T): Promise<T> {
  try { return await apiGet<T>(path); } catch { return fallback; }
}

function readError(error: unknown, fallback: string) {
  if (!(error instanceof Error) || !error.message) return fallback;
  return error.message.includes("Internal Server Error") ? fallback : error.message;
}

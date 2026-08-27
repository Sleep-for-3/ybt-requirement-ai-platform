"use client";

import { AlertTriangle, RefreshCw } from "lucide-react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useState } from "react";

import { useProjectWorkspace } from "@/components/ProjectContext";
import { DocumentPreview } from "@/components/requirement-workspace/DocumentPreview";
import { EvidenceDrawer } from "@/components/requirement-workspace/EvidenceDrawer";
import { RequirementInputPanel } from "@/components/requirement-workspace/RequirementInputPanel";
import type { FieldWorkspaceRecord, SaveState, SourceMappingIndex } from "@/components/requirement-workspace/types";
import { useJobPolling } from "@/hooks/useJobPolling";
import {
  BackgroundJobSummary,
  MartToYbtMapping,
  RequirementWorkspaceFieldDetail,
  RequirementWorkspaceRecordSummary,
  ScenarioBusinessMapping,
  ScenarioTechnicalLineage,
  SourceToMartMapping,
  apiDownload,
  apiPost,
  apiPut
} from "@/lib/api";
import { workspaceEvidenceOptions, workspaceFieldOptions, workspaceProjectionOptions, workspaceQueryKeys } from "@/lib/workspace-queries";
import { isMappingLocked } from "@/lib/workspace-view-model.mjs";

export function RequirementWorkspace() {
  const { projectId, selectedProject } = useProjectWorkspace();
  const queryClient = useQueryClient();
  const [tableId, setTableId] = useState<number | null>(null);
  const [fieldId, setFieldId] = useState<number | null>(null);
  const [scenarioId, setScenarioId] = useState<number | null>(null);
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
  const [activeTab, setActiveTab] = useState<"structured" | "lineage" | "evidence" | "questions" | "document">("structured");
  const projectionQuery = useQuery({
    ...workspaceProjectionOptions(projectId || 0, tableId, scenarioId),
    enabled:Boolean(projectId)
  });
  const projection = projectionQuery.data;
  const detailQuery = useQuery({
    ...workspaceFieldOptions(projectId || 0, fieldId || 0, scenarioId),
    enabled:Boolean(projectId && fieldId)
  });
  const evidenceQuery = useQuery({
    ...workspaceEvidenceOptions(projectId || 0, fieldId || 0, scenarioId),
    enabled:Boolean(projectId && fieldId && evidenceOpen)
  });

  const tables = projection?.tables || [];
  const scenarios = projection?.scenarios || [];
  const businessSystems = projection?.business_systems || [];
  const datasources = projection?.datasources || [];
  const martTables = projection?.mart_tables || [];
  const martFields = projection?.mart_fields || [];
  const questions = projection?.question_summaries || [];
  const fields = useMemo(() => (projection?.records || []).map((item) => summaryTargetField(item)), [projection?.records]);
  const summaryRecords = useMemo(() => (projection?.records || []).map((item) => summaryWorkspaceRecord(item, scenarioId)), [projection?.records, scenarioId]);
  const summarySourceMappings = useMemo(() => summarySourceMappingIndex(projection?.records || []), [projection?.records]);
  const records = useMemo(() => mergeSelectedDetail(summaryRecords, detailQuery.data || null), [summaryRecords, detailQuery.data]);
  const sourceMappings = useMemo(() => ({...summarySourceMappings, ...(detailQuery.data?.source_mappings || {})}), [summarySourceMappings, detailQuery.data]);
  const selectedTable = tables.find((table) => table.id === tableId) || null;
  const selectedScenario = scenarios.find((scenario) => scenario.id === scenarioId) || null;
  const selectedRecord = records.find((record) => record.field.id === fieldId) || null;
  const selectedField = selectedRecord?.field || fields.find((field) => field.id === fieldId) || null;
  const tableQuestions = questions.filter((question) => question.target_table_id === tableId && (!question.scenario_id || question.scenario_id === scenarioId));
  const selectedEvidence = evidenceQuery.data || [];
  const evidenceCountByField = useMemo(() => Object.fromEntries((projection?.records || []).map((item) => [item.field.id, item.evidence_count])), [projection?.records]);
  const deliverable = projection?.deliverable_summary || null;

  const refreshWorkspace = useCallback(async () => {
    if (!projectId) return;
    await queryClient.invalidateQueries({queryKey:workspaceQueryKeys.project(projectId)});
  }, [projectId, queryClient]);

  const businessJob = useJobPolling(businessJobId, { initialJob: businessJobSeed, onTerminal: () => { void refreshWorkspace(); } }) || businessJobSeed;
  const technicalJob = useJobPolling(technicalJobId, { initialJob: technicalJobSeed, onTerminal: () => { void refreshWorkspace(); } }) || technicalJobSeed;

  useEffect(() => {
    setTableId(null); setFieldId(null); setScenarioId(null); setEvidenceOpen(false); setError(""); setNotice("");
    setActiveTab("structured");
  }, [projectId]);
  useEffect(() => {
    if (!projectId || !projection) return;
    const nextTableId = tableId && projection.tables.some((item) => item.id === tableId) ? tableId : projection.selected_target_table_id || null;
    const nextScenarioId = scenarioId && projection.scenarios.some((item) => item.id === scenarioId) ? scenarioId : projection.selected_scenario_id || null;
    if (nextTableId !== tableId || nextScenarioId !== scenarioId) {
      queryClient.setQueryData(workspaceProjectionOptions(projectId, nextTableId, nextScenarioId).queryKey, projection);
      setTableId(nextTableId); setScenarioId(nextScenarioId);
    }
    const recentBusiness = projection.recent_jobs.find((job) => job.job_type === "batch_ai_generation_business") || null;
    const recentTechnical = projection.recent_jobs.find((job) => job.job_type === "batch_ai_generation_technical") || null;
    setBusinessJobSeed(recentBusiness); setBusinessJobId(recentBusiness?.id || null);
    setTechnicalJobSeed(recentTechnical); setTechnicalJobId(recentTechnical?.id || null);
    if (!projection.tables.length) setNotice("当前项目没有目标表，请先导入并应用一表通监管模板。");
  }, [projectId, projection, queryClient, scenarioId, tableId]);
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
    guardUnsaved(() => {
      if (projectId && nextTableId) void queryClient.prefetchQuery(workspaceProjectionOptions(projectId, nextTableId, scenarioId));
      setTableId(nextTableId); setFieldId(null);
    });
  }

  function changeScenario(nextScenarioId: number | null) {
    guardUnsaved(() => {
      if (projectId) void queryClient.prefetchQuery(workspaceProjectionOptions(projectId, tableId, nextScenarioId));
      setScenarioId(nextScenarioId);
    });
  }

  function changeField(nextFieldId: number) {
    guardUnsaved(() => {
      if (projectId) void queryClient.prefetchQuery(workspaceFieldOptions(projectId, nextFieldId, scenarioId));
      setFieldId(nextFieldId);
    });
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
      await refreshWorkspace();
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
      await refreshWorkspace();
    } catch (cause) { setError(readError(cause, "采用 AI 草稿失败")); }
  }

  async function saveFinalContent() {
    if (!selectedRecord) return;
    if (!detailQuery.data) { setError("当前字段完整口径仍在加载，请稍后再保存。"); return; }
    setSaveState("saving"); setError("");
    try {
      const actions: Promise<unknown>[] = [];
      if (selectedRecord.business && !isMappingLocked(selectedRecord.business.business_confirm_status)) actions.push(apiPut(`/scenario-business-mappings/${selectedRecord.business.id}`, { final_content: businessFinal }));
      if (selectedRecord.lineage && !isMappingLocked(selectedRecord.lineage.tech_confirm_status)) actions.push(apiPut(`/scenario-technical-lineages/${selectedRecord.lineage.id}`, { final_content: technicalFinal }));
      if (!actions.length) throw new Error("当前内容已进入确认或审核流程，不能在工作台直接修改。请进入字段场景审核任务处理。");
      await Promise.all(actions);
      setSaveState("saved"); setNotice("人工最终内容已保存。AI 草稿仍独立保留。" );
      await refreshWorkspace();
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

  if (projectionQuery.isPending) return <WorkspaceSkeleton />;

  const queryError = projectionQuery.error ? readError(projectionQuery.error, "无法加载当前项目，请确认后端服务和项目权限") : detailQuery.error ? readError(detailQuery.error, "无法加载当前字段详情") : "";

  return (
    <>
      <main className="min-w-[1180px]">
        <div className="border-b border-line bg-white px-5 py-4">
          <div className="flex items-end gap-4">
            <div className="min-w-0 flex-1"><h1 className="text-xl font-semibold tracking-tight text-ink">生成监管需求文档</h1><p className="mt-1 text-xs text-slate-500">基于真实监管目标、源系统、监管集市、历史知识与双层 Mapping，形成字段级需求文档草稿并交由人工校核。</p></div>
            <button className="button-secondary" disabled={projectionQuery.isFetching} onClick={() => { void refreshWorkspace(); }} type="button"><RefreshCw size={15} />{projectionQuery.isFetching?"刷新中…":"刷新真实数据"}</button>
          </div>
        </div>
        <div className="px-5 pt-4">
          <StepBar hasTable={Boolean(tableId)} hasScenario={Boolean(scenarioId)} hasDraft={Boolean(projection?.records.some((record) => record.business?.has_ai_draft || record.lineage?.has_ai_draft))} hasFinal={Boolean(projection?.records.some((record) => record.business?.has_final || record.lineage?.has_final))} />
          {error || queryError ? <div className="mt-3 flex items-start gap-2 rounded-lg border border-coral-200 bg-coral-50 px-3 py-2 text-sm text-coral-700" role="alert"><AlertTriangle className="mt-0.5 shrink-0" size={16} />{error || queryError}</div> : null}
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
            {detailQuery.isFetching ? <div className="absolute inset-x-0 top-0 z-20 flex h-14 items-center justify-center border-b border-line bg-white/90 text-xs text-slate-500 backdrop-blur">正在懒加载当前字段完整口径与双层 Mapping…</div> : null}
            <DocumentPreview
              businessFinal={businessFinal}
              activeTab={activeTab}
              businessLocked={isMappingLocked(selectedRecord?.business?.business_confirm_status)}
              deliverable={deliverable}
              evidenceCountByField={evidenceCountByField}
              evidenceForSelected={fieldId ? evidenceCountByField[fieldId] || 0 : 0}
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
              onTabChange={setActiveTab}
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
      <EvidenceDrawer error={evidenceQuery.error ? readError(evidenceQuery.error,"证据加载失败") : ""} items={selectedEvidence} loading={evidenceQuery.isPending && evidenceQuery.fetchStatus === "fetching"} onClose={() => setEvidenceOpen(false)} open={evidenceOpen} />
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

function summaryTargetField(item: RequirementWorkspaceRecordSummary): FieldWorkspaceRecord["field"] {
  return {
    id:item.field.id, project_id:item.field.project_id, target_table_id:item.field.target_table_id,
    field_code:item.field.field_code, field_name:item.field.field_name, field_type:item.field.field_type,
    required_flag:item.field.required_flag, regulatory_refined_definition:item.field.definition_preview
  };
}

function summaryWorkspaceRecord(item:RequirementWorkspaceRecordSummary, scenarioId:number|null):FieldWorkspaceRecord {
  const field = summaryTargetField(item);
  const business:ScenarioBusinessMapping|null = item.business ? {
    id:item.business.id, project_id:field.project_id, target_field_id:field.id, scenario_id:scenarioId || 0,
    business_definition:item.business.content_preview, source_system_screenshot_required:false,
    source_system_change_required:false, external_data_required:false, manual_supplement_required:false,
    business_confirm_status:item.business.status, ai_generated_content:item.business.has_ai_draft?item.business.content_preview:null,
    final_content:null, confidence_level:item.business.confidence_level
  } : null;
  const lineage:ScenarioTechnicalLineage|null = item.lineage ? {
    id:item.lineage.id, project_id:field.project_id, target_field_id:field.id, scenario_id:scenarioId || 0,
    source_system_name:item.lineage.source_system_name, source_database_name:item.lineage.source_database_name,
    source_schema_name:item.lineage.source_schema_name, source_table_english_name:item.lineage.source_table_name,
    source_field_english_name:item.lineage.source_field_name, processing_logic:item.lineage.content_preview,
    tech_confirm_status:item.lineage.status, ai_generated_content:item.lineage.has_ai_draft?item.lineage.content_preview:null,
    final_content:null, confidence_level:item.lineage.confidence_level,
    lineage_status:item.lineage.lineage_status
  } : null;
  const martMappings:MartToYbtMapping[] = item.mart_mappings.map((mapping)=>({
    id:mapping.id, project_id:field.project_id, target_field_id:field.id, mart_field_id:mapping.mart_field_id,
    mapping_status:mapping.status, business_rule:mapping.content_preview, final_content:mapping.content_preview,
    confidence_level:mapping.confidence_level, lineage_status:mapping.lineage_status
  }));
  return {field,business,lineage,martMappings};
}

function summarySourceMappingIndex(items:RequirementWorkspaceRecordSummary[]):SourceMappingIndex {
  const output:SourceMappingIndex={};
  for (const item of items) for (const [martFieldId,rows] of Object.entries(item.source_mappings)) {
    output[Number(martFieldId)] = rows.map((mapping):SourceToMartMapping=>({
      id:mapping.id, project_id:item.field.project_id, mart_field_id:Number(martFieldId), mapping_status:mapping.status,
      source_system_summary:mapping.source_system_summary, business_rule:mapping.content_preview,
      final_content:mapping.content_preview, confidence_level:mapping.confidence_level, lineage_status:mapping.lineage_status
    }));
  }
  return output;
}

function mergeSelectedDetail(records:FieldWorkspaceRecord[], detail:RequirementWorkspaceFieldDetail|null):FieldWorkspaceRecord[] {
  if (!detail) return records;
  return records.map((record)=>record.field.id===detail.field.id?{
    field:detail.field, business:detail.business||null, lineage:detail.lineage||null, martMappings:detail.mart_mappings
  }:record);
}

function readError(error: unknown, fallback: string) {
  if (!(error instanceof Error) || !error.message) return fallback;
  return error.message.includes("Internal Server Error") ? fallback : error.message;
}

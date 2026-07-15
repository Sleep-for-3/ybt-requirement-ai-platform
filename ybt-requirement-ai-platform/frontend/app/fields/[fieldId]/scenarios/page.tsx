"use client";

import { Check, Clock3, DatabaseZap, Link2, Save, Search, Sparkles, X } from "lucide-react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { WorkspaceHeader } from "@/components/WorkspaceHeader";
import {
  CandidateSourceRecommendation, ColumnProfileSnapshot, ColumnProfileTask, HybridKnowledgeItem, MappingEvidence, ProductScenario, RegulatoryKnowledgeItem, ScenarioBusinessMapping,
  ScenarioTechnicalLineage, TargetField, apiGet, apiPost, apiPut,
} from "@/lib/api";

const EMPTY_BUSINESS = {
  business_definition: "", source_system_screenshot_required: false, source_system_change_required: false,
  external_data_required: false, manual_supplement_required: false, business_owner: "", remarks: "",
  ai_generated_content: "", final_content: "", confidence_level: "medium", open_questions: "",
};
const EMPTY_LINEAGE = {
  source_system_name: "", source_database_name: "", source_schema_name: "", source_table_english_name: "",
  source_table_chinese_name: "", source_field_english_name: "", source_field_chinese_name: "",
  processing_logic: "", processing_logic_type: "pending_confirmation", tech_owner: "", remarks: "",
  ai_generated_content: "", final_content: "", confidence_level: "medium", open_questions: "",
};
const EMPTY_PROFILE: ColumnProfileTask = { id: 0, status: "", catalog_column_id: 0, profile_result_json: {}, generated_sql_json: [] };

export default function FieldScenarioPage() {
  const fieldId = Number(useParams<{ fieldId: string }>().fieldId);
  const [field, setField] = useState<TargetField | null>(null);
  const [scenarios, setScenarios] = useState<ProductScenario[]>([]);
  const [businesses, setBusinesses] = useState<ScenarioBusinessMapping[]>([]);
  const [lineages, setLineages] = useState<ScenarioTechnicalLineage[]>([]);
  const [scenarioId, setScenarioId] = useState<number | null>(null);
  const [businessForm, setBusinessForm] = useState<Record<string, string | boolean>>(EMPTY_BUSINESS);
  const [lineageForm, setLineageForm] = useState<Record<string, string>>(EMPTY_LINEAGE);
  const [knowledge, setKnowledge] = useState<RegulatoryKnowledgeItem[]>([]);
  const [ragKnowledge, setRagKnowledge] = useState<HybridKnowledgeItem[]>([]);
  const [groundedAnswer, setGroundedAnswer] = useState<Record<string, unknown> | null>(null);
  const [recommendations, setRecommendations] = useState<CandidateSourceRecommendation[]>([]);
  const [selectedRecommendationId, setSelectedRecommendationId] = useState<number | null>(null);
  const [profileTask, setProfileTask] = useState<ColumnProfileTask>(EMPTY_PROFILE);
  const [profileHistory, setProfileHistory] = useState<{ columnId: number; items: ColumnProfileSnapshot[] } | null>(null);
  const [datasourceFilter, setDatasourceFilter] = useState("");
  const [schemaFilter, setSchemaFilter] = useState("");
  const [businessEvidences, setBusinessEvidences] = useState<MappingEvidence[]>([]);
  const [businessEvidenceText, setBusinessEvidenceText] = useState("");
  const [showBusinessEvidenceForm, setShowBusinessEvidenceForm] = useState(false);
  const [technicalEvidences, setTechnicalEvidences] = useState<MappingEvidence[]>([]);
  const [evidenceText, setEvidenceText] = useState("");
  const [showEvidenceForm, setShowEvidenceForm] = useState(false);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [reviewTasks,setReviewTasks]=useState<Array<{id:number;step_key:string;status:string;target_type:string;target_id:number;assignee_user_id?:number|null;due_at?:string|null}>>([]);

  const business = useMemo(() => businesses.find((item) => item.scenario_id === scenarioId) || null, [businesses, scenarioId]);
  const lineage = useMemo(() => lineages.find((item) => item.scenario_id === scenarioId) || null, [lineages, scenarioId]);
  const contextualReviewTasks = useMemo(() => reviewTasks.filter((task) =>
    (task.target_type === "scenario_business" && task.target_id === business?.id) ||
    (task.target_type === "scenario_technical" && task.target_id === lineage?.id)
  ), [reviewTasks, business?.id, lineage?.id]);

  async function reload() {
    const target = await apiGet<TargetField>(`/fields/${fieldId}`);
    const [scenarioItems, businessItems, lineageItems] = await Promise.all([
      apiGet<ProductScenario[]>(`/projects/${target.project_id}/scenarios?enabled=true`),
      apiGet<ScenarioBusinessMapping[]>(`/target-fields/${fieldId}/scenario-business-mappings`),
      apiGet<ScenarioTechnicalLineage[]>(`/target-fields/${fieldId}/scenario-technical-lineages`),
    ]);
    setField(target); setScenarios(scenarioItems); setBusinesses(businessItems); setLineages(lineageItems);
    try { setReviewTasks(await apiGet(`/projects/${target.project_id}/tasks`)); } catch { setReviewTasks([]); }
    setScenarioId((value) => value || scenarioItems[0]?.id || null);
  }
  useEffect(() => { if (fieldId) void reload(); }, [fieldId]);
  useEffect(() => {
    setBusinessForm(business ? {
      business_definition: business.business_definition || "",
      source_system_screenshot_required: business.source_system_screenshot_required,
      source_system_change_required: business.source_system_change_required,
      external_data_required: business.external_data_required,
      manual_supplement_required: business.manual_supplement_required,
      business_owner: business.business_owner || "",
      remarks: business.remarks || "",
      ai_generated_content: business.ai_generated_content || "",
      final_content: business.final_content || "",
      confidence_level: business.confidence_level,
      open_questions: business.open_questions || "",
    } : EMPTY_BUSINESS);
    setLineageForm(lineage ? {
      source_system_name: lineage.source_system_name || "",
      source_database_name: lineage.source_database_name || "",
      source_schema_name: lineage.source_schema_name || "",
      source_table_english_name: lineage.source_table_english_name || "",
      source_table_chinese_name: lineage.source_table_chinese_name || "",
      source_field_english_name: lineage.source_field_english_name || "",
      source_field_chinese_name: lineage.source_field_chinese_name || "",
      processing_logic: lineage.processing_logic || "",
      processing_logic_type: lineage.processing_logic_type || "pending_confirmation",
      tech_owner: lineage.tech_owner || "",
      remarks: lineage.remarks || "",
      ai_generated_content: lineage.ai_generated_content || "",
      final_content: lineage.final_content || "",
      confidence_level: lineage.confidence_level,
      open_questions: lineage.open_questions || "",
    } : EMPTY_LINEAGE);
    setKnowledge([]); setRagKnowledge([]); setGroundedAnswer(null); setRecommendations([]); setSelectedRecommendationId(null); setProfileTask(EMPTY_PROFILE); setProfileHistory(null); setMessage("");
    setBusinessEvidenceText(""); setShowBusinessEvidenceForm(false);
    setEvidenceText(""); setShowEvidenceForm(false);
    if (business) {
      void apiGet<MappingEvidence[]>(`/mappings/scenario_business/${business.id}/evidence`).then(setBusinessEvidences);
    } else {
      setBusinessEvidences([]);
    }
    if (lineage) {
      void apiGet<MappingEvidence[]>(`/mappings/scenario_technical/${lineage.id}/evidence`).then(setTechnicalEvidences);
    } else {
      setTechnicalEvidences([]);
    }
  }, [business, lineage, scenarioId]);

  async function run(action: () => Promise<unknown>, success: string) {
    setBusy(true); setMessage("");
    try { await action(); setMessage(success); await reload(); }
    catch (error) { setMessage(error instanceof Error ? error.message : "操作失败"); }
    finally { setBusy(false); }
  }

  async function saveBusiness() {
    if (!scenarioId) return;
    const payload = businessForm;
    await run(
      () => business ? apiPut(`/scenario-business-mappings/${business.id}`, payload) : apiPost(`/target-fields/${fieldId}/scenarios/${scenarioId}/business-mapping`, payload),
      "业务口径已保存",
    );
  }
  async function saveLineage() {
    if (!scenarioId) return;
    const payload = { ...lineageForm, business_mapping_id: business?.id || null };
    await run(
      () => lineage ? apiPut(`/scenario-technical-lineages/${lineage.id}`, payload) : apiPost(`/target-fields/${fieldId}/scenarios/${scenarioId}/technical-lineage`, payload),
      "技术溯源已保存",
    );
  }
  async function searchKnowledge() {
    if (!field || !scenarioId) return;
    const result = await apiPost<{ items: RegulatoryKnowledgeItem[] }>(`/projects/${field.project_id}/knowledge/search`, {
      target_field_code: field.field_code, scenario_id: scenarioId, query: field.field_name, top_k: 20,
    });
    setKnowledge(result.items); setMessage(`检索到 ${result.items.length} 条历史知识`);
  }
  async function searchRagKnowledge(knowledgeTypes?: string[]) {
    if (!field || !scenarioId) return;
    const result = await apiPost<{ items: HybridKnowledgeItem[] }>(`/projects/${field.project_id}/knowledge/hybrid-search`, {
      query: `${field.field_code} ${field.field_name}`,
      target_field_id: field.id,
      scenario_id: scenarioId,
      knowledge_types: knowledgeTypes || [],
      top_k: 20,
    });
    setRagKnowledge(result.items); setMessage(`混合检索命中 ${result.items.length} 条带出处知识`);
  }
  async function explainField() {
    if (!field || !scenarioId) return;
    const result = await apiPost<Record<string, unknown>>(`/projects/${field.project_id}/knowledge/ask`, {
      query: `请解释 ${field.field_code} ${field.field_name} 在当前场景中的监管含义和来源依据`,
      target_field_id: field.id,
      scenario_id: scenarioId,
      top_k: 10,
    });
    setGroundedAnswer(result); setMessage("已生成带真实引用的字段解释");
  }
  async function submitFeedback(targetId: number, rating: "correct" | "partially_correct" | "incorrect") {
    if (!field) return;
    await apiPost(`/projects/${field.project_id}/feedback`, {
      feedback_type: "retrieval", target_type: "knowledge_unit", target_id: targetId, rating,
    });
    setMessage("反馈已保存");
  }
  async function recommend() {
    if (!scenarioId) return;
    const result = await apiPost<{ recommendations: CandidateSourceRecommendation[] }>(`/target-fields/${fieldId}/scenarios/${scenarioId}/recommend-sources`, {});
    setRecommendations(result.recommendations); setMessage(`生成 ${result.recommendations.length} 个候选来源`);
  }
  async function selectCatalogCandidate(item: CandidateSourceRecommendation) {
    const result = await apiPost<{ recommendation: CandidateSourceRecommendation }>(`/source-recommendations/${item.id}/select`, {});
    setSelectedRecommendationId(result.recommendation.id); setMessage("候选已选择，尚未探查或采用");
    if (!item.catalog_column_id) await reload();
  }
  async function profileCatalogCandidate(item: CandidateSourceRecommendation) {
    if (!field || !scenarioId || !item.catalog_column_id) return;
    try { const task = await apiPost<ColumnProfileTask>(`/catalog/columns/${item.catalog_column_id}/profile`, { target_field_id: field.id, scenario_id: scenarioId, source_recommendation_id: item.id, metrics: ["null_rate", "distinct_count", "top_values", "min_max", "length_distribution"] }); setProfileTask(task); setMessage(`安全探查 ${task.status}`); }
    catch (error) { setMessage(error instanceof Error ? error.message : "探查失败"); }
  }
  async function adoptCatalogCandidate(item: CandidateSourceRecommendation) {
    await run(() => apiPost(`/source-recommendations/${item.id}/adopt`, {}), "已采用目录候选作为技术来源");
  }
  async function showProfileHistory(item: CandidateSourceRecommendation) {
    if (!item.catalog_column_id) return;
    const items = await apiGet<ColumnProfileSnapshot[]>(`/catalog/columns/${item.catalog_column_id}/profiles`);
    setProfileHistory({ columnId: item.catalog_column_id, items });
  }
  async function bindTechnicalEvidence() {
    if (!lineage || !field || !evidenceText.trim()) return;
    await run(
      () => apiPost(`/mappings/scenario_technical/${lineage.id}/evidence`, {
        evidence_type: "manual_note",
        source_name: "字段场景工作台人工证据",
        location_text: `${field.field_code} / ${scenarios.find((item) => item.id === scenarioId)?.scenario_name || "当前场景"}`,
        quoted_content: evidenceText.trim(),
        evidence_summary: evidenceText.trim(),
      }),
      "技术溯源证据已绑定",
    );
  }
  async function bindBusinessEvidence() {
    if (!business || !field || !businessEvidenceText.trim()) return;
    await run(
      () => apiPost(`/mappings/scenario_business/${business.id}/evidence`, {
        evidence_type: "manual_note",
        source_name: "字段场景工作台人工证据",
        location_text: `${field.field_code} / ${scenarios.find((item) => item.id === scenarioId)?.scenario_name || "当前场景"}`,
        quoted_content: businessEvidenceText.trim(),
        evidence_summary: businessEvidenceText.trim(),
      }),
      "业务口径证据已绑定",
    );
  }

  if (!field) return <main className="p-6 text-sm text-slate-500">加载中...</main>;
  return (
    <main>
      <WorkspaceHeader title={`${field.field_code} ${field.field_name}`} meta={`${field.data_category || "未分类"} / ${field.data_format || field.field_type || "格式待确认"}`} />
      <div className="border-b border-line bg-white px-4 py-4 lg:px-6">
        <div className="mx-auto grid max-w-[1600px] gap-3 text-sm md:grid-cols-3 xl:grid-cols-6">
          <Meta label="监管原始口径" value={field.regulatory_original_definition || field.regulatory_description} />
          <Meta label="监管定义细化" value={field.regulatory_refined_definition} />
          <Meta label="EAST 同源映射" value={field.east_definition} />
          <Meta label="字段业务定义（行内）" value={field.internal_definition || field.field_definition} />
          <Meta label="报表名称" value={field.report_name} />
          <Meta label="字段名称" value={field.report_field_name} />
        </div>
      </div>
      <div className="mx-auto max-w-[1600px] p-4 lg:p-6">
        <div className="mb-4 flex gap-2 overflow-x-auto border-b border-line pb-3">
          {scenarios.map((item) => <button className={item.id === scenarioId ? "button-primary" : "button-secondary"} key={item.id} onClick={() => setScenarioId(item.id)}>{item.scenario_name}</button>)}
        </div>
        {message ? <div className="mb-4 rounded-md border border-line bg-white px-4 py-3 text-sm">{message}</div> : null}
        <section className="panel mb-5 p-4"><div className="flex flex-wrap items-center justify-between gap-3"><div><h2 className="font-semibold">协作与审核状态</h2><p className="mt-1 text-xs text-slate-500">仅显示当前字段和场景；点击任务查看审核意见、退回原因与历史快照</p></div><div className="flex gap-2"><Link className="button-secondary" href={`/projects/${field.project_id}/dashboard`}>项目看板</Link><Link className="button-secondary" href={`/audit?projectId=${field.project_id}`}>操作审计</Link></div></div><div className="mt-4 grid gap-3 md:grid-cols-3 xl:grid-cols-5">{contextualReviewTasks.map(task=><Link className="rounded-md border border-line p-3 text-sm hover:bg-slate-50" href={`/tasks/${task.id}`} key={task.id}><b>{task.step_key}</b><div className="mt-1 text-xs text-slate-500">{task.status} · 负责人 #{task.assignee_user_id||"待领取"}</div><div className="mt-1 text-xs text-slate-500">到期：{task.due_at||"未设置"}</div><div className="mt-2 text-xs text-blue-600">审核意见与历史快照 →</div></Link>)}{!contextualReviewTasks.length?<div className="text-sm text-slate-500">当前字段场景暂无审核任务</div>:null}</div></section>
        <div className="grid gap-5 xl:grid-cols-2">
          <section className="panel overflow-hidden">
            <PanelTitle title="业务口径" status={business?.business_confirm_status || "未维护"} />
            <div className="grid gap-3 p-4 md:grid-cols-2">
              <Field label="字段业务定义" wide><textarea className="control min-h-24" value={String(businessForm.business_definition || "")} onChange={(e) => setBusinessForm({ ...businessForm, business_definition: e.target.value })} /></Field>
              {[
                ["source_system_screenshot_required", "源系统截图"], ["source_system_change_required", "源系统改造"],
                ["external_data_required", "外部数据"], ["manual_supplement_required", "手工补录"],
              ].map(([key, label]) => <label className="flex h-10 items-center gap-2 rounded-md border border-line px-3 text-sm" key={key}><input checked={Boolean(businessForm[key])} onChange={(e) => setBusinessForm({ ...businessForm, [key]: e.target.checked })} type="checkbox" />{label}</label>)}
              <TextInput label="业务口径确认人" value={String(businessForm.business_owner || "")} onChange={(value) => setBusinessForm({ ...businessForm, business_owner: value })} />
              <TextInput label="置信度" value={String(businessForm.confidence_level || "medium")} onChange={(value) => setBusinessForm({ ...businessForm, confidence_level: value })} />
              <Field label="备注" wide><textarea className="control min-h-20" value={String(businessForm.remarks || "")} onChange={(e) => setBusinessForm({ ...businessForm, remarks: e.target.value })} /></Field>
              <Field label="AI 草稿" wide><textarea className="control min-h-28 bg-slate-50" readOnly value={String(businessForm.ai_generated_content || "")} /></Field>
              <Field label="最终口径" wide><textarea className="control min-h-32" value={String(businessForm.final_content || "")} onChange={(e) => setBusinessForm({ ...businessForm, final_content: e.target.value })} /></Field>
              <Field label="待确认问题" wide><textarea className="control min-h-20" value={String(businessForm.open_questions || "")} onChange={(e) => setBusinessForm({ ...businessForm, open_questions: e.target.value })} /></Field>
            </div>
            <div className="flex flex-wrap gap-2 border-t border-line p-4">
              <button className="button-secondary" onClick={searchKnowledge}><Search size={16} />检索历史知识</button>
              <button className="button-secondary" onClick={() => searchRagKnowledge(["regulatory_qa"])}><Search size={16} />检索监管答疑</button>
              <button className="button-secondary" onClick={() => searchRagKnowledge(["historical_mapping", "historical_traceability"])}><Search size={16} />检索历史口径</button>
              <button className="button-secondary" onClick={explainField}><Sparkles size={16} />解释字段含义</button>
              <button className="button-secondary" onClick={recommend}><DatabaseZap size={16} />从数据目录搜索</button>
              <button className="button-secondary" disabled={!business || busy} onClick={() => run(() => apiPost(`/scenario-business-mappings/${business!.id}/generate-draft`, {}), "AI 业务草稿已生成")}><Sparkles size={16} />AI 草稿</button>
              <button className="button-secondary" disabled={!business?.ai_generated_content || busy} onClick={() => run(() => apiPost(`/scenario-business-mappings/${business!.id}/adopt-ai-draft`, {}), "已采用 AI 草稿")}><Check size={16} />采用草稿</button>
              <button className="button-primary" disabled={busy} onClick={saveBusiness}><Save size={16} />保存</button>
              <button className="button-secondary" disabled={!business || busy} onClick={() => run(() => apiPost(`/scenario-business-mappings/${business!.id}/confirm`, {}), "业务口径已确认")}><Check size={16} />业务确认</button>
              <button className="button-danger" disabled={!business || busy} onClick={() => run(() => apiPost(`/scenario-business-mappings/${business!.id}/reject`, {}), "业务口径已驳回")}><X size={16} />驳回</button>
              <button className="button-secondary" disabled={!business} onClick={() => setShowBusinessEvidenceForm((value) => !value)}><Link2 size={16} />绑定证据</button>
            </div>
            {showBusinessEvidenceForm ? <div className="border-t border-line bg-slate-50 p-4"><label className="text-xs text-slate-500" htmlFor="business-evidence">人工证据说明</label><textarea className="control mt-1 min-h-20" id="business-evidence" onChange={(event) => setBusinessEvidenceText(event.target.value)} placeholder="填写脱敏的业务访谈结论或监管答疑依据" value={businessEvidenceText} /><button className="button-primary mt-2" disabled={!businessEvidenceText.trim() || busy} onClick={bindBusinessEvidence}><Link2 size={16} />确认绑定</button>{businessEvidences.length ? <div className="mt-3 space-y-2">{businessEvidences.map((item) => <div className="rounded-md border border-line bg-white p-2 text-xs" key={item.id}><strong>{item.source_name}</strong><p className="mt-1 text-slate-600">{item.evidence_summary || item.quoted_content || "-"}</p></div>)}</div> : null}</div> : null}
          </section>

          <section className="panel overflow-hidden">
            <PanelTitle title="技术溯源" status={lineage?.tech_confirm_status || "未维护"} />
            <div className="grid gap-3 p-4 md:grid-cols-2">
              {[
                ["source_system_name", "来源系统"], ["source_database_name", "来源库"], ["source_schema_name", "来源 schema"],
                ["source_table_english_name", "来源表英文名"], ["source_table_chinese_name", "来源表中文名"],
                ["source_field_english_name", "来源字段英文名"], ["source_field_chinese_name", "来源字段中文名"],
                ["tech_owner", "技术口径确认人"],
              ].map(([key, label]) => <TextInput key={key} label={label} value={lineageForm[key] || ""} onChange={(value) => setLineageForm({ ...lineageForm, [key]: value })} />)}
              <Field label="处理逻辑类型"><select className="control" value={lineageForm.processing_logic_type} onChange={(e) => setLineageForm({ ...lineageForm, processing_logic_type: e.target.value })}>{["direct", "default_value", "code_mapping", "concatenate", "calculate", "conditional", "manual_supplement", "external_data", "pending_confirmation"].map((item) => <option key={item}>{item}</option>)}</select></Field>
              <TextInput label="置信度" value={lineageForm.confidence_level || "medium"} onChange={(value) => setLineageForm({ ...lineageForm, confidence_level: value })} />
              <Field label="处理逻辑" wide><textarea className="control min-h-24" value={lineageForm.processing_logic} onChange={(e) => setLineageForm({ ...lineageForm, processing_logic: e.target.value })} /></Field>
              <Field label="备注" wide><textarea className="control min-h-20" value={lineageForm.remarks} onChange={(e) => setLineageForm({ ...lineageForm, remarks: e.target.value })} /></Field>
              <Field label="AI 草稿" wide><textarea className="control min-h-28 bg-slate-50" readOnly value={lineageForm.ai_generated_content} /></Field>
              <Field label="最终技术口径" wide><textarea className="control min-h-32" value={lineageForm.final_content} onChange={(e) => setLineageForm({ ...lineageForm, final_content: e.target.value })} /></Field>
              <Field label="待确认问题" wide><textarea className="control min-h-20" value={lineageForm.open_questions} onChange={(e) => setLineageForm({ ...lineageForm, open_questions: e.target.value })} /></Field>
            </div>
            <div className="flex flex-wrap gap-2 border-t border-line p-4">
              <button className="button-secondary" onClick={recommend}><DatabaseZap size={16} />推荐来源字段</button>
              <button className="button-secondary" disabled={!lineage || busy} onClick={() => run(() => apiPost(`/scenario-technical-lineages/${lineage!.id}/generate-draft`, {}), "AI 技术草稿已生成")}><Sparkles size={16} />AI 草稿</button>
              <button className="button-secondary" disabled={!lineage?.ai_generated_content || busy} onClick={() => run(() => apiPost(`/scenario-technical-lineages/${lineage!.id}/adopt-ai-draft`, {}), "已采用 AI 草稿")}><Check size={16} />采用草稿</button>
              <button className="button-primary" disabled={busy} onClick={saveLineage}><Save size={16} />保存</button>
              <button className="button-secondary" disabled={!lineage || busy} onClick={() => run(() => apiPost(`/scenario-technical-lineages/${lineage!.id}/confirm`, {}), "技术口径已确认")}><Check size={16} />技术确认</button>
              <button className="button-danger" disabled={!lineage || busy} onClick={() => run(() => apiPost(`/scenario-technical-lineages/${lineage!.id}/reject`, {}), "技术口径已驳回")}><X size={16} />驳回</button>
              <button className="button-secondary" disabled={!lineage} onClick={() => setShowEvidenceForm((value) => !value)}><Link2 size={16} />绑定证据</button>
            </div>
            {showEvidenceForm ? <div className="border-t border-line bg-slate-50 p-4">
              <label className="text-xs text-slate-500" htmlFor="technical-evidence">人工证据说明</label>
              <textarea className="control mt-1 min-h-20" id="technical-evidence" onChange={(event) => setEvidenceText(event.target.value)} placeholder="填写脱敏的来源依据、访谈结论或待核实说明" value={evidenceText} />
              <button className="button-primary mt-2" disabled={!evidenceText.trim() || busy} onClick={bindTechnicalEvidence}><Link2 size={16} />确认绑定</button>
              {technicalEvidences.length ? <div className="mt-3 space-y-2">{technicalEvidences.map((item) => <div className="rounded-md border border-line bg-white p-2 text-xs" key={item.id}><strong>{item.source_name}</strong><p className="mt-1 text-slate-600">{item.evidence_summary || item.quoted_content || "-"}</p></div>)}</div> : null}
            </div> : null}
          </section>
        </div>

        {(recommendations.length || knowledge.length || ragKnowledge.length || groundedAnswer) ? <section className="mt-5 grid gap-5 xl:grid-cols-2">
          <div className="panel p-4"><div className="flex flex-wrap items-center justify-between gap-2"><h2 className="text-sm font-semibold">候选来源</h2><div className="flex gap-2"><select className="control" onChange={e=>setDatasourceFilter(e.target.value)} value={datasourceFilter}><option value="">全部数据源</option>{Array.from(new Set(recommendations.map(item=>item.recommended_source_system||""))).filter(Boolean).map(value=><option key={value}>{value}</option>)}</select><select className="control" onChange={e=>setSchemaFilter(e.target.value)} value={schemaFilter}><option value="">全部 schema</option>{Array.from(new Set(recommendations.map(item=>item.recommended_schema_name||""))).filter(Boolean).map(value=><option key={value}>{value}</option>)}</select></div></div><div className="mt-3 space-y-2">{recommendations.filter(item=>(!datasourceFilter||item.recommended_source_system===datasourceFilter)&&(!schemaFilter||item.recommended_schema_name===schemaFilter)).map((item) => <div className="rounded-md border border-line p-3 text-sm" key={item.id}><div className="flex items-center justify-between gap-3"><strong>{item.recommended_source_system} / {item.recommended_database_name || "-"} / {item.recommended_schema_name}.{item.recommended_table_name}.{item.recommended_field_name}</strong><span>{Math.round(item.score * 100)}%</span></div><p className="mt-1 text-xs text-slate-500">{item.data_type||"类型待确认"} / {item.nullable===false?"非空":"可空或未知"} / profile: {item.profile_status||"未探查"} / {item.recommendation_basis || "依据待确认"}</p><p className="mt-2 text-slate-600">{item.recommend_reason}</p><p className="mt-1 text-xs text-slate-500">{item.evidence_summary}</p>{item.citation_summary_json?.length ? <div className="mt-2 rounded bg-slate-50 p-2 text-xs"><strong>知识引用</strong>{item.citation_summary_json.map(citation => <div key={citation.knowledge_unit_id}>#{citation.knowledge_unit_id} {citation.source_file_name} {citation.source_sheet_name || ""} {citation.source_cell_range || ""}</div>)}</div> : null}<div className="mt-3 flex flex-wrap gap-2"><button className="button-secondary" onClick={()=>selectCatalogCandidate(item)}><Check size={16}/>选择候选</button>{item.catalog_column_id?<button className="button-secondary" onClick={()=>showProfileHistory(item)}><Clock3 size={16}/>探查历史</button>:null}{item.catalog_column_id?<button className="button-secondary" disabled={selectedRecommendationId!==item.id} onClick={()=>profileCatalogCandidate(item)}><DatabaseZap size={16}/>执行安全探查</button>:null}{item.catalog_column_id?<button className="button-primary" disabled={selectedRecommendationId!==item.id||!profileTask||profileTask.catalog_column_id!==item.catalog_column_id||!profileTask.status.includes("completed")} onClick={()=>adoptCatalogCandidate(item)}><Check size={16}/>采用为技术来源</button>:null}</div>{profileTask?.catalog_column_id===item.catalog_column_id?<pre className="mt-3 overflow-auto rounded bg-slate-50 p-2 text-xs">{JSON.stringify(profileTask.profile_result_json,null,2)}</pre>:null}{profileHistory && profileHistory.columnId===item.catalog_column_id?<CandidateProfileHistory items={profileHistory.items}/>:null}</div>)}</div></div>
          <div className="space-y-5">
            <div className="panel p-4"><h2 className="text-sm font-semibold">带出处知识</h2><div className="mt-3 space-y-2">{ragKnowledge.map((item) => <div className="rounded-md border border-line p-3 text-sm" key={item.knowledge_unit_id}><div className="flex justify-between gap-3"><strong>{item.title || item.knowledge_type}</strong><span>{Math.round(item.rerank_score * 100)}%</span></div><p className="mt-2 text-slate-600">{item.content}</p><p className="mt-1 text-xs text-slate-500">{item.source_file_name} / {item.source_sheet_name || "-"} / {item.source_cell_range || (item.source_page_no ? `第 ${item.source_page_no} 页` : "-")}</p><div className="mt-2 flex gap-2"><button className="button-secondary" onClick={() => submitFeedback(item.knowledge_unit_id, "correct")}>正确</button><button className="button-secondary" onClick={() => submitFeedback(item.knowledge_unit_id, "partially_correct")}>部分正确</button><button className="button-danger" onClick={() => submitFeedback(item.knowledge_unit_id, "incorrect")}>错误</button></div></div>)}</div></div>
            {groundedAnswer ? <div className="panel p-4"><h2 className="text-sm font-semibold">字段解释与引用</h2><pre className="mt-3 overflow-auto whitespace-pre-wrap text-xs">{JSON.stringify(groundedAnswer, null, 2)}</pre></div> : null}
            {knowledge.length ? <div className="panel p-4"><h2 className="text-sm font-semibold">兼容历史结构化知识</h2><div className="mt-3 space-y-2">{knowledge.map((item) => <div className="rounded-md border border-line p-3 text-sm" key={item.id}><strong>{item.knowledge_type}</strong><p className="mt-2 text-slate-600">{item.business_explanation || "-"}</p><p className="mt-1 text-xs text-slate-500">{item.source_document_name} / {item.source_sheet_name} / {item.source_cell_range}</p></div>)}</div></div> : null}
          </div>
        </section> : null}
      </div>
    </main>
  );
}

function Meta({ label, value }: { label: string; value?: string | null }) { return <div><div className="text-xs text-slate-500">{label}</div><div className="mt-1 line-clamp-3 text-sm">{value || "-"}</div></div>; }
function PanelTitle({ title, status }: { title: string; status: string }) { return <div className="flex items-center justify-between border-b border-line px-4 py-3"><h2 className="font-semibold">{title}</h2><span className="rounded-md border border-line bg-slate-50 px-2 py-1 text-xs">{status}</span></div>; }
function Field({ label, wide, children }: { label: string; wide?: boolean; children: React.ReactNode }) { return <label className={wide ? "md:col-span-2" : ""}><span className="mb-1 block text-xs text-slate-500">{label}</span>{children}</label>; }
function TextInput({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) { return <Field label={label}><input className="control" onChange={(event) => onChange(event.target.value)} value={value} /></Field>; }
function CandidateProfileHistory({ items }: { items: ColumnProfileSnapshot[] }) { return <div className="mt-3 rounded bg-slate-50 p-2 text-xs">{items.length ? items.map((snapshot) => <div key={snapshot.id}>{new Date(snapshot.profile_date).toLocaleString()} · total {snapshot.total_count ?? "-"} · null rate {snapshot.null_rate ?? "-"} · distinct {snapshot.distinct_count ?? "-"}</div>) : "暂无探查历史"}</div>; }

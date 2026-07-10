"use client";

import { Check, Database, Download, FileSpreadsheet, FileUp, Play, Plus, RefreshCw, Save, Search, Upload, Wand2, X } from "lucide-react";
import { FormEvent, useEffect, useMemo, useState } from "react";

import { Section } from "@/components/Section";
import {
  FieldDraft,
  BusinessSystem,
  KnowledgeDocument,
  DataSource,
  MappingDocumentExport,
  MappingEvidence,
  MartField,
  MartTable,
  MartToYbtMapping,
  NaturalLanguageTask,
  NaturalLanguageTaskCreateResponse,
  Project,
  SqlFile,
  SourceField,
  SourceTable,
  SourceToMartMapping,
  TargetField,
  TargetTable,
  TemplateApplyResponse,
  TemplateDocument,
  TemplateUploadResponse,
  apiDelete,
  apiGet,
  apiPatch,
  apiPost,
  apiPut,
  uploadForm
} from "@/lib/api";

export default function HomePage() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [tables, setTables] = useState<TargetTable[]>([]);
  const [fields, setFields] = useState<TargetField[]>([]);
  const [documents, setDocuments] = useState<KnowledgeDocument[]>([]);
  const [sqlFiles, setSqlFiles] = useState<SqlFile[]>([]);
  const [templates, setTemplates] = useState<TemplateDocument[]>([]);
  const [datasources, setDatasources] = useState<DataSource[]>([]);
  const [tasks, setTasks] = useState<NaturalLanguageTask[]>([]);
  const [businessSystems, setBusinessSystems] = useState<BusinessSystem[]>([]);
  const [sourceTables, setSourceTables] = useState<SourceTable[]>([]);
  const [sourceFields, setSourceFields] = useState<SourceField[]>([]);
  const [martTables, setMartTables] = useState<MartTable[]>([]);
  const [martFields, setMartFields] = useState<MartField[]>([]);
  const [sourceToMartMappings, setSourceToMartMappings] = useState<SourceToMartMapping[]>([]);
  const [martToYbtMappings, setMartToYbtMappings] = useState<MartToYbtMapping[]>([]);
  const [mappingEvidence, setMappingEvidence] = useState<MappingEvidence[]>([]);
  const [exportResult, setExportResult] = useState<MappingDocumentExport | null>(null);
  const [selectedProjectId, setSelectedProjectId] = useState<number | null>(null);
  const [selectedFieldId, setSelectedFieldId] = useState<number | null>(null);
  const [selectedBusinessSystemId, setSelectedBusinessSystemId] = useState<number | null>(null);
  const [selectedSourceTableId, setSelectedSourceTableId] = useState<number | null>(null);
  const [selectedMartTableId, setSelectedMartTableId] = useState<number | null>(null);
  const [selectedMartFieldId, setSelectedMartFieldId] = useState<number | null>(null);
  const [draft, setDraft] = useState<FieldDraft | null>(null);
  const [templateUpload, setTemplateUpload] = useState<TemplateUploadResponse | null>(null);
  const [templateApply, setTemplateApply] = useState<TemplateApplyResponse | null>(null);
  const [taskCreateResult, setTaskCreateResult] = useState<NaturalLanguageTaskCreateResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  const selectedProject = projects.find((project) => project.id === selectedProjectId) || null;
  const selectedField = fields.find((field) => field.id === selectedFieldId) || null;
  const selectedBusinessSystem = businessSystems.find((system) => system.id === selectedBusinessSystemId) || null;
  const selectedSourceTable = sourceTables.find((table) => table.id === selectedSourceTableId) || null;
  const selectedMartTable = martTables.find((table) => table.id === selectedMartTableId) || null;
  const selectedMartField = martFields.find((field) => field.id === selectedMartFieldId) || null;

  const tableOptions = useMemo(() => tables.map((table) => ({ value: table.id, label: `${table.table_code} ${table.table_name}` })), [tables]);
  const martFieldOptions = useMemo(
    () => martFields.map((field) => {
      const table = martTables.find((item) => item.id === field.mart_table_id);
      return { value: field.id, label: `${table?.table_code || "mart"}.${field.field_code} ${field.field_name}` };
    }),
    [martFields, martTables]
  );

  useEffect(() => {
    void refreshProjects();
  }, []);

  useEffect(() => {
    if (!selectedProjectId) {
      return;
    }
    void refreshWorkspace(selectedProjectId);
  }, [selectedProjectId]);

  useEffect(() => {
    if (!selectedFieldId) {
      setDraft(null);
      setMartToYbtMappings([]);
      return;
    }
    void refreshDraft(selectedFieldId);
    void refreshMartToYbtMappings(selectedFieldId);
  }, [selectedFieldId]);

  useEffect(() => {
    if (!selectedMartFieldId) {
      setSourceToMartMappings([]);
      return;
    }
    void refreshSourceToMartMappings(selectedMartFieldId);
  }, [selectedMartFieldId]);

  async function refreshProjects() {
    const data = await apiGet<Project[]>("/projects");
    setProjects(data);
    if (!selectedProjectId && data[0]) {
      setSelectedProjectId(data[0].id);
    }
  }

  async function refreshWorkspace(projectId: number) {
    const [nextTables, nextFields, nextDocuments, nextSqlFiles, nextTemplates, nextDatasources, nextTasks, nextBusinessSystems, nextMartTables] = await Promise.all([
      apiGet<TargetTable[]>(`/target-tables?project_id=${projectId}`),
      apiGet<TargetField[]>(`/fields?project_id=${projectId}`),
      apiGet<KnowledgeDocument[]>(`/documents?project_id=${projectId}`),
      apiGet<SqlFile[]>(`/sql-files?project_id=${projectId}`),
      apiGet<TemplateDocument[]>(`/projects/${projectId}/templates`),
      apiGet<DataSource[]>(`/projects/${projectId}/datasources`),
      apiGet<NaturalLanguageTask[]>(`/projects/${projectId}/nl-tasks`),
      apiGet<BusinessSystem[]>(`/projects/${projectId}/business-systems`),
      apiGet<MartTable[]>(`/projects/${projectId}/mart-tables`)
    ]);
    const nextSourceTables = (await Promise.all(nextBusinessSystems.map((system) => apiGet<SourceTable[]>(`/business-systems/${system.id}/source-tables`)))).flat();
    const nextSourceFields = (await Promise.all(nextSourceTables.map((table) => apiGet<SourceField[]>(`/source-tables/${table.id}/source-fields`)))).flat();
    const nextMartFields = (await Promise.all(nextMartTables.map((table) => apiGet<MartField[]>(`/mart-tables/${table.id}/mart-fields`)))).flat();
    setTables(nextTables);
    setFields(nextFields);
    setDocuments(nextDocuments);
    setSqlFiles(nextSqlFiles);
    setTemplates(nextTemplates);
    setDatasources(nextDatasources);
    setTasks(nextTasks);
    setBusinessSystems(nextBusinessSystems);
    setSourceTables(nextSourceTables);
    setSourceFields(nextSourceFields);
    setMartTables(nextMartTables);
    setMartFields(nextMartFields);
    if (!selectedBusinessSystemId && nextBusinessSystems[0]) {
      setSelectedBusinessSystemId(nextBusinessSystems[0].id);
    }
    if (!selectedSourceTableId && nextSourceTables[0]) {
      setSelectedSourceTableId(nextSourceTables[0].id);
    }
    if (!selectedMartTableId && nextMartTables[0]) {
      setSelectedMartTableId(nextMartTables[0].id);
    }
    if (!selectedMartFieldId && nextMartFields[0]) {
      setSelectedMartFieldId(nextMartFields[0].id);
    }
    if (!selectedFieldId && nextFields[0]) {
      setSelectedFieldId(nextFields[0].id);
    }
  }

  async function refreshDraft(fieldId: number) {
    const data = await apiGet<FieldDraft | null>(`/fields/${fieldId}/drafts/latest`);
    setDraft(data);
  }

  async function refreshSourceToMartMappings(martFieldId: number) {
    const data = await apiGet<SourceToMartMapping[]>(`/mart-fields/${martFieldId}/source-to-mart-mappings`);
    setSourceToMartMappings(data);
    await refreshMappingEvidence(data, martToYbtMappings);
  }

  async function refreshMartToYbtMappings(fieldId: number) {
    const data = await apiGet<MartToYbtMapping[]>(`/target-fields/${fieldId}/mart-to-ybt-mappings`);
    setMartToYbtMappings(data);
    await refreshMappingEvidence(sourceToMartMappings, data);
  }

  async function refreshMappingEvidence(sourceMappings = sourceToMartMappings, ybtMappings = martToYbtMappings) {
    const evidenceGroups = await Promise.all([
      ...sourceMappings.map((mapping) => apiGet<MappingEvidence[]>(`/mappings/source_to_mart/${mapping.id}/evidence`)),
      ...ybtMappings.map((mapping) => apiGet<MappingEvidence[]>(`/mappings/mart_to_ybt/${mapping.id}/evidence`))
    ]);
    setMappingEvidence(evidenceGroups.flat());
  }

  async function submitProject(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const created = await apiPost<Project>("/projects", {
      name: textValue(form, "name"),
      bank_name: textValue(form, "bank_name"),
      description: textValue(form, "description")
    });
    event.currentTarget.reset();
    setSelectedProjectId(created.id);
    await refreshProjects();
  }

  async function submitTable(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedProjectId) {
      return;
    }
    const form = new FormData(event.currentTarget);
    await apiPost<TargetTable>("/target-tables", {
      project_id: selectedProjectId,
      table_code: textValue(form, "table_code"),
      table_name: textValue(form, "table_name"),
      description: textValue(form, "description")
    });
    event.currentTarget.reset();
    await refreshWorkspace(selectedProjectId);
  }

  async function submitField(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedProjectId) {
      return;
    }
    const form = new FormData(event.currentTarget);
    const created = await apiPost<TargetField>("/fields", {
      project_id: selectedProjectId,
      target_table_id: Number(textValue(form, "target_table_id")),
      field_code: textValue(form, "field_code"),
      field_name: textValue(form, "field_name"),
      field_type: textValue(form, "field_type"),
      required_flag: form.get("required_flag") === "on",
      field_definition: textValue(form, "field_definition"),
      regulatory_description: textValue(form, "regulatory_description")
    });
    event.currentTarget.reset();
    setSelectedFieldId(created.id);
    await refreshWorkspace(selectedProjectId);
  }

  async function uploadDocument(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedProjectId) {
      return;
    }
    const form = new FormData(event.currentTarget);
    form.set("project_id", String(selectedProjectId));
    await uploadForm<KnowledgeDocument>("/documents/upload", form);
    event.currentTarget.reset();
    await refreshWorkspace(selectedProjectId);
  }

  async function uploadSql(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedProjectId) {
      return;
    }
    const form = new FormData(event.currentTarget);
    form.set("project_id", String(selectedProjectId));
    await uploadForm<SqlFile>("/sql-files/upload", form);
    event.currentTarget.reset();
    await refreshWorkspace(selectedProjectId);
  }

  async function uploadTemplate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedProjectId) {
      return;
    }
    const form = new FormData(event.currentTarget);
    form.set("project_id", String(selectedProjectId));
    const result = await uploadForm<TemplateUploadResponse>("/templates/upload", form);
    setTemplateUpload(result);
    setTemplateApply(null);
    event.currentTarget.reset();
    await refreshWorkspace(selectedProjectId);
  }

  async function applyUploadedTemplate() {
    if (!templateUpload || !selectedProjectId) {
      return;
    }
    const result = await apiPost<TemplateApplyResponse>(`/templates/${templateUpload.template_id}/apply`, {});
    setTemplateApply(result);
    await refreshWorkspace(selectedProjectId);
  }

  async function submitDatasource(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedProjectId) {
      return;
    }
    const form = new FormData(event.currentTarget);
    await apiPost<DataSource>(`/projects/${selectedProjectId}/datasources`, {
      name: textValue(form, "name"),
      display_name: textValue(form, "display_name"),
      db_type: textValue(form, "db_type"),
      host: textValue(form, "host") || null,
      port: textValue(form, "port") ? Number(textValue(form, "port")) : null,
      database_name: textValue(form, "database_name"),
      schema_name: textValue(form, "schema_name"),
      username: textValue(form, "username"),
      password: textValue(form, "password") || null,
      readonly_flag: true,
      enabled: true
    });
    event.currentTarget.reset();
    await refreshWorkspace(selectedProjectId);
  }

  async function testDatasource(datasourceId: number) {
    if (!selectedProjectId) {
      return;
    }
    await apiPost(`/datasources/${datasourceId}/test`, {});
    await refreshWorkspace(selectedProjectId);
  }

  async function deleteDatasource(datasourceId: number) {
    if (!selectedProjectId) {
      return;
    }
    await apiDelete(`/datasources/${datasourceId}`);
    await refreshWorkspace(selectedProjectId);
  }

  async function submitNaturalLanguageTask(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedProjectId) {
      return;
    }
    const form = new FormData(event.currentTarget);
    const result = await apiPost<NaturalLanguageTaskCreateResponse>("/nl-tasks", {
      project_id: selectedProjectId,
      text: textValue(form, "text")
    });
    setTaskCreateResult(result);
    event.currentTarget.reset();
    await refreshWorkspace(selectedProjectId);
  }

  async function runNaturalLanguageTask(taskId: number) {
    if (!selectedProjectId) {
      return;
    }
    await apiPost<NaturalLanguageTask>(`/nl-tasks/${taskId}/run`, {});
    await refreshWorkspace(selectedProjectId);
  }

  async function submitBusinessSystem(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedProjectId) {
      return;
    }
    const form = new FormData(event.currentTarget);
    const created = await apiPost<BusinessSystem>(`/projects/${selectedProjectId}/business-systems`, {
      system_code: textValue(form, "system_code"),
      system_name: textValue(form, "system_name"),
      owner_department: textValue(form, "owner_department"),
      description: textValue(form, "description"),
      enabled: form.get("enabled") === "on"
    });
    event.currentTarget.reset();
    setSelectedBusinessSystemId(created.id);
    await refreshWorkspace(selectedProjectId);
  }

  async function submitSourceTable(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedProjectId || !selectedBusinessSystemId) {
      return;
    }
    const form = new FormData(event.currentTarget);
    const created = await apiPost<SourceTable>(`/business-systems/${selectedBusinessSystemId}/source-tables`, {
      table_code: textValue(form, "table_code"),
      table_name: textValue(form, "table_name"),
      table_comment: textValue(form, "table_comment"),
      datasource_id: numericOrNull(form, "datasource_id"),
      schema_name: textValue(form, "schema_name"),
      physical_table_name: textValue(form, "physical_table_name"),
      description: textValue(form, "description")
    });
    event.currentTarget.reset();
    setSelectedSourceTableId(created.id);
    await refreshWorkspace(selectedProjectId);
  }

  async function submitSourceField(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedProjectId || !selectedSourceTableId) {
      return;
    }
    const form = new FormData(event.currentTarget);
    await apiPost<SourceField>(`/source-tables/${selectedSourceTableId}/source-fields`, {
      field_code: textValue(form, "field_code"),
      field_name: textValue(form, "field_name"),
      field_type: textValue(form, "field_type"),
      field_comment: textValue(form, "field_comment"),
      physical_column_name: textValue(form, "physical_column_name"),
      description: textValue(form, "description")
    });
    event.currentTarget.reset();
    await refreshWorkspace(selectedProjectId);
  }

  async function submitMartTable(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedProjectId) {
      return;
    }
    const form = new FormData(event.currentTarget);
    const created = await apiPost<MartTable>(`/projects/${selectedProjectId}/mart-tables`, {
      table_code: textValue(form, "table_code"),
      table_name: textValue(form, "table_name"),
      subject_area: textValue(form, "subject_area"),
      table_comment: textValue(form, "table_comment"),
      datasource_id: numericOrNull(form, "datasource_id"),
      schema_name: textValue(form, "schema_name"),
      physical_table_name: textValue(form, "physical_table_name"),
      is_existing: form.get("is_existing") === "on",
      description: textValue(form, "description")
    });
    event.currentTarget.reset();
    setSelectedMartTableId(created.id);
    await refreshWorkspace(selectedProjectId);
  }

  async function submitMartField(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedProjectId || !selectedMartTableId) {
      return;
    }
    const form = new FormData(event.currentTarget);
    const created = await apiPost<MartField>(`/mart-tables/${selectedMartTableId}/mart-fields`, {
      field_code: textValue(form, "field_code"),
      field_name: textValue(form, "field_name"),
      field_type: textValue(form, "field_type"),
      field_comment: textValue(form, "field_comment"),
      physical_column_name: textValue(form, "physical_column_name"),
      is_existing: form.get("is_existing") === "on",
      description: textValue(form, "description")
    });
    event.currentTarget.reset();
    setSelectedMartFieldId(created.id);
    await refreshWorkspace(selectedProjectId);
    await refreshSourceToMartMappings(created.id);
  }

  async function submitSourceToMartMapping(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedMartFieldId) {
      return;
    }
    const form = new FormData(event.currentTarget);
    await apiPost<SourceToMartMapping>(`/mart-fields/${selectedMartFieldId}/source-to-mart-mappings`, {
      mapping_name: textValue(form, "mapping_name"),
      source_system_summary: textValue(form, "source_system_summary"),
      source_tables_summary: textValue(form, "source_tables_summary"),
      source_fields_summary: textValue(form, "source_fields_summary"),
      business_rule: textValue(form, "business_rule"),
      filter_condition: textValue(form, "filter_condition")
    });
    event.currentTarget.reset();
    await refreshSourceToMartMappings(selectedMartFieldId);
  }

  async function submitMartToYbtMapping(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedFieldId) {
      return;
    }
    const form = new FormData(event.currentTarget);
    const formMartFieldId = numericOrNull(form, "mart_field_id");
    const formMartField = martFields.find((field) => field.id === formMartFieldId) || null;
    const formMartTable = formMartField ? martTables.find((table) => table.id === formMartField.mart_table_id) || null : null;
    await apiPost<MartToYbtMapping>(`/target-fields/${selectedFieldId}/mart-to-ybt-mappings`, {
      mart_field_id: formMartFieldId,
      mapping_name: textValue(form, "mapping_name"),
      mart_table_summary: formMartTable?.table_code || textValue(form, "mart_table_summary"),
      mart_field_summary: formMartField?.field_code || textValue(form, "mart_field_summary"),
      business_rule: textValue(form, "business_rule"),
      reporting_condition: textValue(form, "reporting_condition")
    });
    event.currentTarget.reset();
    await refreshMartToYbtMappings(selectedFieldId);
  }

  async function generateSourceToMart(mappingId: number) {
    if (!selectedMartFieldId) {
      return;
    }
    await apiPost<SourceToMartMapping>(`/source-to-mart-mappings/${mappingId}/generate-draft`, {});
    await refreshSourceToMartMappings(selectedMartFieldId);
  }

  async function generateMartToYbt(mappingId: number) {
    if (!selectedFieldId) {
      return;
    }
    await apiPost<MartToYbtMapping>(`/mart-to-ybt-mappings/${mappingId}/generate-draft`, {});
    await refreshMartToYbtMappings(selectedFieldId);
  }

  async function saveSourceToMartFinal(mapping: SourceToMartMapping, content: string) {
    if (!selectedMartFieldId) {
      return;
    }
    await apiPut<SourceToMartMapping>(`/source-to-mart-mappings/${mapping.id}`, { final_content: content });
    await refreshSourceToMartMappings(selectedMartFieldId);
  }

  async function saveMartToYbtFinal(mapping: MartToYbtMapping, content: string) {
    if (!selectedFieldId) {
      return;
    }
    await apiPut<MartToYbtMapping>(`/mart-to-ybt-mappings/${mapping.id}`, { final_content: content });
    await refreshMartToYbtMappings(selectedFieldId);
  }

  async function reviewSourceToMart(mappingId: number, action: "approve" | "reject") {
    if (!selectedMartFieldId) {
      return;
    }
    await apiPost<SourceToMartMapping>(`/source-to-mart-mappings/${mappingId}/${action}`, { reviewed_by: "当前用户" });
    await refreshSourceToMartMappings(selectedMartFieldId);
  }

  async function reviewMartToYbt(mappingId: number, action: "approve" | "reject") {
    if (!selectedFieldId) {
      return;
    }
    await apiPost<MartToYbtMapping>(`/mart-to-ybt-mappings/${mappingId}/${action}`, { reviewed_by: "当前用户" });
    await refreshMartToYbtMappings(selectedFieldId);
  }

  async function saveSourceToMartVersion(mappingId: number) {
    if (!selectedMartFieldId) {
      return;
    }
    await apiPost(`/source-to-mart-mappings/${mappingId}/save-version`, { change_note: "前端手动保存版本", created_by: "当前用户" });
    await refreshSourceToMartMappings(selectedMartFieldId);
  }

  async function saveMartToYbtVersion(mappingId: number) {
    if (!selectedFieldId) {
      return;
    }
    await apiPost(`/mart-to-ybt-mappings/${mappingId}/save-version`, { change_note: "前端手动保存版本", created_by: "当前用户" });
    await refreshMartToYbtMappings(selectedFieldId);
  }

  async function submitManualEvidence(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const [mappingType, mappingIdText] = textValue(form, "mapping_ref").split(":");
    const mappingId = Number(mappingIdText);
    if (!mappingType || !mappingId) {
      return;
    }
    await apiPost<MappingEvidence>(`/mappings/${mappingType}/${mappingId}/evidence`, {
      evidence_type: "manual_note",
      source_name: textValue(form, "source_name") || "人工备注",
      location_text: textValue(form, "location_text"),
      quoted_content: textValue(form, "quoted_content"),
      evidence_summary: textValue(form, "evidence_summary")
    });
    event.currentTarget.reset();
    await refreshMappingEvidence();
  }

  async function exportMapping(scope: "project" | "table" | "field") {
    if (scope === "project" && selectedProjectId) {
      setExportResult(await apiGet<MappingDocumentExport>(`/projects/${selectedProjectId}/export/mapping-document?format=markdown`));
    }
    if (scope === "table" && selectedField) {
      setExportResult(await apiGet<MappingDocumentExport>(`/target-tables/${selectedField.target_table_id}/export/mapping-document?format=markdown`));
    }
    if (scope === "field" && selectedFieldId) {
      setExportResult(await apiGet<MappingDocumentExport>(`/target-fields/${selectedFieldId}/export/mapping-document?format=markdown`));
    }
  }

  async function generateMapping() {
    if (!selectedFieldId) {
      return;
    }
    setBusy(true);
    setMessage("生成中");
    try {
      const response = await apiPost<{ draft: FieldDraft }>(`/fields/${selectedFieldId}/generate-mapping`, {});
      setDraft(response.draft);
      setMessage("已生成");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "生成失败");
    } finally {
      setBusy(false);
    }
  }

  async function reviewDraft(reviewStatus: "approved" | "rejected" | "revised") {
    if (!draft) {
      return;
    }
    const updated = await apiPatch<FieldDraft>(`/fields/drafts/${draft.id}/review`, {
      review_status: reviewStatus,
      final_content: draft.final_content
    });
    setDraft(updated);
  }

  return (
    <main className="min-h-screen">
      <header className="border-b border-line bg-white">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-6 py-4">
          <div>
            <h1 className="text-xl font-semibold">银行一表通字段级口径智能辅助平台</h1>
            <p className="mt-1 text-sm text-slate-600">{selectedProject ? `${selectedProject.bank_name || "未填写银行"} / ${selectedProject.name}` : "MVP 工作台"}</p>
          </div>
          <button className="button-secondary" onClick={() => selectedProjectId && refreshWorkspace(selectedProjectId)}>
            <RefreshCw size={16} />
            刷新
          </button>
        </div>
      </header>

      <div className="mx-auto grid max-w-7xl grid-cols-1 gap-4 px-6 py-5 xl:grid-cols-[360px_1fr]">
        <aside className="space-y-4">
          <Section title="项目">
            <form className="space-y-3" onSubmit={submitProject}>
              <input className="control" name="name" placeholder="项目名称" required />
              <input className="control" name="bank_name" placeholder="银行名称" />
              <textarea className="control min-h-20" name="description" placeholder="项目描述" />
              <button className="button-primary w-full" type="submit">
                <Plus size={16} />
                新建项目
              </button>
            </form>
            <div className="mt-4 space-y-2">
              {projects.map((project) => (
                <button
                  key={project.id}
                  className={`w-full rounded-md border px-3 py-2 text-left text-sm ${project.id === selectedProjectId ? "border-pine bg-pine/10" : "border-line bg-white"}`}
                  onClick={() => setSelectedProjectId(project.id)}
                >
                  <div className="font-medium">{project.name}</div>
                  <div className="text-slate-500">{project.bank_name || "未填写银行"}</div>
                </button>
              ))}
            </div>
          </Section>

          <Section title="目标表">
            <form className="space-y-3" onSubmit={submitTable}>
              <input className="control" name="table_code" placeholder="表代码" required />
              <input className="control" name="table_name" placeholder="表名称" required />
              <textarea className="control min-h-16" name="description" placeholder="表说明" />
              <button className="button-primary w-full" disabled={!selectedProjectId} type="submit">
                <Plus size={16} />
                新建目标表
              </button>
            </form>
            <div className="mt-4 space-y-2">
              {tables.map((table) => (
                <div key={table.id} className="rounded-md border border-line bg-mist px-3 py-2 text-sm">
                  <div className="font-medium">{table.table_code}</div>
                  <div className="text-slate-600">{table.table_name}</div>
                </div>
              ))}
            </div>
          </Section>

          <Section title="知识库">
            <form className="space-y-3" onSubmit={uploadDocument}>
              <select className="control" name="source_type" defaultValue="历史需求文档">
                <option>历史需求文档</option>
                <option>EAST口径</option>
                <option>数据字典</option>
                <option>监管制度</option>
                <option>开发说明</option>
              </select>
              <input className="control" name="file" type="file" accept=".txt,.md,.sql" required />
              <button className="button-secondary w-full" disabled={!selectedProjectId} type="submit">
                <Upload size={16} />
                上传文档
              </button>
            </form>
            <div className="mt-4 space-y-2">
              {documents.map((document) => (
                <div key={document.id} className="rounded-md border border-line bg-white px-3 py-2 text-sm">
                  <div className="font-medium">{document.file_name}</div>
                  <div className="text-slate-500">{document.source_type}</div>
                </div>
              ))}
            </div>
          </Section>

          <Section title="Excel 模板">
            <form className="space-y-3" onSubmit={uploadTemplate}>
              <input className="control" name="file" type="file" accept=".xlsx" required />
              <button className="button-secondary w-full" disabled={!selectedProjectId} type="submit">
                <FileSpreadsheet size={16} />
                上传模板
              </button>
            </form>
            {templateUpload ? (
              <div className="mt-4 rounded-md border border-line bg-white p-3 text-sm">
                <div className="font-medium">{templateUpload.file_name}</div>
                <div className="mt-1 text-slate-600">
                  {templateUpload.sheet_count} 个 sheet / {templateUpload.table_count} 张表 / {templateUpload.field_count} 个字段
                </div>
                <div className="mt-2 space-y-1">
                  {templateUpload.preview.map((item) => (
                    <div key={item.sheet_name} className="text-xs text-slate-600">
                      {item.sheet_name}: {item.table_code || "-"} {item.table_name || "-"} / {item.field_count} 字段
                    </div>
                  ))}
                </div>
                {templateUpload.warnings.length ? <ListBlock title="解析提示" values={templateUpload.warnings} /> : null}
                <button className="button-primary mt-3 w-full" onClick={applyUploadedTemplate} type="button">
                  <Check size={16} />
                  提交并生成目标表字段
                </button>
              </div>
            ) : null}
            {templateApply ? (
              <div className="mt-3 rounded-md border border-pine/30 bg-pine/10 px-3 py-2 text-sm text-pine">
                已创建 {templateApply.created_tables} 张表、{templateApply.created_fields} 个字段；更新 {templateApply.updated_tables} 张表、{templateApply.updated_fields} 个字段；跳过 {templateApply.skipped_rows} 行。
              </div>
            ) : null}
            <div className="mt-4 space-y-2">
              {templates.map((template) => (
                <div key={template.id} className="rounded-md border border-line bg-white px-3 py-2 text-sm">
                  <div className="font-medium">{template.file_name}</div>
                  <div className="text-slate-500">{template.parse_status}</div>
                </div>
              ))}
            </div>
          </Section>
        </aside>

        <section className="space-y-4">
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <Section title="SQL 数据源">
              <form className="grid grid-cols-1 gap-3 md:grid-cols-2" onSubmit={submitDatasource}>
                <input className="control" name="name" placeholder="数据源名称，例如 ecif_query" required />
                <input className="control" name="display_name" placeholder="显示名称" />
                <select className="control" name="db_type" defaultValue="sqlite">
                  <option value="sqlite">sqlite</option>
                  <option value="postgresql">postgresql</option>
                  <option value="mysql">mysql 预留</option>
                  <option value="oracle">oracle 预留</option>
                  <option value="db2">db2 预留</option>
                  <option value="hive">hive 预留</option>
                </select>
                <input className="control" name="database_name" placeholder="数据库名或 SQLite 文件路径" />
                <input className="control" name="host" placeholder="host" />
                <input className="control" name="port" placeholder="port" />
                <input className="control" name="schema_name" placeholder="schema" />
                <input className="control" name="username" placeholder="用户名" />
                <input className="control md:col-span-2" name="password" placeholder="密码，留空则不配置" type="password" />
                <button className="button-primary md:col-span-2" disabled={!selectedProjectId} type="submit">
                  <Database size={16} />
                  新增数据源
                </button>
              </form>
              <p className="mt-3 text-xs text-slate-500">数据源名称用于自然语言任务引用，例如：使用 ecif_query 查询 ecif_customer 表 cert_type 字段的空值率。</p>
              <div className="mt-4 space-y-2">
                {datasources.map((datasource) => (
                  <div key={datasource.id} className="rounded-md border border-line bg-white p-3 text-sm">
                    <div className="flex items-center justify-between gap-2">
                      <div>
                        <div className="font-medium">{datasource.name}</div>
                        <div className="text-slate-500">{datasource.display_name || datasource.db_type} / {datasource.database_name || "-"}</div>
                      </div>
                      <Badge label={datasource.last_test_status || "未测试"} tone={datasource.last_test_status === "success" ? "green" : datasource.last_test_status === "failed" ? "red" : "slate"} />
                    </div>
                    <div className="mt-3 flex flex-wrap gap-2">
                      <button className="button-secondary" onClick={() => testDatasource(datasource.id)} type="button">测试连接</button>
                      <button className="button-secondary" onClick={() => deleteDatasource(datasource.id)} type="button">删除</button>
                    </div>
                  </div>
                ))}
              </div>
            </Section>

            <Section title="自然语言任务">
              <form className="space-y-3" onSubmit={submitNaturalLanguageTask}>
                <textarea className="control min-h-24" name="text" placeholder="使用 ecif_query 查询 ecif_customer 表 cert_type 字段的空值率和枚举分布" required />
                <button className="button-primary w-full" disabled={!selectedProjectId} type="submit">
                  <Plus size={16} />
                  提交任务
                </button>
              </form>
              <div className="mt-3 flex flex-wrap gap-2">
                {datasources.map((datasource) => <Badge key={datasource.id} label={datasource.name} tone="slate" />)}
              </div>
              {taskCreateResult ? (
                <div className="mt-4 rounded-md border border-line bg-white p-3 text-sm">
                  <div>{taskCreateResult.message}</div>
                  {taskCreateResult.available_datasources.length ? <ListBlock title="可用数据源" values={taskCreateResult.available_datasources} /> : null}
                </div>
              ) : null}
              <div className="mt-4 space-y-3">
                {tasks.map((task) => (
                  <div key={task.id} className="rounded-md border border-line bg-white p-3 text-sm">
                    <div className="flex items-start justify-between gap-2">
                      <div>
                        <div className="font-medium">{task.raw_text}</div>
                        <div className="mt-1 text-slate-500">
                          {task.datasource_name || "-"} / {task.extracted_table_name || "-"} / {task.extracted_field_name || "-"}
                        </div>
                      </div>
                      <Badge label={task.status} tone={task.status === "completed" ? "green" : task.status === "failed" ? "red" : "gold"} />
                    </div>
                    {task.status === "parsed" ? (
                      <button className="button-secondary mt-3" onClick={() => runNaturalLanguageTask(task.id)} type="button">
                        <Play size={16} />
                        执行安全查询
                      </button>
                    ) : null}
                    {task.generated_sql_json.length ? <SqlList items={task.generated_sql_json} /> : null}
                    {Object.keys(task.result_summary_json).length ? (
                      <pre className="mt-3 max-h-52 overflow-auto whitespace-pre-wrap rounded-md bg-mist p-3 text-xs">{JSON.stringify(task.result_summary_json, null, 2)}</pre>
                    ) : null}
                    {task.error_message ? <p className="mt-2 text-coral">{task.error_message}</p> : null}
                  </div>
                ))}
              </div>
            </Section>
          </div>

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <Section title="业务系统来源层">
              <form className="grid grid-cols-1 gap-3 md:grid-cols-2" onSubmit={submitBusinessSystem}>
                <input className="control" name="system_code" placeholder="系统代码，例如 ECIF" required />
                <input className="control" name="system_name" placeholder="系统名称" required />
                <input className="control" name="owner_department" placeholder="所属部门" />
                <label className="flex items-center gap-2 rounded-md border border-line bg-white px-3 py-2 text-sm">
                  <input defaultChecked name="enabled" type="checkbox" />
                  启用
                </label>
                <textarea className="control min-h-16 md:col-span-2" name="description" placeholder="系统说明" />
                <button className="button-primary md:col-span-2" disabled={!selectedProjectId} type="submit">
                  <Plus size={16} />
                  新增业务系统
                </button>
              </form>

              <div className="mt-4 grid grid-cols-1 gap-2 md:grid-cols-2">
                {businessSystems.map((system) => (
                  <button
                    key={system.id}
                    className={`rounded-md border px-3 py-2 text-left text-sm ${system.id === selectedBusinessSystemId ? "border-pine bg-pine/10" : "border-line bg-white"}`}
                    onClick={() => setSelectedBusinessSystemId(system.id)}
                    type="button"
                  >
                    <div className="font-medium">{system.system_code}</div>
                    <div className="text-slate-600">{system.system_name}</div>
                  </button>
                ))}
              </div>

              <form className="mt-4 grid grid-cols-1 gap-3 md:grid-cols-2" onSubmit={submitSourceTable}>
                <input className="control" name="table_code" placeholder="源表代码，例如 ecif_customer" required />
                <input className="control" name="table_name" placeholder="源表名称" required />
                <select className="control" name="datasource_id" defaultValue="">
                  <option value="">关联数据源，可选</option>
                  {datasources.map((datasource) => (
                    <option key={datasource.id} value={datasource.id}>
                      {datasource.name}
                    </option>
                  ))}
                </select>
                <input className="control" name="physical_table_name" placeholder="物理表名，可空" />
                <input className="control" name="schema_name" placeholder="schema，可空" />
                <input className="control" name="table_comment" placeholder="表说明" />
                <textarea className="control min-h-16 md:col-span-2" name="description" placeholder="补充说明" />
                <button className="button-secondary md:col-span-2" disabled={!selectedBusinessSystem} type="submit">
                  <Plus size={16} />
                  新增源表
                </button>
              </form>

              <div className="mt-4 grid grid-cols-1 gap-2 md:grid-cols-2">
                {sourceTables.map((table) => (
                  <button
                    key={table.id}
                    className={`rounded-md border px-3 py-2 text-left text-sm ${table.id === selectedSourceTableId ? "border-pine bg-pine/10" : "border-line bg-white"}`}
                    onClick={() => setSelectedSourceTableId(table.id)}
                    type="button"
                  >
                    <div className="font-medium">{table.table_code}</div>
                    <div className="text-slate-600">{table.table_name}</div>
                  </button>
                ))}
              </div>

              <form className="mt-4 grid grid-cols-1 gap-3 md:grid-cols-2" onSubmit={submitSourceField}>
                <input className="control" name="field_code" placeholder="源字段代码，例如 cert_type" required />
                <input className="control" name="field_name" placeholder="源字段名称" required />
                <input className="control" name="field_type" placeholder="字段类型" />
                <input className="control" name="physical_column_name" placeholder="物理字段名，可空" />
                <textarea className="control min-h-16 md:col-span-2" name="field_comment" placeholder="字段说明" />
                <button className="button-secondary md:col-span-2" disabled={!selectedSourceTable} type="submit">
                  <Plus size={16} />
                  新增源字段
                </button>
              </form>

              <div className="mt-4 grid grid-cols-1 gap-2 md:grid-cols-3">
                {sourceFields.map((field) => {
                  const table = sourceTables.find((item) => item.id === field.source_table_id);
                  return (
                    <div key={field.id} className="rounded-md border border-line bg-white px-3 py-2 text-sm">
                      <div className="font-medium">{table?.table_code || "-"} . {field.field_code}</div>
                      <div className="text-slate-600">{field.field_name}</div>
                    </div>
                  );
                })}
              </div>
            </Section>

            <Section title="监管集市层">
              <form className="grid grid-cols-1 gap-3 md:grid-cols-2" onSubmit={submitMartTable}>
                <input className="control" name="table_code" placeholder="集市表代码，例如 mart_customer" required />
                <input className="control" name="table_name" placeholder="集市表名称" required />
                <input className="control" name="subject_area" placeholder="主题域，例如 客户" />
                <select className="control" name="datasource_id" defaultValue="">
                  <option value="">关联集市数据源，可选</option>
                  {datasources.map((datasource) => (
                    <option key={datasource.id} value={datasource.id}>
                      {datasource.name}
                    </option>
                  ))}
                </select>
                <input className="control" name="physical_table_name" placeholder="物理表名，可空" />
                <input className="control" name="schema_name" placeholder="schema，可空" />
                <label className="flex items-center gap-2 rounded-md border border-line bg-white px-3 py-2 text-sm">
                  <input name="is_existing" type="checkbox" />
                  已有表
                </label>
                <input className="control" name="table_comment" placeholder="表说明" />
                <textarea className="control min-h-16 md:col-span-2" name="description" placeholder="设计说明" />
                <button className="button-primary md:col-span-2" disabled={!selectedProjectId} type="submit">
                  <Plus size={16} />
                  新增监管集市表
                </button>
              </form>

              <div className="mt-4 grid grid-cols-1 gap-2 md:grid-cols-2">
                {martTables.map((table) => (
                  <button
                    key={table.id}
                    className={`rounded-md border px-3 py-2 text-left text-sm ${table.id === selectedMartTableId ? "border-pine bg-pine/10" : "border-line bg-white"}`}
                    onClick={() => setSelectedMartTableId(table.id)}
                    type="button"
                  >
                    <div className="font-medium">{table.table_code}</div>
                    <div className="text-slate-600">{table.table_name}</div>
                  </button>
                ))}
              </div>

              <form className="mt-4 grid grid-cols-1 gap-3 md:grid-cols-2" onSubmit={submitMartField}>
                <input className="control" name="field_code" placeholder="集市字段代码，例如 cert_type" required />
                <input className="control" name="field_name" placeholder="集市字段名称" required />
                <input className="control" name="field_type" placeholder="字段类型" />
                <input className="control" name="physical_column_name" placeholder="物理字段名，可空" />
                <label className="flex items-center gap-2 rounded-md border border-line bg-white px-3 py-2 text-sm">
                  <input name="is_existing" type="checkbox" />
                  已有字段
                </label>
                <textarea className="control min-h-16 md:col-span-2" name="field_comment" placeholder="字段说明" />
                <button className="button-secondary md:col-span-2" disabled={!selectedMartTable} type="submit">
                  <Plus size={16} />
                  新增集市字段
                </button>
              </form>

              <div className="mt-4 grid grid-cols-1 gap-2 md:grid-cols-3">
                {martFields.map((field) => {
                  const table = martTables.find((item) => item.id === field.mart_table_id);
                  return (
                    <button
                      key={field.id}
                      className={`rounded-md border px-3 py-2 text-left text-sm ${field.id === selectedMartFieldId ? "border-pine bg-pine/10" : "border-line bg-white"}`}
                      onClick={() => setSelectedMartFieldId(field.id)}
                      type="button"
                    >
                      <div className="font-medium">{table?.table_code || "-"} . {field.field_code}</div>
                      <div className="text-slate-600">{field.field_name}</div>
                    </button>
                  );
                })}
              </div>
            </Section>
          </div>

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1fr_420px]">
            <Section title="目标字段">
              <form className="grid grid-cols-1 gap-3 md:grid-cols-2" onSubmit={submitField}>
                <select className="control" name="target_table_id" required>
                  <option value="">选择目标表</option>
                  {tableOptions.map((item) => (
                    <option key={item.value} value={item.value}>
                      {item.label}
                    </option>
                  ))}
                </select>
                <input className="control" name="field_code" placeholder="字段代码" required />
                <input className="control" name="field_name" placeholder="字段名称" required />
                <input className="control" name="field_type" placeholder="字段类型" />
                <label className="flex items-center gap-2 rounded-md border border-line bg-white px-3 py-2 text-sm">
                  <input name="required_flag" type="checkbox" />
                  必填
                </label>
                <textarea className="control min-h-20 md:col-span-2" name="field_definition" placeholder="字段定义" />
                <textarea className="control min-h-20 md:col-span-2" name="regulatory_description" placeholder="监管描述" />
                <button className="button-primary md:col-span-2" disabled={!selectedProjectId || tables.length === 0} type="submit">
                  <Plus size={16} />
                  新建字段
                </button>
              </form>

              <div className="mt-4 grid grid-cols-1 gap-2 md:grid-cols-2">
                {fields.map((field) => (
                  <button
                    key={field.id}
                    className={`rounded-md border px-3 py-2 text-left text-sm ${field.id === selectedFieldId ? "border-pine bg-pine/10" : "border-line bg-white"}`}
                    onClick={() => setSelectedFieldId(field.id)}
                  >
                    <div className="font-medium">{field.field_code}</div>
                    <div className="text-slate-600">{field.field_name}</div>
                  </button>
                ))}
              </div>
            </Section>

            <Section title="SQL 解析">
              <form className="space-y-3" onSubmit={uploadSql}>
                <input className="control" name="file" type="file" accept=".sql" required />
                <button className="button-secondary w-full" disabled={!selectedProjectId} type="submit">
                  <FileUp size={16} />
                  上传 SQL
                </button>
              </form>
              <div className="mt-4 space-y-3">
                {sqlFiles.map((sqlFile) => (
                  <div key={sqlFile.id} className="rounded-md border border-line bg-white px-3 py-2 text-sm">
                    <div className="flex items-center justify-between gap-2">
                      <div className="font-medium">{sqlFile.file_name}</div>
                      <span className={sqlFile.parse_result?.parsed_success ? "text-pine" : "text-coral"}>
                        {sqlFile.parse_result?.parsed_success ? "成功" : "失败"}
                      </span>
                    </div>
                    <SqlParseList label="表" values={sqlFile.parse_result?.source_tables_json || []} />
                    <SqlParseList label="字段" values={sqlFile.parse_result?.selected_fields_json || []} />
                    <SqlParseList label="WHERE" values={sqlFile.parse_result?.where_conditions_json || []} />
                    {sqlFile.parse_result?.error_message ? <p className="mt-2 text-coral">{sqlFile.parse_result.error_message}</p> : null}
                  </div>
                ))}
              </div>
            </Section>
          </div>

          <Section
            title="字段分析"
            right={
              <button className="button-primary" disabled={!selectedField || busy} onClick={generateMapping}>
                <Wand2 size={16} />
                生成口径
              </button>
            }
          >
            {selectedField ? (
              <div className="space-y-4">
                <div className="grid grid-cols-1 gap-3 text-sm md:grid-cols-4">
                  <Metric label="字段代码" value={selectedField.field_code} />
                  <Metric label="字段名称" value={selectedField.field_name} />
                  <Metric label="字段类型" value={selectedField.field_type || "-"} />
                  <Metric label="必填" value={selectedField.required_flag ? "是" : "否"} />
                </div>
                {message ? <div className="rounded-md border border-line bg-mist px-3 py-2 text-sm text-slate-700">{message}</div> : null}
                {draft ? (
                  <DraftView draft={draft} onReview={reviewDraft} />
                ) : (
                  <div className="flex min-h-44 items-center justify-center rounded-md border border-dashed border-line bg-white text-sm text-slate-500">
                    <Search size={16} className="mr-2" />
                    暂无口径草稿
                  </div>
                )}
              </div>
            ) : (
              <div className="flex min-h-44 items-center justify-center rounded-md border border-dashed border-line bg-white text-sm text-slate-500">暂无字段</div>
            )}
          </Section>

          <Section
            title="双层口径工作台"
            right={
              <div className="flex flex-wrap gap-2">
                <button className="button-secondary" disabled={!selectedProjectId} onClick={() => exportMapping("project")} type="button">
                  <Download size={16} />
                  导出项目
                </button>
                <button className="button-secondary" disabled={!selectedField} onClick={() => exportMapping("table")} type="button">
                  <Download size={16} />
                  导出表
                </button>
                <button className="button-primary" disabled={!selectedField} onClick={() => exportMapping("field")} type="button">
                  <Download size={16} />
                  导出字段
                </button>
              </div>
            }
          >
            <div className="space-y-4">
              <div className="grid grid-cols-1 gap-3 text-sm md:grid-cols-4">
                <Metric label="一表通字段" value={selectedField ? `${selectedField.field_code} ${selectedField.field_name}` : "-"} />
                <Metric label="监管集市字段" value={selectedMartField ? `${selectedMartField.field_code} ${selectedMartField.field_name}` : "-"} />
                <Metric label="业务系统" value={selectedBusinessSystem ? `${selectedBusinessSystem.system_code} ${selectedBusinessSystem.system_name}` : "-"} />
                <Metric label="证据数量" value={String(mappingEvidence.length)} />
              </div>

              <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
                <div className="rounded-md border border-line bg-mist p-3">
                  <h3 className="text-sm font-semibold">业务系统到监管集市口径</h3>
                  <form className="mt-3 grid grid-cols-1 gap-3 md:grid-cols-2" onSubmit={submitSourceToMartMapping}>
                    <input className="control" name="mapping_name" placeholder="口径名称，例如 ECIF 证件类型入集市" />
                    <input className="control" name="source_system_summary" placeholder="来源业务系统" />
                    <input className="control" name="source_tables_summary" placeholder="来源表" />
                    <input className="control" name="source_fields_summary" placeholder="来源字段" />
                    <textarea className="control min-h-20 md:col-span-2" name="business_rule" placeholder="业务规则" />
                    <textarea className="control min-h-16 md:col-span-2" name="filter_condition" placeholder="过滤条件" />
                    <button className="button-primary md:col-span-2" disabled={!selectedMartField} type="submit">
                      <Plus size={16} />
                      新建业务系统到集市口径
                    </button>
                  </form>
                  <div className="mt-4 space-y-3">
                    {sourceToMartMappings.map((mapping) => (
                      <SourceToMartCard
                        key={mapping.id}
                        mapping={mapping}
                        onApprove={() => reviewSourceToMart(mapping.id, "approve")}
                        onGenerate={() => generateSourceToMart(mapping.id)}
                        onReject={() => reviewSourceToMart(mapping.id, "reject")}
                        onSave={(content) => saveSourceToMartFinal(mapping, content)}
                        onVersion={() => saveSourceToMartVersion(mapping.id)}
                      />
                    ))}
                    {!sourceToMartMappings.length ? <EmptyBlock text="选择监管集市字段后，可创建第一层口径。" /> : null}
                  </div>
                </div>

                <div className="rounded-md border border-line bg-mist p-3">
                  <h3 className="text-sm font-semibold">监管集市到一表通口径</h3>
                  <form className="mt-3 grid grid-cols-1 gap-3 md:grid-cols-2" onSubmit={submitMartToYbtMapping}>
                    <input className="control" name="mapping_name" placeholder="口径名称，例如 证件类型报送口径" />
                    <select className="control" name="mart_field_id" defaultValue={selectedMartFieldId || ""}>
                      <option value="">选择监管集市字段</option>
                      {martFieldOptions.map((item) => (
                        <option key={item.value} value={item.value}>
                          {item.label}
                        </option>
                      ))}
                    </select>
                    <input className="control" name="mart_table_summary" placeholder="集市表摘要" />
                    <input className="control" name="mart_field_summary" placeholder="集市字段摘要" />
                    <textarea className="control min-h-20 md:col-span-2" name="business_rule" placeholder="取数口径" />
                    <textarea className="control min-h-16 md:col-span-2" name="reporting_condition" placeholder="报送限制条件" />
                    <button className="button-primary md:col-span-2" disabled={!selectedField} type="submit">
                      <Plus size={16} />
                      新建集市到一表通口径
                    </button>
                  </form>
                  <div className="mt-4 space-y-3">
                    {martToYbtMappings.map((mapping) => (
                      <MartToYbtCard
                        key={mapping.id}
                        mapping={mapping}
                        onApprove={() => reviewMartToYbt(mapping.id, "approve")}
                        onGenerate={() => generateMartToYbt(mapping.id)}
                        onReject={() => reviewMartToYbt(mapping.id, "reject")}
                        onSave={(content) => saveMartToYbtFinal(mapping, content)}
                        onVersion={() => saveMartToYbtVersion(mapping.id)}
                      />
                    ))}
                    {!martToYbtMappings.length ? <EmptyBlock text="选择一表通字段后，可创建第二层口径。" /> : null}
                  </div>
                </div>
              </div>

              <div className="grid grid-cols-1 gap-4 xl:grid-cols-[420px_1fr]">
                <div className="rounded-md border border-line bg-white p-3">
                  <h3 className="text-sm font-semibold">绑定人工证据</h3>
                  <form className="mt-3 space-y-3" onSubmit={submitManualEvidence}>
                    <select className="control" name="mapping_ref" required>
                      <option value="">选择口径</option>
                      {sourceToMartMappings.map((mapping) => (
                        <option key={`s-${mapping.id}`} value={`source_to_mart:${mapping.id}`}>
                          source_to_mart / {mapping.mapping_name || mapping.id}
                        </option>
                      ))}
                      {martToYbtMappings.map((mapping) => (
                        <option key={`m-${mapping.id}`} value={`mart_to_ybt:${mapping.id}`}>
                          mart_to_ybt / {mapping.mapping_name || mapping.id}
                        </option>
                      ))}
                    </select>
                    <input className="control" name="source_name" placeholder="证据来源" />
                    <input className="control" name="location_text" placeholder="位置" />
                    <textarea className="control min-h-20" name="quoted_content" placeholder="引用内容" />
                    <textarea className="control min-h-16" name="evidence_summary" placeholder="证据摘要" />
                    <button className="button-secondary w-full" type="submit">
                      <Plus size={16} />
                      添加证据
                    </button>
                  </form>
                </div>
                <div className="rounded-md border border-line bg-white p-3">
                  <h3 className="text-sm font-semibold">口径证据</h3>
                  <div className="mt-3 space-y-2">
                    {mappingEvidence.map((evidence) => (
                      <details key={evidence.id} className="rounded-md border border-line bg-mist px-3 py-2 text-sm">
                        <summary className="cursor-pointer font-medium">
                          {evidence.mapping_type} / {evidence.evidence_type} / {evidence.source_name}
                        </summary>
                        <div className="mt-2 text-slate-600">{evidence.location_text || "-"}</div>
                        <pre className="mt-2 max-h-40 overflow-auto whitespace-pre-wrap rounded-md bg-white p-3 text-xs">{evidence.evidence_summary || evidence.quoted_content || "-"}</pre>
                      </details>
                    ))}
                    {!mappingEvidence.length ? <EmptyBlock text="暂无口径级证据。" /> : null}
                  </div>
                </div>
              </div>

              {exportResult ? (
                <div className="rounded-md border border-line bg-white p-3">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <h3 className="text-sm font-semibold">导出预览：{exportResult.file_name}</h3>
                    <a className="button-secondary" download={exportResult.file_name} href={`data:text/markdown;charset=utf-8,${encodeURIComponent(exportResult.content)}`}>
                      <Download size={16} />
                      下载 Markdown
                    </a>
                  </div>
                  <pre className="mt-3 max-h-[520px] overflow-auto whitespace-pre-wrap rounded-md bg-mist p-4 text-xs leading-6 text-slate-700">{exportResult.content}</pre>
                </div>
              ) : null}
            </div>
          </Section>
        </section>
      </div>
    </main>
  );
}

function DraftView({ draft, onReview }: { draft: FieldDraft; onReview: (status: "approved" | "rejected" | "revised") => Promise<void> }) {
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <Badge label={`置信度 ${draft.confidence_level}`} tone={draft.confidence_level === "high" ? "green" : draft.confidence_level === "low" ? "red" : "gold"} />
        <Badge label={`审核 ${draft.review_status}`} tone="slate" />
        <button className="button-secondary" onClick={() => onReview("approved")}>
          <Check size={16} />
          通过
        </button>
        <button className="button-secondary" onClick={() => onReview("revised")}>
          <RefreshCw size={16} />
          修改
        </button>
        <button className="button-danger" onClick={() => onReview("rejected")}>
          <X size={16} />
          驳回
        </button>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <TextBlock title="业务系统到监管集市口径" text={draft.business_to_mart_rule || "-"} />
        <TextBlock title="监管集市到一表通口径" text={draft.mart_to_ybt_rule || "-"} />
        <TextBlock title="EAST 参考摘要" text={draft.east_reference_summary || "-"} />
        <TextBlock title="SQL 参考摘要" text={draft.sql_reference_summary || "-"} />
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <ListBlock title="来源系统候选" values={draft.source_system_candidates_json} />
        <ListBlock title="来源表候选" values={draft.source_table_candidates_json} />
        <ListBlock title="来源字段候选" values={draft.source_field_candidates_json} />
      </div>

      <ListBlock title="风险提示" values={draft.risk_points_json} />
      <ListBlock title="待人工确认问题" values={draft.questions_for_human_json} />
      <TextBlock title="校验说明" text={draft.validation_notes || "-"} />

      <div>
        <h3 className="mb-2 text-sm font-semibold">该口径参考来源</h3>
        <div className="space-y-2">
          {draft.evidences.map((evidence, index) => (
            <details key={evidence.id} className="rounded-md border border-line bg-white px-3 py-2 text-sm">
              <summary className="cursor-pointer font-medium">
                {index + 1}. {evidence.source_name} / {evidence.location_text}
              </summary>
              <pre className="mt-2 max-h-44 overflow-auto whitespace-pre-wrap rounded-md bg-mist p-3 text-xs leading-5 text-slate-700">{evidence.quoted_content}</pre>
            </details>
          ))}
        </div>
      </div>
    </div>
  );
}

function SourceToMartCard({
  mapping,
  onApprove,
  onGenerate,
  onReject,
  onSave,
  onVersion
}: {
  mapping: SourceToMartMapping;
  onApprove: () => Promise<void>;
  onGenerate: () => Promise<void>;
  onReject: () => Promise<void>;
  onSave: (content: string) => Promise<void>;
  onVersion: () => Promise<void>;
}) {
  const [content, setContent] = useState(mapping.final_content || mapping.ai_generated_content || "");
  useEffect(() => {
    setContent(mapping.final_content || mapping.ai_generated_content || "");
  }, [mapping.ai_generated_content, mapping.final_content]);
  return (
    <div className="rounded-md border border-line bg-white p-3 text-sm">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <div className="font-medium">{mapping.mapping_name || `口径 ${mapping.id}`}</div>
          <div className="mt-1 text-slate-500">{mapping.source_system_summary || "来源系统待确认"} / {mapping.source_fields_summary || "来源字段待确认"}</div>
        </div>
        <Badge label={mapping.mapping_status} tone={mapping.mapping_status === "approved" ? "green" : mapping.mapping_status === "rejected" ? "red" : "gold"} />
      </div>
      <div className="mt-3 grid grid-cols-1 gap-3 md:grid-cols-2">
        <TextBlock title="业务规则" text={mapping.business_rule || "-"} />
        <TextBlock title="过滤条件" text={mapping.filter_condition || "-"} />
      </div>
      <textarea className="control mt-3 min-h-32" onChange={(event) => setContent(event.target.value)} value={content} />
      <div className="mt-3 flex flex-wrap gap-2">
        <button className="button-secondary" onClick={onGenerate} type="button">
          <Wand2 size={16} />
          AI 草稿
        </button>
        <button className="button-secondary" onClick={() => onSave(content)} type="button">
          <Save size={16} />
          保存
        </button>
        <button className="button-secondary" onClick={onVersion} type="button">
          <Save size={16} />
          版本
        </button>
        <button className="button-secondary" onClick={onApprove} type="button">
          <Check size={16} />
          通过
        </button>
        <button className="button-danger" onClick={onReject} type="button">
          <X size={16} />
          驳回
        </button>
      </div>
    </div>
  );
}

function MartToYbtCard({
  mapping,
  onApprove,
  onGenerate,
  onReject,
  onSave,
  onVersion
}: {
  mapping: MartToYbtMapping;
  onApprove: () => Promise<void>;
  onGenerate: () => Promise<void>;
  onReject: () => Promise<void>;
  onSave: (content: string) => Promise<void>;
  onVersion: () => Promise<void>;
}) {
  const [content, setContent] = useState(mapping.final_content || mapping.ai_generated_content || "");
  useEffect(() => {
    setContent(mapping.final_content || mapping.ai_generated_content || "");
  }, [mapping.ai_generated_content, mapping.final_content]);
  return (
    <div className="rounded-md border border-line bg-white p-3 text-sm">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <div className="font-medium">{mapping.mapping_name || `口径 ${mapping.id}`}</div>
          <div className="mt-1 text-slate-500">{mapping.mart_table_summary || "集市表待确认"} / {mapping.mart_field_summary || "集市字段待确认"}</div>
        </div>
        <Badge label={mapping.mapping_status} tone={mapping.mapping_status === "approved" ? "green" : mapping.mapping_status === "rejected" ? "red" : "gold"} />
      </div>
      <div className="mt-3 grid grid-cols-1 gap-3 md:grid-cols-2">
        <TextBlock title="取数口径" text={mapping.business_rule || "-"} />
        <TextBlock title="报送限制" text={mapping.reporting_condition || "-"} />
      </div>
      <textarea className="control mt-3 min-h-32" onChange={(event) => setContent(event.target.value)} value={content} />
      <div className="mt-3 flex flex-wrap gap-2">
        <button className="button-secondary" onClick={onGenerate} type="button">
          <Wand2 size={16} />
          AI 草稿
        </button>
        <button className="button-secondary" onClick={() => onSave(content)} type="button">
          <Save size={16} />
          保存
        </button>
        <button className="button-secondary" onClick={onVersion} type="button">
          <Save size={16} />
          版本
        </button>
        <button className="button-secondary" onClick={onApprove} type="button">
          <Check size={16} />
          通过
        </button>
        <button className="button-danger" onClick={onReject} type="button">
          <X size={16} />
          驳回
        </button>
      </div>
    </div>
  );
}

function EmptyBlock({ text }: { text: string }) {
  return <div className="flex min-h-24 items-center justify-center rounded-md border border-dashed border-line bg-white text-sm text-slate-500">{text}</div>;
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-line bg-white px-3 py-2">
      <div className="text-xs text-slate-500">{label}</div>
      <div className="mt-1 font-medium">{value}</div>
    </div>
  );
}

function TextBlock({ title, text }: { title: string; text: string }) {
  return (
    <div className="rounded-md border border-line bg-white p-3">
      <h3 className="text-sm font-semibold">{title}</h3>
      <p className="mt-2 whitespace-pre-wrap text-sm leading-6 text-slate-700">{text}</p>
    </div>
  );
}

function ListBlock({ title, values }: { title: string; values: string[] }) {
  return (
    <div className="rounded-md border border-line bg-white p-3">
      <h3 className="text-sm font-semibold">{title}</h3>
      <div className="mt-2 flex flex-wrap gap-2">
        {values.length ? values.map((value) => <Badge key={value} label={value} tone="slate" />) : <span className="text-sm text-slate-500">-</span>}
      </div>
    </div>
  );
}

function Badge({ label, tone }: { label: string; tone: "green" | "red" | "gold" | "slate" }) {
  const classes = {
    green: "border-pine/30 bg-pine/10 text-pine",
    red: "border-coral/30 bg-coral/10 text-coral",
    gold: "border-gold/30 bg-gold/10 text-gold",
    slate: "border-line bg-mist text-slate-700"
  };
  return <span className={`inline-flex items-center rounded-md border px-2 py-1 text-xs font-medium ${classes[tone]}`}>{label}</span>;
}

function SqlParseList({ label, values }: { label: string; values: string[] }) {
  if (!values.length) {
    return null;
  }
  return (
    <div className="mt-2 text-xs text-slate-600">
      <span className="font-medium">{label}: </span>
      {values.slice(0, 4).join(" / ")}
      {values.length > 4 ? " ..." : ""}
    </div>
  );
}

function SqlList({ items }: { items: Array<{ name: string; sql: string }> }) {
  return (
    <div className="mt-3 space-y-2">
      {items.map((item) => (
        <details key={item.name} className="rounded-md border border-line bg-mist px-3 py-2 text-xs">
          <summary className="cursor-pointer font-medium">{item.name}</summary>
          <pre className="mt-2 overflow-auto whitespace-pre-wrap leading-5">{item.sql}</pre>
        </details>
      ))}
    </div>
  );
}

function textValue(form: FormData, key: string): string {
  const value = form.get(key);
  return typeof value === "string" ? value.trim() : "";
}

function numericOrNull(form: FormData, key: string): number | null {
  const value = textValue(form, key);
  return value ? Number(value) : null;
}

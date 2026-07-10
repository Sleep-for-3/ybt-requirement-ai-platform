const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000/api";

export type Project = {
  id: number;
  name: string;
  bank_name?: string | null;
  description?: string | null;
};

export type TargetTable = {
  id: number;
  project_id: number;
  table_code: string;
  table_name: string;
  description?: string | null;
};

export type TargetField = {
  id: number;
  project_id: number;
  target_table_id: number;
  field_code: string;
  field_name: string;
  field_type?: string | null;
  required_flag: boolean;
  field_definition?: string | null;
  regulatory_description?: string | null;
  data_category?: string | null;
  data_format?: string | null;
  regulatory_original_definition?: string | null;
  regulatory_refined_definition?: string | null;
  report_name?: string | null;
  report_field_name?: string | null;
  east_definition?: string | null;
  internal_definition?: string | null;
  remarks?: string | null;
};

export type ProductScenario = {
  id: number;
  project_id: number;
  scenario_code: string;
  scenario_name: string;
  scenario_type?: string | null;
  description?: string | null;
  business_owner?: string | null;
  tech_owner?: string | null;
  enabled: boolean;
  sort_order: number;
};

export type ScenarioBusinessMapping = {
  id: number;
  project_id: number;
  target_field_id: number;
  scenario_id: number;
  business_definition?: string | null;
  source_system_screenshot_required: boolean;
  source_system_change_required: boolean;
  external_data_required: boolean;
  manual_supplement_required: boolean;
  business_owner?: string | null;
  business_confirm_status: string;
  remarks?: string | null;
  ai_generated_content?: string | null;
  final_content?: string | null;
  confidence_level: string;
  open_questions?: string | null;
};

export type ScenarioTechnicalLineage = {
  id: number;
  project_id: number;
  target_field_id: number;
  scenario_id: number;
  business_mapping_id?: number | null;
  source_system_name?: string | null;
  source_database_name?: string | null;
  source_schema_name?: string | null;
  source_table_english_name?: string | null;
  source_table_chinese_name?: string | null;
  source_field_english_name?: string | null;
  source_field_chinese_name?: string | null;
  processing_logic?: string | null;
  processing_logic_type?: string | null;
  tech_owner?: string | null;
  tech_confirm_status: string;
  remarks?: string | null;
  ai_generated_content?: string | null;
  final_content?: string | null;
  confidence_level: string;
  open_questions?: string | null;
};

export type CandidateSourceRecommendation = {
  id: number;
  recommended_source_system?: string | null;
  recommended_database_name?: string | null;
  recommended_schema_name?: string | null;
  recommended_table_name?: string | null;
  recommended_table_comment?: string | null;
  recommended_field_name?: string | null;
  recommended_field_comment?: string | null;
  recommended_processing_logic?: string | null;
  recommend_reason: string;
  evidence_summary: string;
  confidence_level: string;
  score: number;
  selected_flag: boolean;
};

export type RegulatoryKnowledgeItem = {
  id: number;
  knowledge_type: string;
  target_field_code?: string | null;
  scenario_id?: number | null;
  business_explanation?: string | null;
  source_document_name?: string | null;
  source_sheet_name?: string | null;
  source_cell_range?: string | null;
  score?: number;
};

export type TraceabilityTemplateDocument = {
  id: number;
  project_id: number;
  file_name: string;
  parse_status: string;
  sheet_names_json: string[];
  detected_scenarios_json: Array<{ scenario_code: string; scenario_name: string }>;
  parse_summary_json: Record<string, number>;
  warnings_json: string[];
  error_message?: string | null;
};

export type KnowledgeDocument = {
  id: number;
  project_id: number;
  file_name: string;
  file_type: string;
  source_type: string;
};

export type SqlFile = {
  id: number;
  project_id: number;
  file_name: string;
  raw_sql: string;
  parse_result?: {
    parsed_success: boolean;
    source_tables_json: string[];
    selected_fields_json: string[];
    joins_json: string[];
    where_conditions_json: string[];
    error_message?: string | null;
  } | null;
};

export type FieldDraft = {
  id: number;
  business_to_mart_rule?: string | null;
  mart_to_ybt_rule?: string | null;
  source_system_candidates_json: string[];
  source_table_candidates_json: string[];
  source_field_candidates_json: string[];
  east_reference_summary?: string | null;
  sql_reference_summary?: string | null;
  validation_notes?: string | null;
  confidence_level: string;
  review_status: string;
  final_content?: string | null;
  risk_points_json: string[];
  questions_for_human_json: string[];
  template_reference_summary?: string | null;
  db_query_summary?: string | null;
  data_quality_notes?: string | null;
  evidence_completeness?: string;
  evidences: Array<{
    id: number;
    evidence_type: string;
    source_name: string;
    location_text: string;
    quoted_content: string;
  }>;
};

export type TemplateDocument = {
  id: number;
  project_id: number;
  file_name: string;
  parse_status: string;
  sheet_names_json: string[];
  error_message?: string | null;
};

export type TemplateUploadResponse = {
  template_id: number;
  file_name: string;
  parse_status: string;
  sheet_count: number;
  table_count: number;
  field_count: number;
  warnings: string[];
  preview: Array<{
    sheet_name: string;
    table_code?: string | null;
    table_name?: string | null;
    field_count: number;
  }>;
};

export type TemplateApplyResponse = {
  template_id: number;
  created_tables: number;
  updated_tables: number;
  created_fields: number;
  updated_fields: number;
  skipped_rows: number;
  warnings: string[];
};

export type DataSource = {
  id: number;
  project_id: number;
  name: string;
  display_name?: string | null;
  db_type: string;
  host?: string | null;
  port?: number | null;
  database_name?: string | null;
  schema_name?: string | null;
  username?: string | null;
  password_configured: boolean;
  readonly_flag: boolean;
  enabled: boolean;
  last_test_status?: string | null;
  last_test_message?: string | null;
};

export type NaturalLanguageTask = {
  id: number;
  project_id: number;
  raw_text: string;
  datasource_name?: string | null;
  intent?: string | null;
  status: string;
  extracted_table_name?: string | null;
  extracted_field_name?: string | null;
  generated_sql_json: Array<{ name: string; sql: string }>;
  result_summary_json: Record<string, unknown>;
  error_message?: string | null;
};

export type NaturalLanguageTaskCreateResponse = {
  task_id: number;
  status: string;
  datasource_name?: string | null;
  intent?: string | null;
  extracted_table_name?: string | null;
  extracted_field_name?: string | null;
  message: string;
  available_datasources: string[];
};

export type BusinessSystem = {
  id: number;
  project_id: number;
  system_code: string;
  system_name: string;
  description?: string | null;
  owner_department?: string | null;
  enabled: boolean;
};

export type SourceTable = {
  id: number;
  project_id: number;
  business_system_id: number;
  table_code: string;
  table_name: string;
  table_comment?: string | null;
  datasource_id?: number | null;
  schema_name?: string | null;
  physical_table_name?: string | null;
  description?: string | null;
};

export type SourceField = {
  id: number;
  project_id: number;
  source_table_id: number;
  field_code: string;
  field_name: string;
  field_type?: string | null;
  field_comment?: string | null;
  physical_column_name?: string | null;
  description?: string | null;
};

export type MartTable = {
  id: number;
  project_id: number;
  table_code: string;
  table_name: string;
  subject_area?: string | null;
  table_comment?: string | null;
  datasource_id?: number | null;
  schema_name?: string | null;
  physical_table_name?: string | null;
  is_existing: boolean;
  description?: string | null;
};

export type MartField = {
  id: number;
  project_id: number;
  mart_table_id: number;
  field_code: string;
  field_name: string;
  field_type?: string | null;
  field_comment?: string | null;
  physical_column_name?: string | null;
  is_existing: boolean;
  description?: string | null;
};

export type SourceToMartMapping = {
  id: number;
  project_id: number;
  mart_field_id: number;
  mapping_name?: string | null;
  mapping_status: string;
  source_system_summary?: string | null;
  source_tables_summary?: string | null;
  source_fields_summary?: string | null;
  business_rule?: string | null;
  filter_condition?: string | null;
  join_condition?: string | null;
  priority_rule?: string | null;
  merge_rule?: string | null;
  code_mapping_rule?: string | null;
  null_handling_rule?: string | null;
  exception_rule?: string | null;
  quality_check_rule?: string | null;
  open_questions?: string | null;
  ai_generated_content?: string | null;
  final_content?: string | null;
  confidence_level: string;
};

export type MartToYbtMapping = {
  id: number;
  project_id: number;
  target_field_id: number;
  mart_field_id?: number | null;
  mapping_name?: string | null;
  mapping_status: string;
  mart_table_summary?: string | null;
  mart_field_summary?: string | null;
  business_rule?: string | null;
  filter_condition?: string | null;
  join_condition?: string | null;
  code_mapping_rule?: string | null;
  null_handling_rule?: string | null;
  reporting_condition?: string | null;
  validation_rule?: string | null;
  open_questions?: string | null;
  ai_generated_content?: string | null;
  final_content?: string | null;
  confidence_level: string;
};

export type MappingEvidence = {
  id: number;
  project_id: number;
  mapping_type: string;
  mapping_id: number;
  evidence_type: string;
  evidence_id?: number | null;
  source_name: string;
  location_text?: string | null;
  quoted_content?: string | null;
  evidence_summary?: string | null;
};

export type MappingDocumentExport = {
  format: string;
  scope: string;
  scope_id: number;
  file_name: string;
  content: string;
};

export async function apiGet<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(await response.text());
  }
  return response.json();
}

export async function apiPost<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body)
  });
  if (!response.ok) {
    throw new Error(await response.text());
  }
  return response.json();
}

export async function apiPatch<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body)
  });
  if (!response.ok) {
    throw new Error(await response.text());
  }
  return response.json();
}

export async function apiPut<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body)
  });
  if (!response.ok) {
    throw new Error(await response.text());
  }
  return response.json();
}

export async function apiDelete<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, { method: "DELETE" });
  if (!response.ok) {
    throw new Error(await response.text());
  }
  return response.json();
}

export async function uploadForm<T>(path: string, formData: FormData): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    body: formData
  });
  if (!response.ok) {
    throw new Error(await response.text());
  }
  return response.json();
}

export async function apiDownload(path: string): Promise<{ blob: Blob; fileName: string }> {
  const response = await fetch(`${API_BASE}${path}`);
  if (!response.ok) {
    throw new Error(await response.text());
  }
  const disposition = response.headers.get("content-disposition") || "";
  const encodedName = disposition.match(/filename\*=UTF-8''([^;]+)/i)?.[1];
  return { blob: await response.blob(), fileName: encodedName ? decodeURIComponent(encodedName) : "业务口径及技术溯源表.xlsx" };
}

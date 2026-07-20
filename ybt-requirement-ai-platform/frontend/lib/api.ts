const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000/api";
const ACCESS_TOKEN_KEY = "ybt:access-token";
const REFRESH_TOKEN_KEY = "ybt:refresh-token";

export function saveSession(accessToken: string, refreshToken: string) {
  sessionStorage.setItem(ACCESS_TOKEN_KEY, accessToken);
  sessionStorage.setItem(REFRESH_TOKEN_KEY, refreshToken);
}

export function clearSession() {
  sessionStorage.removeItem(ACCESS_TOKEN_KEY);
  sessionStorage.removeItem(REFRESH_TOKEN_KEY);
}

export function hasSession() {
  return typeof window !== "undefined" && Boolean(sessionStorage.getItem(ACCESS_TOKEN_KEY));
}

function authHeaders(extra: Record<string, string> = {}): Record<string, string> {
  const token = typeof window !== "undefined" ? sessionStorage.getItem(ACCESS_TOKEN_KEY) : null;
  return token ? { ...extra, Authorization: `Bearer ${token}` } : extra;
}

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
  lineage_status: string;
  lineage_last_verified_at?: string | null;
  lineage_change_set_id?: number | null;
};

export type ScriptFile = { id:number;project_id:number;relative_path:string;file_name:string;file_type:string;logical_target_name?:string|null;enabled:boolean;current_version_no:number };
export type ScriptVersion = { id:number;version_no:number;file_hash:string;normalized_hash:string;parse_status:string;dialect?:string|null;warnings:string[];git_commit_sha?:string|null;created_at:string };
export type ScriptDependency = { id:number;child_script_file_id?:number|null;dependency_type:string;call_expression:string;condition_expression?:string|null;source_line_start?:number|null;source_line_end?:number|null;confidence_level:string;warnings:string[] };
export type LineageNode = { id:number;node_type:string;logical_name:string;database_name?:string|null;schema_name?:string|null;table_name?:string|null;column_name?:string|null;catalog_column_id?:number|null;source_field_id?:number|null;mart_field_id?:number|null;target_field_id?:number|null;unresolved_flag:boolean;metadata:Record<string,unknown> };
export type LineageEdge = { id:number;source_node_id:number;target_node_id:number;edge_type:string;transformation_type?:string|null;transformation_expression?:string|null;join_condition?:string|null;filter_condition?:string|null;aggregation_rule?:string|null;code_mapping_rule?:string|null;source_line_start?:number|null;source_line_end?:number|null;confidence_level:string;evidence:Record<string,unknown> };
export type LineageGraph = { nodes:LineageNode[];edges:LineageEdge[];direction:string;depth:number;truncated:boolean };
export type ScriptChange = { id:number;script_file_id:number;from_version_id?:number|null;to_version_id?:number|null;change_type:string;status:string;summary:Record<string,unknown>;severity:string;impact_id?:number|null;created_at:string };
export type ImpactAnalysis = { id:number;project_id:number;change_set_id:number;status:string;severity:string;affected_target_field_ids:number[];affected_mart_field_ids:number[];affected_mapping_ids:string[];summary:Record<string,unknown>;open_questions:string[];workflow?:{id:number;status:string;current_step?:string|null;tasks:Array<{id:number;step_key:string;status:string;assignee_user_id?:number|null;assignee_role?:string|null}>}|null };

export type ScenarioReviewPackageView = {
  id: number;
  project_id: number;
  target_field_id: number;
  scenario_id: number;
  business_mapping_id: number;
  technical_lineage_id: number;
  status: string;
  current_version_no: number;
  workflow_instance?: {
    id: number;
    status: string;
    current_step?: string | null;
    current_task_id?: number | null;
    current_assignee_user_id?: number | null;
    current_assignee_role?: string | null;
    can_withdraw: boolean;
  } | null;
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
  catalog_column_id?: number | null;
  datasource_id?: number | null;
  data_type?: string | null;
  nullable?: boolean | null;
  profile_status?: string | null;
  retrieval_log_id?: number | null;
  knowledge_unit_ids_json?: number[];
  citation_summary_json?: Array<{ knowledge_unit_id:number; source_file_name:string; source_sheet_name?:string|null; source_cell_range?:string|null }>;
  recommendation_basis?: string | null;
};

export type CatalogSchema = { id:number; datasource_id:number; schema_name:string; schema_comment?:string|null; enabled:boolean };
export type CatalogTable = { id:number; datasource_id:number; schema_name:string; table_name:string; table_comment?:string|null; table_type:string; estimated_row_count?:number|null; primary_key_columns_json:string[]; enabled:boolean };
export type CatalogColumn = { id:number; datasource_id:number; catalog_table_id:number; schema_name:string; table_name:string; column_name:string; column_comment?:string|null; data_type?:string|null; nullable:boolean; ordinal_position:number; is_primary_key:boolean; enabled:boolean };
export type CatalogSearchItem = { catalog_column_id:number; datasource_id:number; datasource_name:string; schema_name:string; table_name:string; table_comment?:string|null; column_name:string; column_comment?:string|null; data_type?:string|null; nullable:boolean; is_primary_key:boolean; score:number; match_reasons:string[]; imported_source_field_id?:number|null; imported_mart_field_id?:number|null };
export type MetadataSyncTask = { id:number; datasource_id:number; status:string; sync_mode:string; schema_count:number; table_count:number; column_count:number; warnings_json:string[]; error_message?:string|null };
export type ColumnProfileTask = { id:number; status:string; catalog_column_id:number; profile_result_json:Record<string,unknown>; generated_sql_json:Array<{metric:string;sql:string}>; error_message?:string|null };
export type ColumnProfileSnapshot = { id:number; profile_task_id:number; catalog_column_id:number; profile_date:string; total_count?:number|null; null_rate?:number|null; distinct_count?:number|null; min_value_text?:string|null; max_value_text?:string|null; min_length?:number|null; max_length?:number|null; average_length?:number|null; top_values_json:unknown[]; warnings_json:unknown[] };
export type KnowledgeRagDocument = { id:number; project_id:number; file_name:string; knowledge_type:string; knowledge_scope:string; institution_name?:string|null; document_status:string; confidentiality_level:string; current_version_no:number; parse_summary_json:Record<string,unknown>; warnings_json:string[] };
export type KnowledgeUnit = { id:number; document_id:number; knowledge_type:string; unit_type:string; title?:string|null; content:string; source_file_name:string; source_sheet_name?:string|null; source_page_no?:number|null; source_heading?:string|null; source_cell_range?:string|null; target_field_code?:string|null; enabled:boolean };
export type HybridKnowledgeItem = { knowledge_unit_id:number; title?:string|null; content:string; knowledge_type:string; source_file_name:string; source_sheet_name?:string|null; source_cell_range?:string|null; source_page_no?:number|null; keyword_score:number; vector_score:number; rerank_score:number; match_reasons:string[] };
export type DeliverableTemplate = { id:number;project_id:number;template_name:string;template_type:string;description?:string|null;enabled:boolean;is_default:boolean;current_version_no:number;current_version_id?:number|null };
export type DeliverableTemplateVersion = { id:number;project_id:number;template_id:number;version_no:number;file_hash:string;sheet_config_json:Array<Record<string,unknown>>;parse_status:string;warnings_json:unknown[] };
export type DeliverableFieldItem = { id:number;target_field_id:number;field_order:number;field_status:string;business_summary?:string|null;technical_summary?:string|null;evidence_completeness:number;confidence_level:string;open_question_count:number };
export type DeliverablePackage = { id:number;project_id:number;package_name:string;package_type:string;target_table_id:number;template_version_id:number;status:string;version_no:number;generated_file_id?:number|null;summary_json:Record<string,unknown>;warnings_json:unknown[];field_count:number;approved_field_count:number;items:DeliverableFieldItem[] };
export type PendingQuestion = { id:number;project_id:number;target_table_id:number;target_field_id?:number|null;scenario_id?:number|null;question_type:string;question_text:string;question_status:string;priority:string;assigned_role?:string|null;assigned_user_id?:number|null;resolution_text?:string|null };
export type HistoricalCaliberImport = { id:number;project_id:number;import_name:string;document_type:string;status:string;parse_summary_json:Record<string,number>;warnings_json:unknown[] };
export type HistoricalCaliberItem = { id:number;target_field_code?:string|null;target_field_name?:string|null;scenario_name?:string|null;business_content?:string|null;technical_content?:string|null;source_sheet_name:string;source_cell_range:string;match_status:string };

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
  lineage_status: string;
  lineage_last_verified_at?: string | null;
  lineage_change_set_id?: number | null;
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
  lineage_status: string;
  lineage_last_verified_at?: string | null;
  lineage_change_set_id?: number | null;
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
  const response = await fetch(`${API_BASE}${path}`, { cache: "no-store", headers: authHeaders() });
  if (!response.ok) {
    throw new Error(await response.text());
  }
  return response.json();
}

export async function apiPost<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
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
    headers: authHeaders({ "Content-Type": "application/json" }),
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
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(body)
  });
  if (!response.ok) {
    throw new Error(await response.text());
  }
  return response.json();
}

export async function apiDelete<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, { method: "DELETE", headers: authHeaders() });
  if (!response.ok) {
    throw new Error(await response.text());
  }
  return response.json();
}

export async function uploadForm<T>(path: string, formData: FormData): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: authHeaders(),
    body: formData
  });
  if (!response.ok) {
    throw new Error(await response.text());
  }
  return response.json();
}

export async function apiDownload(path: string): Promise<{ blob: Blob; fileName: string }> {
  const response = await fetch(`${API_BASE}${path}`, { headers: authHeaders() });
  if (!response.ok) {
    throw new Error(await response.text());
  }
  const disposition = response.headers.get("content-disposition") || "";
  const encodedName = disposition.match(/filename\*=UTF-8''([^;]+)/i)?.[1];
  return { blob: await response.blob(), fileName: encodedName ? decodeURIComponent(encodedName) : "业务口径及技术溯源表.xlsx" };
}

export async function apiPostDownload(path: string, body: unknown = {}): Promise<{ blob: Blob; fileName: string }> {
  const response = await fetch(`${API_BASE}${path}`, { method: "POST", headers: authHeaders({ "Content-Type": "application/json" }), body: JSON.stringify(body) });
  if (!response.ok) throw new Error(await response.text());
  const disposition = response.headers.get("content-disposition") || "";
  const name = disposition.match(/filename=([^;]+)/i)?.[1] || "preview.xlsx";
  return { blob: await response.blob(), fileName: name.replaceAll('"', "") };
}

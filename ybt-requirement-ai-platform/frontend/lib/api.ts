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

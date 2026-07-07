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
  evidences: Array<{
    id: number;
    evidence_type: string;
    source_name: string;
    location_text: string;
    quoted_content: string;
  }>;
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

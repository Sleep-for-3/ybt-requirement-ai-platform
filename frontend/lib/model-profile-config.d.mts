export type ModelProfileConfig = {
  json_mode?: boolean;
  max_output_tokens?: number;
  max_context_tokens?: number;
  temperature?: number;
  timeout_seconds?: number;
  retry_count?: number;
  requirement_max_input_bytes?: number;
  [key: string]: unknown;
};

export type EditableModelProfile = { config_json?: ModelProfileConfig } | null | undefined;

export const DEFAULT_MODEL_CONFIG: Readonly<Required<Pick<
  ModelProfileConfig,
  "json_mode" | "max_output_tokens" | "temperature" | "timeout_seconds" | "retry_count"
>>>;

export function buildModelProfileConfig(
  editing: EditableModelProfile,
  requirementMaxInputBytes: number,
): ModelProfileConfig;

export function changedConfigKeys(
  editing: EditableModelProfile,
  nextConfig: ModelProfileConfig,
): string[];

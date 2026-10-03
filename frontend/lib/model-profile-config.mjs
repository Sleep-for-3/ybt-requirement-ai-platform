/**
 * B13: editing a model profile must preserve every tuning value the operator did not change.
 *
 * The form only exposes the requirement input budget, so renaming a profile used to reset
 * json_mode / max_output_tokens / temperature / timeout_seconds / retry_count to defaults,
 * silently discarding tuned values (for example a raised max_output_tokens).
 */

export const DEFAULT_MODEL_CONFIG = Object.freeze({
  json_mode: true,
  max_output_tokens: 2048,
  temperature: 0.2,
  timeout_seconds: 60,
  retry_count: 2,
});

/**
 * Merge the stored config with the single field the form edits.
 * @param {object|null|undefined} editing existing profile being edited (null when creating)
 * @param {number} requirementMaxInputBytes value from the form field
 */
export function buildModelProfileConfig(editing, requirementMaxInputBytes) {
  const stored = editing && editing.config_json ? editing.config_json : DEFAULT_MODEL_CONFIG;
  return { ...stored, requirement_max_input_bytes: requirementMaxInputBytes };
}

/** Which keys changed between the stored and the submitted config. */
export function changedConfigKeys(editing, nextConfig) {
  const stored = editing && editing.config_json ? editing.config_json : {};
  const keys = new Set([...Object.keys(stored), ...Object.keys(nextConfig)]);
  return [...keys].filter((key) => stored[key] !== nextConfig[key]);
}

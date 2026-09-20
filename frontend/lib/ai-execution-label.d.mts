export type AIExecutionPresentation = {
  kind: string;
  label: string;
  tone: string;
  detail: string;
};

export type AIContextPresentation = {
  complete: boolean | null;
  label: string;
};

export function aiExecutionPresentation(
  metadata?: {
    execution_kind?: string | null;
    provider?: string | null;
    context_complete?: boolean | null;
  } | null
): AIExecutionPresentation;

export function aiContextPresentation(
  metadata?: {
    execution_kind?: string | null;
    provider?: string | null;
    context_complete?: boolean | null;
  } | null
): AIContextPresentation;

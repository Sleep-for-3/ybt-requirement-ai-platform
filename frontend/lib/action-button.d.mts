export type ActionButtonStatus = "idle" | "submitting" | "queued" | "running" | "success" | "failed" | "disabled";
export function resolveActionButtonState(input: {
  actionStatus?: ActionButtonStatus;
  disabled?: boolean;
  disabledReason?: string;
  idleLabel: import("react").ReactNode;
  loadingText?: string;
}): {
  busy: boolean;
  label: import("react").ReactNode;
  reason?: string;
  unavailable: boolean;
};

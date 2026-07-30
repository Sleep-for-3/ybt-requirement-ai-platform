"use client";

import { LoaderCircle } from "lucide-react";
import { ButtonHTMLAttributes, forwardRef } from "react";

import { AsyncActionStatus } from "@/hooks/useAsyncAction";
import { resolveActionButtonState } from "@/lib/action-button.mjs";

type Props = ButtonHTMLAttributes<HTMLButtonElement> & {
  actionStatus?: AsyncActionStatus | "disabled";
  disabledReason?: string;
  loadingText?: string;
};

export const AsyncActionButton = forwardRef<HTMLButtonElement, Props>(function AsyncActionButton({
  actionStatus = "idle",
  children,
  disabled,
  disabledReason,
  loadingText = "正在提交…",
  title,
  type = "button",
  ...props
}, ref) {
  const { busy, label, reason, unavailable } = resolveActionButtonState({
    actionStatus,
    disabled,
    disabledReason,
    idleLabel: children,
    loadingText
  });

  return (
    <span className="inline-flex flex-col items-start gap-1">
      <button
        {...props}
        aria-busy={busy}
        aria-disabled={unavailable}
        disabled={unavailable}
        ref={ref}
        title={reason || title}
        type={type}
      >
        {busy ? <LoaderCircle aria-hidden className="animate-spin" size={14} /> : null}
        {label}
      </button>
      {reason ? <span className="text-xs text-slate-500" role="note">{reason}</span> : null}
    </span>
  );
});

"use client";

import { useEffect, useRef } from "react";

import { AsyncActionButton } from "@/components/feedback/AsyncActionButton";

type Props = {
  cancelText?: string;
  confirmText?: string;
  description: string;
  busy?: boolean;
  danger?: boolean;
  open: boolean;
  title: string;
  onCancel: () => void;
  onConfirm: () => void | Promise<void>;
};

export function ConfirmDialog({
  cancelText = "取消",
  confirmText = "确认",
  description,
  busy = false,
  danger = false,
  open,
  title,
  onCancel,
  onConfirm
}: Props) {
  const confirmRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    const previous = document.activeElement as HTMLElement | null;
    confirmRef.current?.focus();
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape" && !busy) onCancel();
    }
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      previous?.focus();
    };
  }, [busy, onCancel, open]);

  if (!open) return null;
  return (
    <div aria-modal="true" className="fixed inset-0 z-[90] flex items-center justify-center p-4" role="dialog">
      <button aria-label="关闭确认框" className="absolute inset-0 bg-slate-950/50" disabled={busy} onClick={onCancel} type="button" />
      <div className="relative w-full max-w-md rounded-2xl border border-line bg-white p-5 shadow-pop">
        <h2 className="text-base font-semibold text-ink">{title}</h2>
        <p className="mt-2 text-sm leading-6 text-slate-600">{description}</p>
        <div className="mt-5 flex justify-end gap-2">
          <button className="button-secondary" disabled={busy} onClick={onCancel} type="button">{cancelText}</button>
          <AsyncActionButton
            actionStatus={busy ? "submitting" : "idle"}
            className={danger ? "button-danger" : "button-primary"}
            loadingText="处理中…"
            onClick={() => void onConfirm()}
            ref={confirmRef}
          >
            {confirmText}
          </AsyncActionButton>
        </div>
      </div>
    </div>
  );
}

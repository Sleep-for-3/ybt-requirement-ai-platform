"use client";

import { X } from "lucide-react";
import { useEffect, useRef } from "react";

export function ModalDialog({
  children,
  description,
  onClose,
  open,
  title
}: {
  children: React.ReactNode;
  description?: string;
  onClose: () => void;
  open: boolean;
  title: string;
}) {
  const closeRef = useRef<HTMLButtonElement>(null);
  const surfaceRef = useRef<HTMLElement>(null);

  const onCloseRef = useRef(onClose);
  useEffect(() => { onCloseRef.current = onClose; }, [onClose]);

  useEffect(() => {
    // Focus ownership is keyed on `open` alone. Re-running this effect while the dialog is
    // open stole focus back to the close control after the first keystroke, because every
    // parent render hands us a fresh `onClose` identity (GlobalSearch types into a
    // controlled input rendered beside this dialog).
    if (!open) return;
    const previous = document.activeElement as HTMLElement | null;
    // A control that declared autoFocus inside the dialog keeps it (search-first dialogs);
    // otherwise the close button stays the default landing target.
    if (!previous || !surfaceRef.current?.contains(previous)) closeRef.current?.focus();
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") onCloseRef.current();
    }
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      previous?.focus();
    };
  }, [open]);

  if (!open) return null;
  return (
    <div aria-modal="true" className="fixed inset-0 z-[90] flex items-center justify-center p-4" role="dialog" aria-labelledby="modal-dialog-title">
      <button aria-label="关闭弹窗" className="absolute inset-0 bg-slate-950/50 backdrop-blur-[1px]" onClick={onClose} type="button" />
      <section className="relative max-h-[calc(100vh-2rem)] w-full max-w-xl overflow-y-auto rounded-2xl border border-line bg-white shadow-pop" ref={surfaceRef}>
        <header className="flex items-start justify-between gap-4 border-b border-line px-5 py-4">
          <div>
            <h2 className="text-base font-semibold text-ink" id="modal-dialog-title">{title}</h2>
            {description ? <p className="mt-1 text-sm leading-5 text-slate-500">{description}</p> : null}
          </div>
          <button aria-label="关闭弹窗" className="button-ghost h-9 w-9 shrink-0 px-0" onClick={onClose} ref={closeRef} type="button"><X size={17} /></button>
        </header>
        <div className="p-5">{children}</div>
      </section>
    </div>
  );
}

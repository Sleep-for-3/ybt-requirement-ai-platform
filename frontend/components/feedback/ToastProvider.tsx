"use client";

import { AlertCircle, CheckCircle2, Info, LoaderCircle, TriangleAlert, X } from "lucide-react";
import { createContext, useCallback, useContext, useMemo, useRef, useState } from "react";

import { isRecentToast } from "@/lib/toast-dedupe.mjs";

export type ToastKind = "loading" | "success" | "warning" | "error" | "info";
export type ToastInput = {
  kind?: ToastKind;
  message: string;
  durationMs?: number;
};
type ToastItem = ToastInput & { id: number; kind: ToastKind };
type ToastApi = {
  close: (id: number) => void;
  show: (toast: ToastInput) => number;
  loading: (message: string) => number;
  success: (message: string) => number;
  warning: (message: string) => number;
  error: (message: string) => number;
  info: (message: string) => number;
};

const ToastContext = createContext<ToastApi | null>(null);
const ICONS = {
  loading: LoaderCircle,
  success: CheckCircle2,
  warning: TriangleAlert,
  error: AlertCircle,
  info: Info
};
const STYLES = {
  loading: "border-sky-200 bg-sky-50 text-sky-800",
  success: "border-emerald-200 bg-emerald-50 text-emerald-800",
  warning: "border-amber-200 bg-amber-50 text-amber-900",
  error: "border-coral-200 bg-coral-50 text-coral-800",
  info: "border-slate-200 bg-white text-slate-700"
};

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const sequence = useRef(0);
  const recent = useRef(new Map<string, { at: number; id: number }>());

  const close = useCallback((id: number) => {
    setItems((current) => current.filter((item) => item.id !== id));
  }, []);

  const show = useCallback((input: ToastInput) => {
    const kind = input.kind || "info";
    const key = `${kind}:${input.message}`;
    const now = Date.now();
    const previous = recent.current.get(key);
    if (previous && isRecentToast(previous.at, now)) return previous.id;
    const id = ++sequence.current;
    recent.current.set(key, { at: now, id });
    setItems((current) => [...current.slice(-4), { ...input, id, kind }]);
    const duration = input.durationMs ?? (kind === "error" ? 8_000 : kind === "loading" ? 0 : 4_000);
    if (duration > 0) {
      window.setTimeout(() => {
        setItems((current) => current.filter((item) => item.id !== id));
        if (recent.current.get(key)?.id === id) recent.current.delete(key);
      }, duration);
    }
    return id;
  }, []);

  const api = useMemo<ToastApi>(() => ({
    close,
    show,
    loading: (message) => show({ kind: "loading", message }),
    success: (message) => show({ kind: "success", message }),
    warning: (message) => show({ kind: "warning", message }),
    error: (message) => show({ kind: "error", message }),
    info: (message) => show({ kind: "info", message })
  }), [close, show]);

  return (
    <ToastContext.Provider value={api}>
      {children}
      <div aria-atomic="false" aria-live="polite" className="pointer-events-none fixed right-4 top-16 z-[100] flex w-[min(24rem,calc(100vw-2rem))] flex-col gap-2">
        {items.map((item) => {
          const Icon = ICONS[item.kind];
          return (
            <div className={`pointer-events-auto flex items-start gap-2 rounded-xl border px-3 py-2.5 shadow-pop ${STYLES[item.kind]}`} key={item.id} role={item.kind === "error" ? "alert" : "status"}>
              <Icon aria-hidden className={`mt-0.5 shrink-0 ${item.kind === "loading" ? "animate-spin" : ""}`} size={17} />
              <p className="min-w-0 flex-1 break-words text-sm leading-5">{item.message}</p>
              <button aria-label="关闭提示" className="rounded p-0.5 opacity-60 hover:bg-black/5 hover:opacity-100" onClick={() => close(item.id)} type="button">
                <X size={15} />
              </button>
            </div>
          );
        })}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast() {
  const value = useContext(ToastContext);
  if (!value) throw new Error("useToast 必须在 ToastProvider 内使用");
  return value;
}

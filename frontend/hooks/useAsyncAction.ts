"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { useToast } from "@/components/feedback/ToastProvider";
import { normalizeRequestError } from "@/lib/http-response.mjs";

export type AsyncActionStatus = "idle" | "submitting" | "queued" | "running" | "success" | "failed";
type Options<T> = {
  successMessage?: string | ((value: T) => string);
  onSuccess?: (value: T) => void | Promise<void>;
  onError?: (error: Error) => void;
};

export function useAsyncAction<T = void>(options: Options<T> = {}) {
  const [status, setStatus] = useState<AsyncActionStatus>("idle");
  const [error, setError] = useState<Error | null>(null);
  const runningRef = useRef(false);
  const mountedRef = useRef(true);
  const toast = useToast();
  const optionsRef = useRef(options);
  optionsRef.current = options;

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const run = useCallback(async (action: () => Promise<T>): Promise<T | undefined> => {
    if (runningRef.current) return undefined;
    runningRef.current = true;
    if (mountedRef.current) {
      setError(null);
      setStatus("submitting");
    }
    try {
      const value = await action();
      if (mountedRef.current) setStatus("success");
      const message = typeof optionsRef.current.successMessage === "function"
        ? optionsRef.current.successMessage(value)
        : optionsRef.current.successMessage;
      if (message) toast.success(message);
      await optionsRef.current.onSuccess?.(value);
      return value;
    } catch (cause) {
      const normalized = normalizeRequestError(cause);
      if (mountedRef.current) {
        setError(normalized);
        setStatus("failed");
      }
      toast.error(normalized.message);
      optionsRef.current.onError?.(normalized);
      return undefined;
    } finally {
      runningRef.current = false;
      if (mountedRef.current) setStatus("idle");
    }
  }, [toast]);

  return {
    error,
    isRunning: status === "submitting",
    run,
    setStatus,
    status
  };
}

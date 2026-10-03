"use client";

/**
 * B11: the React binding for the shared unsaved-changes registry.
 *
 * `useUnsavedChanges(ownerId, isDirty)` registers this editor while it holds unsaved work and
 * clears the registration on save or unmount, so several editors can be dirty at once.
 * `<UnsavedChangesGuard />` installs the tab-level guard (refresh/close) once for the app.
 */

import { useEffect } from "react";

import {
  beforeUnloadReturnValue,
  leaveDecision,
  registerDirty,
} from "@/lib/unsaved-changes.mjs";

export function useUnsavedChanges(ownerId: string, isDirty: boolean): void {
  useEffect(() => {
    if (!isDirty) return;
    return registerDirty(ownerId, true);
  }, [ownerId, isDirty]);
}

export function confirmLeave(): boolean {
  if (leaveDecision() === "allow") return true;
  return window.confirm("有未保存的编辑，确定要离开并丢失这些内容吗？");
}

export function UnsavedChangesGuard() {
  useEffect(() => {
    function handleBeforeUnload(event: BeforeUnloadEvent) {
      const value = beforeUnloadReturnValue();
      if (value === undefined) return;
      event.preventDefault();
      event.returnValue = value;
    }
    window.addEventListener("beforeunload", handleBeforeUnload);
    return () => window.removeEventListener("beforeunload", handleBeforeUnload);
  }, []);
  return null;
}

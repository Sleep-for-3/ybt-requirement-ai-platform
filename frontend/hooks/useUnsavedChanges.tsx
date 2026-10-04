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
  shouldInterceptNavigation,
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
    /**
     * B11: also intercept in-app link clicks. `beforeunload` never fires for a client-side route
     * change, so a sidebar <Link> used to drop the operator's edits with no prompt.
     */
    function handleClick(event: MouseEvent) {
      const anchor = (event.target as Element | null)?.closest?.("a[href]") as HTMLAnchorElement | null;
      if (!anchor) return;
      const decision = shouldInterceptNavigation({
        defaultPrevented: event.defaultPrevented,
        button: event.button,
        metaKey: event.metaKey,
        ctrlKey: event.ctrlKey,
        shiftKey: event.shiftKey,
        altKey: event.altKey,
        target: anchor.getAttribute("target"),
        href: anchor.getAttribute("href"),
        sameOrigin: anchor.origin === window.location.origin,
        skipGuard: anchor.hasAttribute("data-skip-unsaved-guard"),
      });
      if (!decision) return;
      if (!confirmLeave()) event.preventDefault();
    }
    window.addEventListener("beforeunload", handleBeforeUnload);
    document.addEventListener("click", handleClick, true);
    return () => {
      window.removeEventListener("beforeunload", handleBeforeUnload);
      document.removeEventListener("click", handleClick, true);
    };
  }, []);
  return null;
}

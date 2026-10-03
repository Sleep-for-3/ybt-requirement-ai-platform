/**
 * B11: one place that knows whether any editor holds unsaved work.
 *
 * Before this, each editor tracked its own `dirty` flag with no shared registration, so the app
 * could navigate away, switch project/field or close the tab and silently drop the operator's
 * edits. This module is framework-free so the rule itself is unit-testable; the React binding
 * lives in hooks/useUnsavedChanges.
 */

const owners = new Map();

/** Register one owner's dirty state; returns a disposer that removes it. */
export function registerDirty(ownerId, isDirty) {
  if (isDirty) owners.set(ownerId, true);
  else owners.delete(ownerId);
  return () => owners.delete(ownerId);
}

export function clearOwner(ownerId) {
  owners.delete(ownerId);
}

export function resetForTests() {
  owners.clear();
}

export function hasUnsavedChanges() {
  return owners.size > 0;
}

export function dirtyOwners() {
  return [...owners.keys()].sort();
}

export const UNSAVED_MESSAGE = "有未保存的编辑，离开将丢失这些内容。";

/**
 * What to do when a navigation is attempted.
 * `allow` -> proceed, `confirm` -> ask the operator (save / discard / cancel).
 * Fail-safe: any unsaved editor blocks the navigation.
 */
export function leaveDecision() {
  return hasUnsavedChanges() ? "confirm" : "allow";
}

/** The value a beforeunload handler must return to trigger the browser prompt. */
export function beforeUnloadReturnValue() {
  return hasUnsavedChanges() ? UNSAVED_MESSAGE : undefined;
}

/** Local draft persistence: keep the unfinished body so a reload can restore it. */
export function draftKey(scope) {
  return `draft:${scope}`;
}

export function saveDraft(storage, scope, payload) {
  try {
    storage.setItem(draftKey(scope), JSON.stringify({ savedAt: new Date().toISOString(), payload }));
    return true;
  } catch {
    return false;
  }
}

export function readDraft(storage, scope) {
  try {
    const raw = storage.getItem(draftKey(scope));
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === "object" && "payload" in parsed ? parsed : null;
  } catch {
    return null;
  }
}

export function clearDraft(storage, scope) {
  try {
    storage.removeItem(draftKey(scope));
    return true;
  } catch {
    return false;
  }
}

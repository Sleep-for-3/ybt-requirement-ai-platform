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

/**
 * B11: does an in-app link click need the unsaved-changes prompt?
 *
 * `beforeunload` covers reload/close and the project/requirement switches call confirmLeave()
 * explicitly, but a plain <Link> click used to navigate away and silently drop the operator's
 * edits. Only an unmodified plain left click on a same-app link is intercepted: modified clicks
 * (new tab/window, download, middle click), external links, hash-only jumps, links that already
 * handled the event and links tagged `data-skip-unsaved-guard` are left to the browser.
 */
export function shouldInterceptNavigation(click) {
  if (!click || click.defaultPrevented) return false;
  if (click.button !== 0) return false;
  if (click.metaKey || click.ctrlKey || click.shiftKey || click.altKey) return false;
  if (click.target && click.target !== "_self") return false;
  const href = click.href || "";
  if (!href || href.startsWith("#")) return false;
  if (click.sameOrigin === false) return false;
  if (click.skipGuard) return false;
  return true;
}

/** Local draft persistence: keep the unfinished body so a reload can restore it. */
/**
 * C02: 草稿必须按**账号**隔离。
 *
 * 原键 `draft:${scope}` 不含 actor，所以同一项目/同一 Skill 下，A 未保存的私有正文
 * 会被 B 读到并可恢复。新键把可信登录用户 ID 编入命名空间；未取得身份时不拼 key。
 */
export function draftKey(scope, actorId) {
  const actor = actorId === null || actorId === undefined || actorId === "" ? null : String(actorId);
  return actor === null ? null : `draft:actor:${actor}:${scope}`;
}

export function saveDraft(storage, scope, payload, actorId) {
  const key = draftKey(scope, actorId);
  if (!key) return false;
  try {
    // C02: 草稿本身也记录 owner，读取与恢复都校验；跨账号即使拿到 key 也不能自动归属。
    storage.setItem(key, JSON.stringify({
      savedAt: new Date().toISOString(), owner: String(actorId), payload
    }));
    return true;
  } catch {
    return false;
  }
}

export function readDraft(storage, scope, actorId) {
  const key = draftKey(scope, actorId);
  if (!key) return null;
  try {
    const raw = storage.getItem(key);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object" || !("payload" in parsed)) return null;
    // C02: 历史无 owner 的草稿不得自动归属当前登录者。
    if (typeof parsed.owner !== "string" || parsed.owner !== String(actorId)) return null;
    return parsed;
  } catch {
    return null;
  }
}

export function clearDraft(storage, scope, actorId) {
  const key = draftKey(scope, actorId);
  if (!key) return false;
  try {
    storage.removeItem(key);
    return true;
  } catch {
    return false;
  }
}

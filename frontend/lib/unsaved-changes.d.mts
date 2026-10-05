export function registerDirty(ownerId: string, isDirty: boolean): () => void;
export function clearOwner(ownerId: string): void;
export function resetForTests(): void;
export function hasUnsavedChanges(): boolean;
export function dirtyOwners(): string[];
export const UNSAVED_MESSAGE: string;
export function leaveDecision(): "allow" | "confirm";
export function beforeUnloadReturnValue(): string | undefined;
export function shouldInterceptNavigation(click: {
  defaultPrevented?: boolean;
  button?: number;
  metaKey?: boolean;
  ctrlKey?: boolean;
  shiftKey?: boolean;
  altKey?: boolean;
  target?: string | null;
  href?: string | null;
  sameOrigin?: boolean;
  skipGuard?: boolean;
} | null | undefined): boolean;
// C02: 草稿按可信登录用户 ID 隔离；未取得身份时 draftKey 返回 null，读写均被拒绝。
export type DraftActorId = number | string | null | undefined;
export function draftKey(scope: string, actorId: DraftActorId): string | null;
export function saveDraft(storage: Storage, scope: string, payload: unknown, actorId: DraftActorId): boolean;
export function readDraft(
  storage: Storage,
  scope: string,
  actorId: DraftActorId
): { savedAt?: string; owner?: string; payload: unknown } | null;
export function clearDraft(storage: Storage, scope: string, actorId: DraftActorId): boolean;

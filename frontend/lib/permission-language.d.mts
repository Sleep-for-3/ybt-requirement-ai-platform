export type PermissionLanguageEntry = { label: string; description?: string; group?: string };
export declare const permissionLanguage: {
  institutionRoles: Record<string, PermissionLanguageEntry>;
  projectRoles: Record<string, PermissionLanguageEntry>;
  permissions: Record<string, PermissionLanguageEntry>;
  groupOrder: string[];
};
export function institutionRoleLabel(code: string): string;
export function projectRoleLabel(code: string): string;
export function projectRoleDescription(code: string): string;
export function permissionLabel(code: string): string;
export function permissionGroup(code: string): string;
export function groupPermissions(codes: string[]): Array<{ group: string; permissions: Array<{ code: string; label: string; configured: boolean }> }>;

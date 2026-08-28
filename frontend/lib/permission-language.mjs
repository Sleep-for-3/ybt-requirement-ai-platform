import language from "./permission-language.json" with { type: "json" };

const UNKNOWN = "未配置中文名称";

export const permissionLanguage = language;

export function institutionRoleLabel(code) {
  return language.institutionRoles[code]?.label || UNKNOWN;
}

export function projectRoleLabel(code) {
  return language.projectRoles[code]?.label || UNKNOWN;
}

export function projectRoleDescription(code) {
  return language.projectRoles[code]?.description || "该角色尚未配置产品说明";
}

export function permissionLabel(code) {
  return language.permissions[code]?.label || UNKNOWN;
}

export function permissionGroup(code) {
  return language.permissions[code]?.group || "系统";
}

export function groupPermissions(codes) {
  const grouped = new Map();
  for (const code of codes) {
    const group = permissionGroup(code);
    if (!grouped.has(group)) grouped.set(group, []);
    grouped.get(group).push({ code, label: permissionLabel(code), configured: Boolean(language.permissions[code]) });
  }
  return language.groupOrder
    .filter((group) => grouped.has(group))
    .map((group) => ({ group, permissions: grouped.get(group) }));
}

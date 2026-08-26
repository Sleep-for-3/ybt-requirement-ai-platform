export type NavigationAudience = "technical" | "admin";

export type NavigationAccess = {
  isAdmin: boolean;
  isTechnical: boolean;
};

export type NavigationAuth = {
  effective_project_permissions?: Record<string, string[]>;
  institution_memberships?: Array<{
    institution_id?: number;
    role?: string;
    status?: string;
  }>;
};

export function navigationAccessForProject(
  auth: NavigationAuth | null | undefined,
  projectId: number | null | undefined
): NavigationAccess;

export function canViewNavigationAudience(
  audience: NavigationAudience | undefined,
  access: NavigationAccess
): boolean;

export function navigationTrailForPath(pathname: string): {
  parentHref: string | null;
  sectionHref: string | null;
  sectionLabel: string | null;
};

export function parentReturnHref(parentHref: string | null, queryString?: string): string | null;
export function detailHrefWithReturnTo(detailHref: string, listPath: string, listQuery?: string): string;

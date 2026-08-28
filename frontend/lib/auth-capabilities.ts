export type AuthCapabilities = {
  can_view_admin: boolean;
  can_manage_institutions: boolean;
  can_manage_users: boolean;
  can_view_permission_matrix: boolean;
  can_view_platform_health: boolean;
  can_view_institution_cockpit: boolean;
  can_view_all_projects: boolean;
};

export type AuthMe = {
  id: number;
  username: string;
  display_name?: string | null;
  effective_project_permissions?: Record<string, string[]>;
  capabilities: AuthCapabilities;
};

export const NO_CAPABILITIES: AuthCapabilities = {
  can_view_admin: false,
  can_manage_institutions: false,
  can_manage_users: false,
  can_view_permission_matrix: false,
  can_view_platform_health: false,
  can_view_institution_cockpit: false,
  can_view_all_projects: false,
};

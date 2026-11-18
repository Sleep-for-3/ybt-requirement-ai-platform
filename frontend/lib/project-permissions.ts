"use client";

import { useEffect, useMemo, useState } from "react";

import { apiGet, hasSession } from "@/lib/api";

type AuthMe = { project_memberships:Array<{project_id:number;project_role:string;status:string}>;effective_project_permissions:Record<string,string[]> };

export function useProjectPermissions(projectId:number|null|undefined) {
  const [scope, setScope] = useState<{ projectId: number; role: string | null; effective: string[]; legacy: boolean } | null>(null);
  useEffect(() => {
    if (!projectId) return;
    const controller = new AbortController();
    void apiGet<AuthMe>("/auth/me", { signal: controller.signal }).then(me => {
      if (controller.signal.aborted) return;
      const projectRole = me.project_memberships.find(item => item.project_id === projectId && item.status === "active")?.project_role;
      setScope({ projectId, role: projectRole || null, effective: me.effective_project_permissions[String(projectId)] || [], legacy: false });
    }).catch(() => {
      if (!controller.signal.aborted) setScope({ projectId, role: null, effective: [], legacy: !hasSession() });
    });
    return () => controller.abort();
  }, [projectId]);
  return useMemo(() => {
    const active = scope?.projectId === projectId ? scope : null;
    const permissions = new Set(active?.effective);
    return { ready: Boolean(active), role: active?.legacy ? "legacy_system" : active?.role ?? null, can:(permission:string) => Boolean(active?.legacy || permissions.has(permission)) };
  }, [projectId, scope]);
}

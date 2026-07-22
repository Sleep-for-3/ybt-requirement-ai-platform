"use client";

import { useEffect, useMemo, useState } from "react";

import { apiGet, hasSession } from "@/lib/api";

type AuthMe = { project_memberships:Array<{project_id:number;project_role:string;status:string}>;effective_project_permissions:Record<string,string[]> };

export function useProjectPermissions(projectId:number|null|undefined) {
  const [role, setRole] = useState<string | null>(null);
  const [effective, setEffective] = useState<string[]>([]);
  const [legacy, setLegacy] = useState(false);
  useEffect(() => {
    if (!projectId) { setRole(null); setEffective([]); setLegacy(false); return; }
    void apiGet<AuthMe>("/auth/me").then(me => {
      const projectRole = me.project_memberships.find(item => item.project_id === projectId && item.status === "active")?.project_role;
      setRole(projectRole || null);
      setEffective(me.effective_project_permissions[String(projectId)] || []);
      setLegacy(false);
    }).catch(() => { setRole(null); setEffective([]); setLegacy(!hasSession()); });
  }, [projectId]);
  return useMemo(() => {
    const permissions = new Set(effective);
    return { role: legacy ? "legacy_system" : role, can:(permission:string) => legacy || permissions.has(permission) };
  }, [effective, legacy, role]);
}

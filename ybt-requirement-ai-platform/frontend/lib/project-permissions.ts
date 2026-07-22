"use client";

import { useEffect, useMemo, useState } from "react";

import { apiGet, hasSession } from "@/lib/api";

type AuthMe = { institution_memberships:Array<{role:string;status:string}>;project_memberships:Array<{project_id:number;project_role:string;status:string}> };

const FULL = new Set(["template.manage","deliverable.manage","deliverable.generate","deliverable.review","deliverable.export","question.manage","question.answer","historical.import","historical.reuse"]);

const ROLE_PERMISSIONS: Record<string, Set<string>> = {
  project_manager: new Set(["template.manage","deliverable.manage","deliverable.generate","deliverable.review","deliverable.export","question.manage","question.answer","historical.import","historical.reuse"]),
  business_analyst: new Set(["deliverable.generate","question.answer"]),
  technical_analyst: new Set(["deliverable.generate","question.answer"]),
  business_reviewer: new Set([]),
  technical_reviewer: new Set([]),
  final_reviewer: new Set(["deliverable.review","deliverable.export"]),
  knowledge_manager: new Set(["historical.import","historical.reuse"]),
  data_catalog_manager: new Set([]),
  viewer: new Set([]),
  auditor: new Set(["deliverable.export"]),
  institution_admin: FULL,
  legacy_system: FULL,
};

export function useProjectPermissions(projectId:number|null|undefined) {
  const [role, setRole] = useState<string | null>(null);
  useEffect(() => {
    if (!projectId) { setRole(null); return; }
    void apiGet<AuthMe>("/auth/me").then(me => {
      const projectRole = me.project_memberships.find(item => item.project_id === projectId && item.status === "active")?.project_role;
      const institutionAdmin = me.institution_memberships.some(item => item.status === "active" && ["institution_admin","security_admin"].includes(item.role));
      setRole(projectRole || (institutionAdmin ? "institution_admin" : null));
    }).catch(() => setRole(hasSession() ? null : "legacy_system"));
  }, [projectId]);
  return useMemo(() => ({ role, can:(permission:string) => Boolean(role && ROLE_PERMISSIONS[role]?.has(permission)) }), [role]);
}

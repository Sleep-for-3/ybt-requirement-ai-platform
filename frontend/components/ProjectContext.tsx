"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

import { Project, apiGet } from "@/lib/api";

type ProjectContextValue = {
  projects: Project[];
  projectId: number | null;
  selectedProject: Project | null;
  selectProject: (projectId: number | null) => void;
  refreshProjects: () => Promise<void>;
};

const ProjectContext = createContext<ProjectContextValue | null>(null);
const STORAGE_KEY = "ybt:selected-project-id";

export function ProjectProvider({ children }: { children: React.ReactNode }) {
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectId, setProjectId] = useState<number | null>(null);

  const selectProject = useCallback((nextProjectId: number | null) => {
    setProjectId(nextProjectId);
    if (nextProjectId) localStorage.setItem(STORAGE_KEY, String(nextProjectId));
    else localStorage.removeItem(STORAGE_KEY);
  }, []);

  const refreshProjects = useCallback(async () => {
    const items = await apiGet<Project[]>("/projects");
    setProjects(items);
    setProjectId((current) => {
      const requested = Number(new URLSearchParams(window.location.search).get("projectId")) || null;
      const stored = Number(localStorage.getItem(STORAGE_KEY)) || null;
      const candidate = requested || current || stored;
      const next = candidate && items.some((item) => item.id === candidate) ? candidate : items[0]?.id || null;
      if (next) localStorage.setItem(STORAGE_KEY, String(next));
      return next;
    });
  }, []);

  useEffect(() => { void refreshProjects(); }, [refreshProjects]);

  const value = useMemo<ProjectContextValue>(() => ({
    projects,
    projectId,
    selectedProject: projects.find((item) => item.id === projectId) || null,
    selectProject,
    refreshProjects,
  }), [projectId, projects, refreshProjects, selectProject]);

  return <ProjectContext.Provider value={value}>{children}</ProjectContext.Provider>;
}

export function useProjectWorkspace() {
  const context = useContext(ProjectContext);
  if (!context) throw new Error("useProjectWorkspace must be used inside ProjectProvider");
  return context;
}

export function ProjectSelector({ className = "w-56" }: { className?: string }) {
  const { projects, projectId, selectProject } = useProjectWorkspace();
  return (
    <select
      aria-label="当前项目"
      className={`control ${className}`}
      onChange={(event) => selectProject(Number(event.target.value) || null)}
      value={projectId || ""}
    >
      <option value="">选择项目</option>
      {projects.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}
    </select>
  );
}

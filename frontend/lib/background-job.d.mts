import type { BackgroundJobSummary } from "./types";

export function isTerminalJob(job: Pick<BackgroundJobSummary, "status">): boolean;
export function describeKnowledgeJob(
  job: Pick<BackgroundJobSummary, "status" | "progress" | "current_step" | "error_message">
): string;

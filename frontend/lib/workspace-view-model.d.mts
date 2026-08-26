import type {
  MartField,
  MartTable,
  MartToYbtMapping,
  PendingQuestion,
  ScenarioBusinessMapping,
  ScenarioTechnicalLineage,
  SourceToMartMapping,
  TargetField
} from "./types";

type ContentMapping = Partial<ScenarioBusinessMapping & ScenarioTechnicalLineage & SourceToMartMapping & MartToYbtMapping>;

export function preferredMappingContent(mapping?: ContentMapping | null, fallback?: string): string;
export function combinedFieldStatus(input: { businessStatus?: string | null; technicalStatus?: string | null; martStatuses?: Array<string | null | undefined> }): string;
export function mappingStatusLabel(status?: string | null): string;
export function mappingStatusTone(status?: string | null): "success" | "danger" | "warning" | "info" | "neutral";
export function isMappingLocked(status?: string | null): boolean;
export function isQuestionOpen(question?: PendingQuestion | null): boolean;
export function buildLineageLabels(input: {
  lineage?: ScenarioTechnicalLineage | null;
  sourceToMart?: SourceToMartMapping | null;
  martField?: MartField | null;
  martTable?: MartTable | null;
  targetField?: TargetField | null;
}): { source: string; mart: string; target: string };

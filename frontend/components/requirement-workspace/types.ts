import type {
  MartToYbtMapping,
  ScenarioBusinessMapping,
  ScenarioTechnicalLineage,
  SourceToMartMapping,
  TargetField
} from "@/lib/api";

export type FieldWorkspaceRecord = {
  field: TargetField;
  business: ScenarioBusinessMapping | null;
  lineage: ScenarioTechnicalLineage | null;
  martMappings: MartToYbtMapping[];
};

export type SourceMappingIndex = Record<number, SourceToMartMapping[]>;
export type SaveState = "idle" | "dirty" | "saving" | "saved" | "error";

/**
 * Type declarations for ``lineage-graph.mjs``.
 *
 * ``tsconfig.json`` sets ``allowJs: false``, so Next.js refuses to compile any
 * TypeScript import of the runtime ``.mjs`` module until a matching ``.d.mts``
 * declaration exists next to it.  Behaviour is covered by
 * ``frontend/tests/lineage-graph.test.mjs``.
 */

export declare const TRUNCATION_LABELS: Readonly<Record<string, string>>;

export interface TraversalInfo {
  mode: string;
  label: string;
  detail: string;
  truncated: boolean;
  truncationReason: string | null;
  tone: "warning" | "neutral";
}

export function describeTraversal(graph: unknown): TraversalInfo;

export function truncationLabels(): Record<string, string>;

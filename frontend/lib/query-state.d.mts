export type QueryKind = "loading" | "forbidden" | "offline" | "error" | "empty" | "ready";

export type QueryState = {
  kind: QueryKind;
  status: number | null;
  message: string;
};

export const QUERY_KIND: Readonly<Record<QueryKind, QueryKind>>;

export function classifyQueryState(input: {
  isPending?: boolean;
  isError?: boolean;
  error?: unknown;
  hasData?: boolean;
  itemCount?: number;
}): QueryState;

export function isRetryable(kind: QueryKind): boolean;

export function withLastSuccess<T>(
  previous: { data: T; at: string | null } | null,
  incoming: { data?: T | null; at?: string | null } | null | undefined,
): { data: T; at: string | null } | null;

export function lastSuccessLabel(state: { data: unknown; at: string | null } | null): string;

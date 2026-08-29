import { QueryClient } from "@tanstack/react-query";

import { GLOBAL_STALE_TIME_MS } from "@/lib/query-policy.mjs";

let browserClient: QueryClient | undefined;

function createQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: GLOBAL_STALE_TIME_MS,
        gcTime: 10 * 60_000,
        refetchOnWindowFocus: false,
        refetchOnReconnect: true,
        retry: (failureCount, error) => {
          const status = typeof error === "object" && error && "status" in error ? Number(error.status) : 0;
          if ([400, 401, 403, 404, 409, 422].includes(status)) return false;
          return failureCount < 2;
        },
        retryDelay: (attempt) => Math.min(1_000 * 2 ** attempt, 8_000)
      }
    }
  });
}

export function getQueryClient() {
  if (typeof window === "undefined") return createQueryClient();
  browserClient ||= createQueryClient();
  return browserClient;
}

export function clearQueryCache() {
  browserClient?.clear();
}

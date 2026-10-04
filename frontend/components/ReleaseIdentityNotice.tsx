"use client";

/**
 * B18: surface a mixed-version release instead of letting it stay invisible.
 *
 * The identity helpers and their tests already existed, but nothing called them from the UI, so a
 * frontend built from one commit talking to an API/worker on another looked perfectly normal. This
 * notice compares this build's inlined identity with what the API reports and renders only when they
 * disagree (or when either side is unknown) - it stays silent on a consistent release.
 */

import { useQuery } from "@tanstack/react-query";

import { apiGet } from "@/lib/api";
import { frontendIdentity, identityMismatches, type ReleaseIdentity } from "@/lib/build-info";

export function ReleaseIdentityNotice() {
  const versionQuery = useQuery({
    queryKey: ["release-identity"],
    queryFn: ({ signal }) => apiGet<ReleaseIdentity>("/version", { signal }),
    staleTime: 60_000,
  });
  if (!versionQuery.data) return null;
  const mismatches = identityMismatches(frontendIdentity(), versionQuery.data);
  if (mismatches.length === 0) return null;
  return (
    <p className="text-[11px] text-amber-700" role="status" data-testid="release-identity-mismatch">
      前后端发布标识不一致（{mismatches.join("；")}），请联系运维核对本次发布。
    </p>
  );
}

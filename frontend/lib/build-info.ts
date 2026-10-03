/**
 * B18: the frontend half of the release identity contract.
 *
 * The deployed frontend must be able to state which commit/build it is and compare that with
 * what the API, worker and beat report, so a mixed-version release is detectable instead of
 * silent. Values are inlined at build time through NEXT_PUBLIC_* (no secrets).
 */

export const UNKNOWN = "unknown";

export type ReleaseIdentity = {
  component: string;
  app_commit: string;
  build_time: string;
  schema_head: string | null;
};

export function frontendIdentity(): ReleaseIdentity {
  return {
    component: "frontend",
    app_commit: process.env.NEXT_PUBLIC_APP_COMMIT || UNKNOWN,
    build_time: process.env.NEXT_PUBLIC_BUILD_TIME || UNKNOWN,
    schema_head: process.env.NEXT_PUBLIC_SCHEMA_HEAD || null,
  };
}

/** Compare the frontend with an API/worker report on the fields that must agree. */
export function identityMismatches(
  frontend: ReleaseIdentity,
  remote: ReleaseIdentity,
): string[] {
  const mismatches: string[] = [];
  if (frontend.app_commit === UNKNOWN || remote.app_commit === UNKNOWN) {
    mismatches.push("app_commit:unknown");
  } else if (frontend.app_commit !== remote.app_commit) {
    mismatches.push(`app_commit:${frontend.app_commit}!=${remote.app_commit}`);
  }
  if (frontend.build_time === UNKNOWN || remote.build_time === UNKNOWN) {
    mismatches.push("build_time:unknown");
  }
  if (
    frontend.schema_head &&
    remote.schema_head &&
    frontend.schema_head !== remote.schema_head
  ) {
    mismatches.push(`schema_head:${frontend.schema_head}!=${remote.schema_head}`);
  }
  return mismatches;
}

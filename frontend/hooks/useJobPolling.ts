"use client";

import { useEffect, useRef, useState } from "react";

import { apiGet, BackgroundJobSummary } from "@/lib/api";
import { createJobPollingRegistry } from "@/lib/job-polling.mjs";

const pollingRegistry = createJobPollingRegistry({
  fetchJob: (jobId: number) => apiGet<BackgroundJobSummary>(`/jobs/${jobId}`)
});

type Options = {
  enabled?: boolean;
  initialJob?: BackgroundJobSummary | null;
  onTerminal?: (job: BackgroundJobSummary) => void | Promise<void>;
};

export function useJobPolling(jobId: number | null | undefined, options: Options = {}) {
  const [job, setJob] = useState<BackgroundJobSummary | null>(options.initialJob || null);
  const terminalRef = useRef(options.onTerminal);
  terminalRef.current = options.onTerminal;

  useEffect(() => {
    if (options.initialJob) setJob(options.initialJob);
  }, [options.initialJob]);

  useEffect(() => {
    if (!jobId || options.enabled === false) return;
    return pollingRegistry.subscribe(jobId, (next: BackgroundJobSummary) => {
      setJob(next);
      if (["completed", "failed", "partially_completed", "cancelled", "timed_out"].includes(next.status)) {
        void terminalRef.current?.(next);
      }
    });
  }, [jobId, options.enabled]);

  return job;
}

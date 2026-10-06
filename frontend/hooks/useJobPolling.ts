"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { apiGet, BackgroundJobSummary } from "@/lib/api";
import { createJobPollingRegistry } from "@/lib/job-polling.mjs";

const pollingRegistry = createJobPollingRegistry({
  fetchJob: (jobId: number) => apiGet<BackgroundJobSummary>(`/jobs/${jobId}`),
  // C11: 断网达到上限后停轮询，但必须让界面拿到“后台任务状态暂时无法更新、可重试”的信号。
  onPollingError: (error: Error) => {
    pollingUnavailable = error.message;
  }
});

// C11: 模块级的可见状态；界面可读它显示提示条，并调 resumeJobPolling 手动恢复。
let pollingUnavailable: string | null = null;

export function jobPollingUnavailable(): string | null {
  return pollingUnavailable;
}

export function resumeJobPolling(jobId: number | null | undefined): boolean {
  if (!jobId) return false;
  const resumed = pollingRegistry.resume(jobId);
  if (resumed) pollingUnavailable = null;
  return resumed;
}

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

/**
 * C11: 轮询因连续失败而停止时，界面需要在**不改变原有返回值**的前提下拿到可见状态与恢复入口。
 *
 * 旧行为是：连续 maxErrors 次失败后直接删掉订阅，于是网络/可见性恢复也不再查询，
 * 界面永久停在旧状态且没有任何提示。现在 registry 会保留订阅并由 online/visibility 自动重拉，
 * 这个 hook 只负责把“当前是否仍不可用”暴露给需要显示提示条的页面。
 */
export function useJobPollingStatus(jobId: number | null | undefined) {
  const [unavailable, setUnavailable] = useState<string | null>(() => pollingUnavailable);

  useEffect(() => {
    setUnavailable(pollingUnavailable);
    const timer = setInterval(() => setUnavailable(pollingUnavailable), 1000);
    return () => clearInterval(timer);
  }, [jobId]);

  const resume = useCallback(() => {
    if (resumeJobPolling(jobId)) setUnavailable(null);
  }, [jobId]);

  return { unavailable, resume };
}

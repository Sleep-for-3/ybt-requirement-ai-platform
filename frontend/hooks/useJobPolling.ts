"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { apiGet, BackgroundJobSummary } from "@/lib/api";
import { createJobPollingRegistry } from "@/lib/job-polling.mjs";

const pollingRegistry = createJobPollingRegistry({
  fetchJob: (jobId: number) => apiGet<BackgroundJobSummary>(`/jobs/${jobId}`),
  // C11: 断网达到上限后停轮询，但必须让界面拿到“后台任务状态暂时无法更新、可重试”的信号。
  onPollingError: () => {
    // R08: 错误状态由 registry **按 job** 保存（errorFor），这里不再写模块级全局变量，
    // 也不再把提示串到无关 job 上。
  }
});

// R08: 退出/切换账号时清空全部轮询状态（含各 job 的错误提示与最后成功时间）。
export function resetJobPollingState(): void {
  pollingRegistry.reset();
}

export function resumeJobPolling(jobId: number | null | undefined): boolean {
  if (!jobId) return false;
  return pollingRegistry.recover(jobId);
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
 * C11/R08: 轮询因连续失败而停止时，界面需要在**不改变原有返回值**的前提下拿到
 * 该任务自己的可见状态与恢复入口。
 *
 * R08 修正：状态**按 job 归属**（registry.errorFor/lastSuccessAt），不再是一个模块级字符串：
 * 旧实现下一个 job 的故障会把其他 job 也标成故障，而且恢复后也不会清掉。
 * 清理时机：拿到状态、终态、解除订阅、以及退出/切换账号（resetJobPollingState）。
 */
export function useJobPollingStatus(jobId: number | null | undefined) {
  const [unavailable, setUnavailable] = useState<string | null>(null);
  const [lastSuccessAt, setLastSuccessAt] = useState<number | null>(null);

  useEffect(() => {
    const sync = () => {
      setUnavailable(pollingRegistry.errorFor(jobId ?? -1));
      setLastSuccessAt(pollingRegistry.lastSuccessAt(jobId ?? -1));
    };
    sync();
    return pollingRegistry.subscribeState(sync);
  }, [jobId]);

  const resume = useCallback(() => {
    if (pollingRegistry.recover(jobId ?? -1)) setUnavailable(null);
  }, [jobId]);

  return { unavailable, lastSuccessAt, resume };
}

const TERMINAL_JOB_STATUSES = new Set([
  "completed",
  "failed",
  "partially_completed",
  "cancelled",
  "timed_out"
]);

export function isTerminalJobStatus(status) {
  return TERMINAL_JOB_STATUSES.has(status);
}

export function createJobPollingRegistry(options) {
  const entries = new Map();
  const setTimer = options.setTimer || ((callback, delay) => setTimeout(callback, delay));
  const clearTimer = options.clearTimer || ((token) => clearTimeout(token));
  const isHidden = options.isHidden || (() => typeof document !== "undefined" && document.hidden);
  const subscribeVisibility = options.subscribeVisibility || ((listener) => {
    if (typeof document === "undefined") return () => undefined;
    document.addEventListener("visibilitychange", listener);
    return () => document.removeEventListener("visibilitychange", listener);
  });
  // C11: 网络恢复信号（浏览器 online）。"断网后永久停止" 是本项要修的缺陷，
  // 所以除了可见性，还要能感知重连。
  const subscribeOnline = options.subscribeOnline || ((listener) => {
    if (typeof window === "undefined" || !window.addEventListener) return () => undefined;
    window.addEventListener("online", listener);
    return () => window.removeEventListener("online", listener);
  });
  const maxErrors = options.maxErrors ?? 3;
  let unsubscribeVisibility;
  let unsubscribeOnline;

  // C11: "停止轮询" 与 "丢弃订阅" 是两件事。
  // 旧实现达到 maxErrors 后直接 remove()，条目被删除，网络/可见性恢复也再也不会查询 ——
  // 界面就永久停在旧状态且没有任何错误提示。现在改为：达到上限只把条目置为 failed（停轮询、
  // 保留 listeners），并由 online / visibility 或手动 resume() 把它拉回活动状态。
  function releaseListeners() {
    if (entries.size !== 0) return;
    if (unsubscribeVisibility) {
      unsubscribeVisibility();
      unsubscribeVisibility = undefined;
    }
    if (unsubscribeOnline) {
      unsubscribeOnline();
      unsubscribeOnline = undefined;
    }
  }

  function resumeStalled() {
    for (const [jobId, entry] of entries) {
      if (entry.failed && !entry.inFlight && !entry.timer && entry.listeners.size > 0) {
        entry.failed = false;
        entry.errors = 0;
        void poll(jobId, entry);
      }
    }
  }

  function handleVisibilityChange() {
    if (isHidden()) {
      for (const entry of entries.values()) {
        if (entry.timer) clearTimer(entry.timer);
        entry.timer = undefined;
      }
      return;
    }
    for (const [jobId, entry] of entries) {
      if (!entry.inFlight && !entry.timer && entry.listeners.size > 0) void poll(jobId, entry);
    }
  }

  function ensureVisibilityListener() {
    if (!unsubscribeVisibility) unsubscribeVisibility = subscribeVisibility(handleVisibilityChange);
    // C11: 网络恢复后必须重新拉取，否则断网期间的失败就成了永久停轮询。
    if (!unsubscribeOnline) unsubscribeOnline = subscribeOnline(resumeStalled);
  }


  function remove(jobId, entry) {
    if (entry.timer) clearTimer(entry.timer);
    entry.timer = undefined;
    if (entries.get(jobId) === entry) entries.delete(jobId);
    releaseListeners();
  }

  function schedule(jobId, entry, delay) {
    if (!entries.has(jobId) || entry.listeners.size === 0 || isHidden() || entry.failed) return;
    entry.timer = setTimer(() => poll(jobId, entry), delay);
  }

  async function poll(jobId, entry) {
    if (entries.get(jobId) !== entry || entry.listeners.size === 0 || entry.inFlight || isHidden()) return;
    // C11: 定时器已经触发，清掉令牌；否则 entry.timer 会留下陈旧值，
    // 使“重新订阅/重连时立即拉一次”的判断永远不成立。
    entry.timer = undefined;
    entry.inFlight = true;
    try {
      const job = await options.fetchJob(jobId);
      entry.errors = 0;
      entry.pollCount += 1;
      for (const listener of entry.listeners) listener(job);
      if (isTerminalJobStatus(job.status)) {
        remove(jobId, entry);
        return;
      }
      const delay = entry.pollCount > 30 ? 5000 : entry.pollCount > 15 ? 3000 : 2000;
      schedule(jobId, entry, delay);
    } catch {
      entry.errors += 1;
      if (entry.errors >= maxErrors) {
        // C11: 不删除条目；标记为 failed（有界退避已用尽），保留 listeners 供恢复。
        entry.failed = true;
        options.onPollingError?.(new Error("后台任务状态暂时无法更新"), { jobId, canResume: true });
        return;
      }
      // C11: 有界退避（上限仍为 5s），不允许无限高频重试。
      schedule(jobId, entry, Math.min(5000, 2000 + entry.errors * 1000));
    } finally {
      entry.inFlight = false;
    }
  }

  return {
    size: () => entries.size,
    // C11: 供界面"重试"按钮/状态查询使用。
    isStalled: (jobId) => Boolean(entries.get(jobId)?.failed),
    resume(jobId) {
      const entry = entries.get(jobId);
      if (!entry || !entry.failed || entry.inFlight || entry.listeners.size === 0) return false;
      entry.failed = false;
      entry.errors = 0;
      void poll(jobId, entry);
      return true;
    },
    subscribe(jobId, listener) {
      let entry = entries.get(jobId);
      if (!entry) {
        entry = {
          errors: 0,
          failed: false,
          inFlight: false,
          listeners: new Set(),
          pollCount: 0,
          timer: undefined
        };
        entries.set(jobId, entry);
      }
      entry.listeners.add(listener);
      ensureVisibilityListener();
      // C11: 断网期间重新订阅（例如从其他页返回）必须立即拉一次，
      // 否则已 failed 的条目会一直停在旧状态。
      if (!entry.inFlight && !entry.timer && !isHidden()
          && (entry.pollCount === 0 || entry.failed)) {
        entry.failed = false;
        entry.errors = 0;
        void poll(jobId, entry);
      }
      return () => {
        entry.listeners.delete(listener);
        if (entry.listeners.size === 0) remove(jobId, entry);
      };
    }
  };
}

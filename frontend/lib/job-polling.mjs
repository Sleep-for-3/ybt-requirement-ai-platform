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

  // R08: 一致的恢复入口（visibility / online / 手动重试 共用）。
  // 供可见性与网络恢复回调直接调用。
  function recover(jobId) {
    const entry = entries.get(jobId);
    if (!entry || entry.inFlight || entry.listeners.size === 0 || isHidden()) return false;
    entry.failed = false;
    entry.errors = 0;
    if (entry.timer) { clearTimer(entry.timer); entry.timer = undefined; }
    void poll(jobId, entry);
    return true;
  }

  function handleVisibilityChange() {
    if (isHidden()) {
      for (const entry of entries.values()) {
        if (entry.timer) clearTimer(entry.timer);
        entry.timer = undefined;
      }
      return;
    }
    // R08: visibility 恢复也走**同一条**恢复流程（不再自己写一套 poll 分支）。
    for (const [jobId, entry] of entries) {
      if (entry.failed) {
        recover(jobId);
      } else if (!entry.inFlight && !entry.timer && entry.listeners.size > 0) {
        void poll(jobId, entry);
      }
    }
  }

  function ensureVisibilityListener() {
    if (!unsubscribeVisibility) unsubscribeVisibility = subscribeVisibility(handleVisibilityChange);
    // C11/R08: 网络恢复后走同一条恢复流程，否则断网期间的失败就成了永久停轮询。
    if (!unsubscribeOnline) unsubscribeOnline = subscribeOnline(() => {
      for (const jobId of entries.keys()) recover(jobId);
    });
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
      // R08: 拿到任何状态都说明轮询已恢复 —— 必须清 failed，否则下面的 schedule 会直接 return，
      // 于是“visibility 恢复读到 running 后仍会停轮询”（复核的剩余问题）。
      entry.failed = false;
      entry.lastError = null;
      entry.lastSuccessAt = Date.now();
      notifyState(jobId);
      if (isTerminalJobStatus(job.status)) {
        remove(jobId, entry);
        return;
      }
      const delay = entry.pollCount > 30 ? 5000 : entry.pollCount > 15 ? 3000 : 2000;
      schedule(jobId, entry, delay);
    } catch {
      entry.errors += 1;
      if (entry.errors >= maxErrors) {
        // C11/R08: 不删除条目；记录本次失败（**按 job**）并通知界面，保留 listeners 供恢复。
        entry.failed = true;
        entry.lastError = "后台任务状态暂时无法更新";
        notifyState(jobId);
        options.onPollingError?.(new Error(entry.lastError), { jobId, canResume: true });
        return;
      }
      // C11: 有界退避（上限仍为 5s），不允许无限高频重试。
      schedule(jobId, entry, Math.min(5000, 2000 + entry.errors * 1000));
    } finally {
      entry.inFlight = false;
    }
  }

  // R08: 状态变化通知（按 job）。界面不再靠 1s 轮询去读模块全局变量。
  const stateListeners = new Set();

  function notifyState(jobId) {
    for (const listener of stateListeners) listener(jobId);
  }

  function clearState(jobId) {
    const entry = entries.get(jobId);
    if (!entry) return;
    entry.failed = false;
    entry.lastError = null;
    notifyState(jobId);
  }

  return {
    size: () => entries.size,
    subscribeState(listener) {
      stateListeners.add(listener);
      return () => { stateListeners.delete(listener); };
    },
    // C11: 供界面“重试”按钮/状态查询使用（**按 job**）。
    isStalled: (jobId) => Boolean(entries.get(jobId)?.failed),
    errorFor: (jobId) => entries.get(jobId)?.lastError ?? null,
    lastSuccessAt: (jobId) => entries.get(jobId)?.lastSuccessAt ?? null,
    clearError(jobId) { clearState(jobId); },
    // R08: 一致恢复 —— visibility / online / 手动重试 都走这里（不再各写一套）。
    recover(jobId) { return recover(jobId); },
    // R08: 身份变化（登录/退出）时清空全部轮询状态，防止旧会话的错误提示污染新会话。
    reset() {
      for (const jobId of entries.keys()) clearState(jobId);
    },
    resume(jobId) {
      const entry = entries.get(jobId);
      if (!entry || !entry.failed || entry.inFlight || entry.listeners.size === 0) return false;
      entry.failed = false;
      entry.errors = 0;
      entry.lastError = null;
      void poll(jobId, entry);
      return true;
    },
    subscribe(jobId, listener) {
      let entry = entries.get(jobId);
      if (!entry) {
        entry = {
          errors: 0,
          failed: false,
          lastError: null,
          lastSuccessAt: null,
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

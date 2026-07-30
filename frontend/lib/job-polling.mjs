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
  const maxErrors = options.maxErrors ?? 3;

  function remove(jobId, entry) {
    if (entry.timer) clearTimer(entry.timer);
    entry.timer = undefined;
    if (entries.get(jobId) === entry) entries.delete(jobId);
  }

  function schedule(jobId, entry, delay) {
    if (!entries.has(jobId) || entry.listeners.size === 0) return;
    entry.timer = setTimer(() => poll(jobId, entry), delay);
  }

  async function poll(jobId, entry) {
    if (entries.get(jobId) !== entry || entry.listeners.size === 0 || entry.inFlight) return;
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
        remove(jobId, entry);
        options.onPollingError?.(new Error("后台任务状态暂时无法更新"));
        return;
      }
      schedule(jobId, entry, Math.min(5000, 2000 + entry.errors * 1000));
    } finally {
      entry.inFlight = false;
    }
  }

  return {
    size: () => entries.size,
    subscribe(jobId, listener) {
      let entry = entries.get(jobId);
      if (!entry) {
        entry = {
          errors: 0,
          inFlight: false,
          listeners: new Set(),
          pollCount: 0,
          timer: undefined
        };
        entries.set(jobId, entry);
      }
      entry.listeners.add(listener);
      if (!entry.inFlight && !entry.timer && entry.pollCount === 0) void poll(jobId, entry);
      return () => {
        entry.listeners.delete(listener);
        if (entry.listeners.size === 0) remove(jobId, entry);
      };
    }
  };
}

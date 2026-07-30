/**
 * Framework-independent action guard. React hooks and tests share this core so
 * the duplicate-click lock is synchronous and does not depend on a render.
 */
export function createAsyncActionRunner(options = {}) {
  let active = false;

  function publish(status, error) {
    options.onStateChange?.({ status, error });
  }

  async function execute(action, confirmation) {
    if (active) return { executed: false };
    active = true;
    publish("submitting");
    try {
      if (confirmation && !(await confirmation())) {
        return { executed: false };
      }
      const value = await action();
      options.onSuccess?.(value);
      publish("success");
      return { executed: true, value };
    } catch (cause) {
      const error = cause instanceof Error ? cause : new Error(String(cause));
      options.onError?.(error);
      publish("failed", error);
      throw error;
    } finally {
      options.onFinally?.();
      active = false;
      publish("idle");
    }
  }

  return {
    isRunning: () => active,
    run: (action) => execute(action),
    runConfirmed: (confirmation, action) => execute(action, confirmation)
  };
}

export type JobLike = { status: string };
export type PollingRegistry<T extends JobLike> = {
  size(): number;
  subscribe(jobId: number, listener: (job: T) => void): () => void;
  /** C11: 连续失败是否已停止轮询（订阅仍保留，可恢复）。 */
  isStalled(jobId: number): boolean;
  /** R08: 该 job 自己的错误消息（不与他 job 混淆），无错误时为 null。 */
  errorFor(jobId: number): string | null;
  /** R08: 该 job 最后一次成功拉取的时间戳。 */
  lastSuccessAt(jobId: number): number | null;
  /** C11: 手动恢复被停止的轮询；返回是否真的重新发起。 */
  resume(jobId: number): boolean;
  /** R08: 一致的恢复入口（visibility / online / 手动共用）。 */
  recover(jobId: number): boolean;
  /** R08: 清除该 job 的错误状态。 */
  clearError(jobId: number): void;
  /** R08: 身份变化（登录/退出）时清空全部状态。 */
  reset(): void;
  /** R08: 订阅状态变化（按 job），替代 1s 轮询读取全局变量。 */
  subscribeState(listener: (jobId: number) => void): () => void;
};

export function isTerminalJobStatus(status: string): boolean;
export function createJobPollingRegistry<T extends JobLike>(options: {
  fetchJob(jobId: number): Promise<T>;
  setTimer?: (callback: () => void | Promise<void>, delay: number) => unknown;
  clearTimer?: (token: unknown) => void;
  maxErrors?: number;
  /** C11: 第二个参数携带 jobId 与 canResume，供界面显示可恢复提示。 */
  onPollingError?: (error: Error, info?: { jobId: number; canResume: boolean }) => void;
  /** C11: 网络恢复信号（浏览器 online）。 */
  subscribeOnline?: (listener: () => void) => () => void;
}): PollingRegistry<T>;

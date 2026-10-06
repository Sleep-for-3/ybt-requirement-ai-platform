export type JobLike = { status: string };
export type PollingRegistry<T extends JobLike> = {
  size(): number;
  subscribe(jobId: number, listener: (job: T) => void): () => void;
  /** C11: 连续失败是否已停止轮询（订阅仍保留，可恢复）。 */
  isStalled(jobId: number): boolean;
  /** C11: 手动恢复被停止的轮询；返回是否真的重新发起。 */
  resume(jobId: number): boolean;
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

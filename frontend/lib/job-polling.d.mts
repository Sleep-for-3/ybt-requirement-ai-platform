export type JobLike = { status: string };
export type PollingRegistry<T extends JobLike> = {
  size(): number;
  subscribe(jobId: number, listener: (job: T) => void): () => void;
};

export function isTerminalJobStatus(status: string): boolean;
export function createJobPollingRegistry<T extends JobLike>(options: {
  fetchJob(jobId: number): Promise<T>;
  setTimer?: (callback: () => void | Promise<void>, delay: number) => unknown;
  clearTimer?: (token: unknown) => void;
  maxErrors?: number;
  onPollingError?: (error: Error) => void;
}): PollingRegistry<T>;

export function jobDetailsHref(jobId) {
  return `/jobs/${encodeURIComponent(String(jobId))}`;
}

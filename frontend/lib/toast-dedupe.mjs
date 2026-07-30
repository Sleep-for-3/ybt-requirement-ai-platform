export function isRecentToast(previousAt, now = Date.now(), windowMs = 2_000) {
  return Number.isFinite(previousAt) && now >= previousAt && now - previousAt < windowMs;
}

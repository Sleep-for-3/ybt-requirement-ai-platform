/**
 * 请求预算策略：默认 60 s，长耗时业务 600 s。
 *
 * 真实模型下单次生成实测 11–123 s；叠加"同一个模型重试 + 兜底模型"后，单次
 * `generate-draft` 的最坏时长可达数分钟（演练实测一次成功调用 411.6 s）。此时服务端
 * 仍在正常工作，统一的 60 s 浏览器超时会把结果误报成"请求超时"，用户重试还会产生
 * 重复草稿。根治方案是把生成类接口改为后台任务并轮询（见 R6 P1-6）。
 */
export const DEFAULT_REQUEST_TIMEOUT_MS = 60_000;
export const LONG_REQUEST_TIMEOUT_MS = 600_000;

const LONG_RUNNING_PATH_PATTERNS = [
  /\/generate-draft$/,
  /\/generate-mapping$/,
  /\/batch\/generate-/,
  /\/profile$/,
  /\/metadata-sync$/,
  /\/reindex$/,
  /\/sync$/,
  /\/evaluations\/runs$/,
  /\/runs$/,
  /\/execute$/,
  /\/render$/,
  /\/download$/,
  /\/export\//,
  /\/knowledge\/ask$/,
  /\/lineage\/edge-explanations$/,
  /\/ai-runtime\/test-chat$/
];

/** 去掉查询串后再判断，避免 `?project_id=1` 之类参数影响匹配。 */
export function isLongRunningRequest(path) {
  const normalized = String(path || "").split("?")[0];
  return LONG_RUNNING_PATH_PATTERNS.some((pattern) => pattern.test(normalized));
}

export function requestTimeoutMs(path) {
  return isLongRunningRequest(path) ? LONG_REQUEST_TIMEOUT_MS : DEFAULT_REQUEST_TIMEOUT_MS;
}

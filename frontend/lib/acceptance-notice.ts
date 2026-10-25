"use client";

/**
 * 一键验收结果的跨挂载存放处（round 64 修的真实缺陷）。
 *
 * 背景：`components/AppShell.tsx:319` 用 `key={`project-scope-${projectId ?? "none"}`}` 包住页面子树，
 * 项目作用域从"未确定"变成真实 id 时整棵子树会重新挂载。页面在加载后约 1 秒内就可能撞上这次重挂载，
 * 此时"点按钮 → 等接口 → setState"里写在旧实例上的结果会被静默丢弃：按钮变回原样、用户看不到任何提示。
 * 结论不是文案问题，而是结果存放位置选错了——所以结果放在模块级存储里，重挂载后新实例仍能读到。
 *
 * 存储只保留**最后一条**结果，并且带 projectId：换项目不继承上一个项目的提示。
 */

export type AcceptanceNoticeKind = "pass" | "blocked" | "error";

export interface AcceptanceNotice {
  projectId: number;
  artifactId: number | null;
  /** 单产物验收还是不产物批量验收——批量时 artifactId 为 null。 */
  scope?: "artifact" | "batch";
  kind: AcceptanceNoticeKind;
  text: string;
  recordId: number | null;
  at: number;
}

let current: AcceptanceNotice | null = null;
const listeners = new Set<() => void>();

function emit(): void {
  listeners.forEach((listener) => listener());
}

export function publishAcceptanceNotice(notice: AcceptanceNotice): void {
  current = notice;
  emit();
}

export function clearAcceptanceNotice(): void {
  if (current === null) return;
  current = null;
  emit();
}

export function subscribeAcceptanceNotice(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function getAcceptanceNotice(): AcceptanceNotice | null {
  return current;
}

/** 服务端渲染没有这条数据，返回 null 让首屏不出现"上次验收"提示。 */
export function getServerAcceptanceNotice(): AcceptanceNotice | null {
  return null;
}

export function noticeForProject(notice: AcceptanceNotice | null, projectId: number): AcceptanceNotice | null {
  if (!notice) return null;
  return notice.projectId === projectId ? notice : null;
}

/** 提示里必须同时说清"结果"和"这次通过不等于业务口径确认"，避免被当成审批结论。 */
export function describeAcceptanceNotice(notice: AcceptanceNotice): string {
  return notice.text;
}

"use client";

import { CircleOff, RotateCw } from "lucide-react";
import type { ReactNode } from "react";

// @ts-expect-error The planned runtime .mjs contract is verified directly by Node DOM tests.
import { asyncRegionContractAttributes, retryAccessibleName } from "@/lib/semantic-catalog-dom-contract.mjs";
import { detailRegionResponseKind } from "@/lib/semantic-catalog-view-model.mjs";
import type { DetailRegionState } from "@/lib/semantic-catalog-view-model.mjs";

export function AsyncRegion<T>({ label, state, emptyText, onRetry, children }: {
  label:string;
  state:DetailRegionState<T>;
  emptyText:string;
  onRetry:()=>void;
  children:(data:T)=>ReactNode;
}) {
  const kind = detailRegionResponseKind(state);
  if (kind === "idle" || kind === "loading") return <RegionSkeleton label={label} />;
  if (kind === "forbidden") return <section {...asyncRegionContractAttributes("forbidden", label)} className="rounded-lg border border-gold-200 bg-gold-50 p-5"><h2 className="text-base font-semibold text-gold-900">无权查看{label}</h2><p className="mt-2 text-sm text-gold-800">当前账号可继续查看语义概览，但没有此区域的资源权限。</p></section>;
  if (kind === "error") return <section {...asyncRegionContractAttributes("error", label)} className="rounded-lg border border-coral-200 bg-coral-50 p-5"><h2 className="text-base font-semibold text-coral-800">{label}加载失败</h2><p className="mt-2 text-sm text-coral-700">该区域未加载，不代表没有数据。</p>{state.error?.message ? <p className="mt-1 text-xs text-coral-700">{state.error.message}</p> : null}<button aria-label={retryAccessibleName(label)} className="button-secondary mt-4 min-h-11" onClick={onRetry} type="button"><RotateCw aria-hidden size={15} />{retryAccessibleName(label)}</button></section>;
  if (kind === "success-empty") return <section className="empty-state" aria-live="polite"><CircleOff aria-hidden className="text-slate-300" size={30} /><h2 className="text-base font-semibold text-ink">{emptyText}</h2><p>该状态来自服务器的成功空结果。</p></section>;
  return <>{children(state.data as T)}</>;
}

function RegionSkeleton({ label }: { label:string }) {
  return <section {...asyncRegionContractAttributes("loading", label)} className="space-y-3"><div aria-hidden className="h-5 w-40 animate-pulse rounded bg-slate-200" />{[0, 1, 2].map((item) => <div aria-hidden className="h-16 animate-pulse rounded-lg border border-line bg-white" key={item} />)}</section>;
}

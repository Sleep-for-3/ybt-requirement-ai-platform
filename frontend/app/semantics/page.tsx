"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { BookOpenCheck, RotateCw } from "lucide-react";

import { useProjectWorkspace } from "@/components/ProjectContext";
import { WorkspaceHeader } from "@/components/WorkspaceHeader";
import { apiGet } from "@/lib/api";
import type { SemanticCatalogItem, SemanticCatalogPage as SemanticCatalogResponse } from "@/lib/api";

type CatalogState =
  | { kind: "idle" | "loading" }
  | { kind: "success"; page: SemanticCatalogResponse }
  | { kind: "forbidden" | "error"; message: string };

function isForbiddenMessage(message: string) {
  return /missing project permission|insufficient project role|没有操作权限/i.test(message);
}

export default function SemanticCatalogPage() {
  const { projectId } = useProjectWorkspace();
  const [state, setState] = useState<CatalogState>({ kind: "idle" });
  const [reloadToken, setReloadToken] = useState(0);
  const activeRequestKey = useRef("");

  useEffect(() => {
    if (!projectId) {
      activeRequestKey.current = "";
      setState({ kind: "idle" });
      return;
    }
    const requestKey = `${projectId}:${reloadToken}`;
    activeRequestKey.current = requestKey;
    setState({ kind: "loading" });
    void apiGet<SemanticCatalogResponse>(
      `/projects/${projectId}/semantic-catalog?mode=candidate&page=1&page_size=50`,
    )
      .then((page) => {
        if (activeRequestKey.current === requestKey) setState({ kind: "success", page });
      })
      .catch((error: unknown) => {
        if (activeRequestKey.current !== requestKey) return;
        const message = error instanceof Error ? error.message : "请求失败";
        setState(
          isForbiddenMessage(message)
            ? { kind: "forbidden", message }
            : { kind: "error", message },
        );
      });
    return () => {
      if (activeRequestKey.current === requestKey) activeRequestKey.current = "";
    };
  }, [projectId, reloadToken]);

  const total = state.kind === "success" ? state.page.total : null;
  return (
    <main>
      <WorkspaceHeader
        title="语义目录"
        meta={total === null ? "项目监管语义" : `共 ${total} 个语义概念`}
      />
      <div className="mx-auto max-w-[1600px] space-y-6 p-4 lg:p-6">
        {state.kind === "idle" ? (
          <section className="empty-state" aria-live="polite">
            <BookOpenCheck className="text-slate-300" size={32} />
            <p>请先选择项目</p>
          </section>
        ) : null}
        {state.kind === "loading" ? <CatalogSkeleton /> : null}
        {state.kind === "forbidden" ? (
          <CatalogError title="无权查看语义目录" message="当前账号没有所选项目的语义目录访问权限。" />
        ) : null}
        {state.kind === "error" ? (
          <CatalogError
            title="语义目录加载失败"
            message={state.message}
            onRetry={() => setReloadToken((value) => value + 1)}
          />
        ) : null}
        {state.kind === "success" && state.page.items.length === 0 ? (
          <section className="empty-state" aria-live="polite">
            <BookOpenCheck className="text-slate-300" size={32} />
            <h2 className="text-base font-semibold text-ink">当前项目暂无语义概念</h2>
            <p>目录仅展示来自受治理语义事实的真实结果。</p>
          </section>
        ) : null}
        {state.kind === "success" && state.page.items.length > 0 ? (
          <CatalogDirectory items={state.page.items} />
        ) : null}
      </div>
    </main>
  );
}

function CatalogSkeleton() {
  return (
    <section aria-busy="true" aria-label="正在加载语义目录" className="space-y-3">
      {[0, 1, 2].map((item) => (
        <div aria-hidden="true" className="h-[68px] animate-pulse rounded-lg border border-line bg-white" key={item} />
      ))}
    </section>
  );
}

function CatalogError({ title, message, onRetry }: { title:string;message:string;onRetry?:()=>void }) {
  return (
    <section className="rounded-lg border border-coral-200 bg-coral-50 p-5" role="alert">
      <h2 className="text-base font-semibold text-coral-800">{title}</h2>
      <p className="mt-2 text-sm text-coral-700">{message}</p>
      {onRetry ? (
        <button className="button-secondary mt-4" onClick={onRetry}>
          <RotateCw size={15} />重新加载语义目录
        </button>
      ) : null}
    </section>
  );
}

function CatalogDirectory({ items }: { items:SemanticCatalogItem[] }) {
  const groups = new Map<string, SemanticCatalogItem[]>();
  for (const item of items) {
    const key = item.business_domain?.trim() || "未分类";
    groups.set(key, [...(groups.get(key) || []), item]);
  }
  return (
    <div className="space-y-6" aria-live="polite">
      {Array.from(groups.entries()).map(([domain, concepts]) => (
        <section key={domain}>
          <h2 className="mb-2 text-base font-semibold text-ink">{domain} · {concepts.length}</h2>
          <div className="overflow-hidden rounded-lg border border-line bg-white">
            {concepts.map((item) => (
              <article className="grid min-h-[68px] gap-3 border-b border-line p-4 last:border-0 md:grid-cols-[minmax(220px,1.6fr)_120px_120px_minmax(130px,1fr)_100px] md:items-center" key={item.id}>
                <div className="min-w-0">
                  <Link className="font-semibold text-pine-700 hover:underline" href={`/semantics/${item.id}`}>
                    {item.concept_name}
                  </Link>
                  <div className="mt-1 break-all font-mono text-xs text-slate-500">{item.concept_code}</div>
                </div>
                <span className="text-sm text-slate-600">{item.concept_type}</span>
                <span className="text-sm text-slate-600">{item.effective_version ? `v${item.effective_version.version_no}` : "暂无正式版本"}</span>
                <div className="text-sm text-slate-600">
                  <span>{item.status}</span>
                  {item.review.pending ? <span className="ml-2 text-gold-700">待审核</span> : null}
                </div>
                <span className="text-sm text-slate-600">{item.related_asset_count} 个资产</span>
              </article>
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}

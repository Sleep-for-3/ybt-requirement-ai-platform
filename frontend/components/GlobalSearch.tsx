"use client";

import { ArrowUpRight, Clock3, Search } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { ModalDialog } from "@/components/feedback/ModalDialog";
import { apiGet } from "@/lib/api";

type SearchItem = {
  category: string;
  entity_type: string;
  entity_id: number;
  title: string;
  subtitle?: string | null;
  href: string;
};

type SearchResponse = {
  query: string;
  items: SearchItem[];
  category_counts: Record<string, number>;
};

type SearchState = "idle" | "loading" | "ready" | "error";

export function GlobalSearch({ projectId }: { projectId: number | null }) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [items, setItems] = useState<SearchItem[]>([]);
  const [recent, setRecent] = useState<SearchItem[]>([]);
  const [state, setState] = useState<SearchState>("idle");

  useEffect(() => {
    function shortcut(event: KeyboardEvent) {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        if (projectId) setOpen(true);
      }
    }
    document.addEventListener("keydown", shortcut);
    return () => document.removeEventListener("keydown", shortcut);
  }, [projectId]);

  useEffect(() => {
    setItems([]);
    setQuery("");
    setState("idle");
    if (!projectId) { setRecent([]); return; }
    try {
      const parsed = JSON.parse(localStorage.getItem(recentKey(projectId)) || "[]");
      setRecent(Array.isArray(parsed) ? parsed.filter(isSafeItem).slice(0, 6) : []);
    } catch {
      setRecent([]);
    }
  }, [projectId]);

  useEffect(() => {
    const normalized = query.trim();
    if (!open || !projectId || normalized.length < 2) {
      setItems([]);
      setState("idle");
      return;
    }
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      setState("loading");
      void apiGet<SearchResponse>(`/projects/${projectId}/global-search?q=${encodeURIComponent(normalized)}&limit=40`, { signal: controller.signal })
        .then((result) => {
          if (controller.signal.aborted) return;
          setItems(result.items.filter(isSafeItem));
          setState("ready");
        })
        .catch(() => {
          if (!controller.signal.aborted) { setItems([]); setState("error"); }
        });
    }, 250);
    return () => { window.clearTimeout(timer); controller.abort(); };
  }, [open, projectId, query]);

  function remember(item: SearchItem) {
    if (!projectId || !isSafeItem(item)) return;
    const next = [item, ...recent.filter((candidate) => candidate.entity_type !== item.entity_type || candidate.entity_id !== item.entity_id)].slice(0, 6);
    setRecent(next);
    localStorage.setItem(recentKey(projectId), JSON.stringify(next));
    setOpen(false);
  }

  const visible = query.trim().length >= 2 ? items : recent;
  const groups = groupItems(visible);
  return (
    <>
      <button aria-label="全局资产搜索" className="flex h-9 w-9 shrink-0 items-center justify-center gap-2 rounded-lg border border-line bg-slate-50 text-left text-xs text-slate-500 hover:border-pine-200 hover:bg-white md:w-auto md:min-w-56 md:justify-start md:px-3" disabled={!projectId} onClick={() => setOpen(true)} type="button">
        <Search size={15} /><span className="hidden flex-1 md:block">搜索资产、语义、需求与血缘</span><kbd className="hidden rounded border border-line bg-white px-1.5 py-0.5 text-[10px] md:inline">Ctrl K</kbd>
      </button>
      <ModalDialog description="仅搜索当前项目中你有权访问的资产，结果直接进入生产页面。" onClose={() => setOpen(false)} open={open} title="全局资产搜索">
        <label className="relative block"><Search className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" size={17} /><input autoFocus className="control pl-10" onChange={(event) => setQuery(event.target.value)} placeholder="输入名称、编码、定义或脚本路径（至少 2 个字符）" value={query} /></label>
        <div className="mt-4 max-h-[55vh] space-y-4 overflow-y-auto">
          {state === "loading" ? <p className="rounded-lg bg-slate-50 px-3 py-4 text-sm text-slate-500">正在检索当前项目资产…</p> : null}
          {state === "error" ? <p className="rounded-lg border border-coral-200 bg-coral-50 px-3 py-4 text-sm text-coral-700" role="alert">搜索暂时不可用，请检查网络或权限后重试。</p> : null}
          {state === "ready" && !items.length ? <p className="rounded-lg bg-slate-50 px-3 py-4 text-sm text-slate-500">当前项目没有匹配结果，请尝试名称、编码或更短的关键词。</p> : null}
          {state === "idle" && !query.trim() && !recent.length ? <p className="rounded-lg bg-slate-50 px-3 py-4 text-sm text-slate-500">暂无最近访问，从搜索一个监管字段或语义概念开始。</p> : null}
          {Array.from(groups.entries()).map(([category, rows]) => <section key={category}><h3 className="mb-2 flex items-center gap-2 text-xs font-semibold text-slate-500">{query.trim().length < 2 ? <Clock3 size={13} /> : null}{category}<span className="font-normal text-slate-400">{rows.length}</span></h3><div className="divide-y divide-line overflow-hidden rounded-xl border border-line">{rows.map((item) => <Link className="flex items-center gap-3 bg-white px-3 py-3 transition hover:bg-mist" href={item.href} key={`${item.entity_type}-${item.entity_id}`} onClick={() => remember(item)}><div className="min-w-0 flex-1"><p className="truncate text-sm font-medium text-ink">{item.title}</p>{item.subtitle ? <p className="mt-0.5 truncate text-xs text-slate-500">{item.subtitle}</p> : null}</div><ArrowUpRight className="shrink-0 text-slate-400" size={15} /></Link>)}</div></section>)}
        </div>
      </ModalDialog>
    </>
  );
}

function recentKey(projectId: number) {
  return `ybt:recent-assets:${projectId}`;
}

function isSafeItem(value: unknown): value is SearchItem {
  if (!value || typeof value !== "object") return false;
  const item = value as Partial<SearchItem>;
  return typeof item.entity_id === "number" && typeof item.entity_type === "string" && typeof item.category === "string" && typeof item.title === "string" && typeof item.href === "string" && item.href.startsWith("/") && !item.href.startsWith("//");
}

function groupItems(items: SearchItem[]) {
  const groups = new Map<string, SearchItem[]>();
  for (const item of items) groups.set(item.category, [...(groups.get(item.category) || []), item]);
  return groups;
}

"use client";

import { ArrowUpRight, Clock3, Search } from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { ModalDialog } from "@/components/feedback/ModalDialog";
import { apiGet } from "@/lib/api";

type SearchItem = { category: string; entity_type: string; entity_id: number; title: string; subtitle?: string | null; href: string };
type Recent = { query: string; type: string; id: number };
type Results = { query: string; items: SearchItem[] | null };
const TITLE = "搜索当前项目资产";

export function GlobalSearch({ projectId }: { projectId: number | null }) {
  return <ProjectAssetSearch key={projectId} projectId={projectId} />;
}

function search(projectId: number, query: string, signal: AbortSignal) {
  return apiGet<{ items: SearchItem[] }>(`/projects/${projectId}/global-search?q=${encodeURIComponent(query)}&limit=40`, { signal });
}

function ProjectAssetSearch({ projectId }: { projectId: number | null }) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<Results | null>(null);
  const [recent, setRecent] = useState<SearchItem[]>([]);
  const input = useRef<HTMLInputElement>(null);
  const list = useRef<HTMLDivElement>(null);
  const key = `ybt:recent-project-search:${projectId}`;
  const normalized = query.trim();

  useEffect(() => {
    function shortcut(event: KeyboardEvent) {
      if (projectId && (event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setOpen(true);
      }
    }
    document.addEventListener("keydown", shortcut);
    return () => document.removeEventListener("keydown", shortcut);
  }, [projectId]);

  useEffect(() => {
    if (!open || !projectId || normalized.length < 2) return;
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      void search(projectId, normalized, controller.signal).then(({ items }) => {
        if (!controller.signal.aborted) setResults({ query: normalized, items: items.filter(isAssetLink) });
      }).catch(() => {
        if (!controller.signal.aborted) setResults({ query: normalized, items: null });
      });
    }, 250);
    return () => { window.clearTimeout(timer); controller.abort(); };
  }, [open, projectId, normalized]);

  useEffect(() => {
    if (!open || !projectId || normalized) return;
    const controller = new AbortController();
    let saved: Recent[];
    try {
      const value: unknown = JSON.parse(localStorage.getItem(key) || "[]");
      saved = Array.isArray(value) ? value.filter((row): row is Recent => row && typeof row.query === "string" && row.query.length >= 2 && row.query.length <= 100 && typeof row.type === "string" && Number.isInteger(row.id)).slice(0, 6) : [];
    } catch { saved = []; }
    const queries = new Map(Array.from(new Set(saved.map(row => row.query)), value => [value, search(projectId, value, controller.signal).catch(() => ({ items: [] }))] as const));
    void Promise.all(saved.map(async row => (await queries.get(row.query))?.items.find(item => item.entity_type === row.type && item.entity_id === row.id))).then(items => {
      if (!controller.signal.aborted) setRecent(items.filter(isAssetLink));
    });
    return () => controller.abort();
  }, [open, projectId, key, normalized]);

  function close() { setOpen(false); setQuery(""); setResults(null); setRecent([]); }
  function remember(item: SearchItem) {
    if (normalized.length >= 2) {
      try {
        const saved: Recent[] = JSON.parse(localStorage.getItem(key) || "[]");
        localStorage.setItem(key, JSON.stringify([{ query: normalized, type: item.entity_type, id: item.entity_id }, ...(Array.isArray(saved) ? saved.filter(row => row && (row.type !== item.entity_type || row.id !== item.entity_id)) : [])].slice(0, 6)));
      } catch { /* Recent visits are optional. */ }
    }
    close();
  }

  const current = results?.query === normalized ? results : null;
  const visible = normalized ? current?.items ?? [] : recent;
  const groups = new Map<string, SearchItem[]>();
  for (const item of visible) groups.set(item.category, [...(groups.get(item.category) ?? []), item]);

  return <>
    <button aria-label={TITLE} className="flex h-9 w-9 shrink-0 items-center justify-center gap-2 rounded-lg border border-line bg-slate-50 text-xs text-slate-600 hover:bg-white md:w-auto md:px-3" disabled={!projectId} onClick={() => setOpen(true)} type="button">
      <Search size={15} /><span className="hidden md:inline">{TITLE}</span>
    </button>
    <ModalDialog initialFocusRef={input} onClose={close} open={open} title={TITLE}>
      <div onKeyDown={event => {
        if (!['ArrowDown', 'ArrowUp'].includes(event.key) || event.nativeEvent.isComposing) return;
        const links = Array.from(list.current?.querySelectorAll<HTMLAnchorElement>("a") ?? []);
        if (!links.length) return;
        event.preventDefault();
        const index = links.indexOf(document.activeElement as HTMLAnchorElement);
        if (index === 0 && event.key === "ArrowUp") input.current?.focus();
        else (links[index < 0 ? (event.key === "ArrowUp" ? links.length - 1 : 0) : Math.min(links.length - 1, index + (event.key === "ArrowDown" ? 1 : -1))])?.focus();
      }}>
        <label className="relative block"><Search className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" size={17} /><input aria-label="资产关键词" className="control pl-10" maxLength={100} onChange={event => { setQuery(event.target.value); if (event.target.value.trim() !== normalized) { setResults(null); setRecent([]); } }} placeholder="字段、表、口径或证据" ref={input} value={query} /></label>
        <div className="mt-3 max-h-[55vh] overflow-y-auto" ref={list}>
          {normalized.length === 1 ? <p role="status" className="text-sm text-slate-500">请输入至少 2 个字符。</p> : null}
          {normalized.length >= 2 && !current ? <p role="status" className="text-sm text-slate-500">正在搜索…</p> : null}
          {current?.items === null ? <p role="alert" className="text-sm text-coral-700">搜索失败，请检查网络或项目权限。</p> : null}
          {current?.items?.length === 0 ? <p role="status" className="text-sm text-slate-500">当前项目没有匹配结果。</p> : null}
          {!normalized ? <p className="mb-2 flex items-center gap-2 text-xs text-slate-500"><Clock3 size={13} />{recent.length ? "最近访问" : "暂无可显示的最近访问"}</p> : null}
          {Array.from(groups).map(([category, rows]) => <section className="mb-3" key={category}>
            <h3 className="border-b border-line py-1 text-xs font-semibold text-slate-500">{category} · {rows.length}</h3>
            {rows.map(item => <Link className="flex items-center gap-3 border-b border-line px-2 py-2.5 hover:bg-mist focus-visible:outline-pine-700" href={item.href} key={`${item.entity_type}-${item.entity_id}`} onClick={() => remember(item)}>
              <span className="min-w-0 flex-1 break-words text-sm font-medium text-ink"><Highlight text={item.title} query={normalized} />{item.subtitle ? <span className="block text-xs font-normal text-slate-500"><Highlight text={item.subtitle} query={normalized} /></span> : null}</span><ArrowUpRight className="shrink-0 text-slate-400" size={15} />
            </Link>)}
          </section>)}
        </div>
      </div>
    </ModalDialog>
  </>;
}

function isAssetLink(item: SearchItem | undefined): item is SearchItem {
  return Boolean(item && typeof item.href === "string" && /^\/(?![/\\])/.test(item.href));
}

function Highlight({ text, query }: { text: string; query: string }) {
  if (!query) return text;
  const pattern = new RegExp(`(${query.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")})`, "giu");
  return text.split(pattern).map((part, index) => index % 2 === 1 ? <mark className="rounded bg-amber-100 text-ink" key={index}>{part}</mark> : part);
}

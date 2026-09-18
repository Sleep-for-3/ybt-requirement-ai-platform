"use client";
import { useEffect, useRef, useState } from "react";
import { Download, ExternalLink } from "lucide-react";
import { apiBlob, apiGet } from "@/lib/api";
import type { KnowledgeLocator, KnowledgePreview } from "@/lib/knowledge-types";
import { locateBlock, ownedBlobUrl, viewerFormat } from "@/lib/knowledge-contract.mjs";

function cellNumber(value: string) { return Array.from(value).reduce((n, c) => n * 26 + c.charCodeAt(0) - 64, 0); }
function inRange(row:number, col:number, range?:string|null) {
  const m = range?.toUpperCase().match(/^([A-Z]+)(\d+)(?::([A-Z]+)(\d+))?$/);
  return !!m && row >= Number(m[2]) && row <= Number(m[4] || m[2]) && col >= cellNumber(m[1]) && col <= cellNumber(m[3] || m[1]);
}
export function KnowledgeDocumentViewer({projectId, documentId, versionId, locator, parsedOnly=false}: {projectId:number; documentId:number; versionId?:number; locator?:KnowledgeLocator; parsedOnly?:boolean}) {
  const [data,setData]=useState<KnowledgePreview|null>(null), [url,setUrl]=useState(""), [error,setError]=useState(""), [fileError,setFileError]=useState("");
  const [sheet,setSheet]=useState(""); const root=useRef<HTMLDivElement>(null);
  const locatorKey=JSON.stringify(locator || {});
  useEffect(()=>{
    const controller=new AbortController(); let dispose: (()=>void)|undefined; let active=true;
    setData(null);setUrl("");setError("");setFileError("");
    const base=`/knowledge/documents/${documentId}`;
    const query=`project_id=${projectId}${versionId ? `&version_id=${versionId}` : ""}`;
    void apiGet<KnowledgePreview>(`${base}/preview?${query}`,{signal:controller.signal}).then(async preview=>{
      if (!active) return;
      setData(preview);setSheet(preview.sheets?.[0]?.name || "");
      try {
        const blob=await apiBlob(`${base}/content?project_id=${projectId}&version_id=${preview.document_version_id}`,controller.signal);
        if (!active) return;
        const handle=ownedBlobUrl(blob);dispose=handle.dispose;setUrl(handle.url);
      } catch { if(active) setFileError("原文暂不可用；下方仍可核验已解析证据。"); }
    }).catch(()=>{if(active)setError("证据已不可用：文档不存在或当前项目无访问权限。");});
    return ()=>{active=false;controller.abort();dispose?.();};
  },[projectId,documentId,versionId]);
  const requestedSheet=locator?.sheet_name;
  useEffect(()=>{if(requestedSheet)setSheet(requestedSheet);},[requestedSheet,data]);
  const found=data ? locateBlock(data.blocks,locator) : null;
  const gridFound=!!data?.sheets?.find(s=>s.name===locator?.sheet_name)?.rows.some((row,r)=>row.some((_,c)=>inRange(r+1,c+1,locator?.cell_range)));
  useEffect(()=>{
    const target=root.current?.querySelector<HTMLElement>('[data-highlight="true"]');
    target?.scrollIntoView({block:"nearest",behavior:"auto"});target?.focus({preventScroll:true});
  },[found,data,sheet,locatorKey]);
  if(error)return <p role="alert" className="rounded-lg bg-red-50 p-4 text-red-800">{error}</p>;
  if(!data)return <p role="status" className="p-5">正在读取文档与定位信息…</p>;
  const format=viewerFormat(data.file_type), selected=data.sheets?.find(s=>s.name===sheet);
  return <div ref={root} className="min-w-0 space-y-4">
    <div className="flex flex-wrap items-center justify-between gap-3"><h3 className="min-w-0 break-words font-semibold">{data.file_name} · 第 {data.version_no} 版</h3><div className="flex flex-wrap gap-2">{url&&format==="pdf"?<a className="button-secondary" href={`${url}#page=${locator?.page_no || 1}`} target="_blank" rel="noopener noreferrer"><ExternalLink size={16}/>打开 PDF 原文</a>:null}{url?<a className="button-secondary" href={url} download={data.file_name}><Download size={16}/>下载原文</a>:null}</div></div>
    {fileError?<p role="status">{fileError}</p>:null}
    {data.warnings.map((warning,i)=><p className="rounded bg-amber-50 p-3 text-sm text-amber-900" key={i}>{warning.includes("OCR")?"当前文件需要 OCR 才能精确检索":warning}</p>)}
    {locator && !found && !gridFound?<p role="status" className="rounded bg-amber-50 p-3">已打开对应文档，精确位置待重新解析</p>:null}
    <div className={format==="pdf"&&!parsedOnly?"grid min-w-0 gap-4 lg:grid-cols-2":"space-y-4"}>
    {format==="pdf"&&!parsedOnly&&url?<iframe title="PDF 原文" src={`${url}#page=${locator?.page_no || 1}`} className="h-[65vh] w-full rounded border border-line"/>:null}
    {format==="grid"&&!parsedOnly&&data.sheets?.length?<section><div role="tablist" aria-label="工作表" className="mb-3 flex flex-wrap gap-2">{data.sheets.map(s=><button role="tab" aria-selected={s.name===sheet} className={s.name===sheet?"button-primary":"button-secondary"} onClick={()=>setSheet(s.name)} key={s.name}>{s.name}</button>)}</div><div className="max-h-[55vh] overflow-auto"><table className="w-full border-collapse text-sm"><tbody>{selected?.rows.map((row,r)=><tr key={r}><th className="border bg-mist px-2">{r+1}</th>{row.map((text,c)=>{const hit=sheet===locator?.sheet_name&&inRange(r+1,c+1,locator.cell_range);return <td key={c} tabIndex={hit?0:undefined} data-highlight={hit} className={`min-w-24 whitespace-pre-wrap border p-2 ${hit?"bg-amber-100 outline-amber-500":""}`}>{text}</td>;})}</tr>)}</tbody></table></div></section>:null}
    <section aria-label="解析证据" className="space-y-3">{data.blocks.map(block=><article key={block.block_id} tabIndex={block.block_id===found?0:undefined} data-highlight={block.block_id===found} className={`rounded-lg border p-4 ${block.block_id===found?"border-amber-400 bg-amber-50":"border-line"}`}><p className="mb-2 text-xs text-slate-500">{block.locator.sheet_name} {block.locator.cell_range} {block.locator.page_no?`第 ${block.locator.page_no} 页`:""} {block.locator.paragraph_index?`段落 ${block.locator.paragraph_index}`:""}</p><div className={`whitespace-pre-wrap break-words text-sm leading-7 ${format==="text"?"font-mono":""}`}>{block.text}</div></article>)}</section>
    {!data.blocks.length?<p>当前版本暂无可解析文字。</p>:null}
    </div>
  </div>;
}

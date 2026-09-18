"use client";
import { useEffect, useRef } from "react";
import { KnowledgeDocumentViewer } from "./KnowledgeDocumentViewer";
import type { KnowledgeCitation } from "@/lib/knowledge-types";
import { citationLocator } from "@/lib/knowledge-contract.mjs";
export function KnowledgeEvidenceDrawer({citation,projectId,onClose}:{citation:KnowledgeCitation|null;projectId:number;onClose:()=>void}) {
  const dialog=useRef<HTMLDialogElement>(null);
  useEffect(()=>{if(!citation)return;const previous=document.activeElement as HTMLElement|null;const node=dialog.current;node?.showModal();return()=>{node?.close();previous?.focus();};},[citation]);
  if(!citation)return null;
  return <dialog ref={dialog} onCancel={event=>{event.preventDefault();onClose();}} className="fixed inset-y-0 left-auto right-0 m-0 h-dvh max-h-none w-[min(960px,100vw)] max-w-full bg-white p-0 shadow-xl backdrop:bg-slate-950/30" aria-label="文档证据"><div className="sticky top-0 z-10 flex items-center justify-between border-b bg-white p-4"><h2 className="font-semibold">文档证据</h2><button autoFocus className="button-secondary" onClick={onClose}>关闭</button></div><div className="p-4">{citation.document_id?<KnowledgeDocumentViewer projectId={projectId} documentId={citation.document_id} versionId={citation.document_version_id} locator={citationLocator(citation)}/>:<p role="alert">证据已不可用</p>}</div></dialog>;
}

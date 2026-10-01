"use client";

import { useEffect, useRef, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { apiGet, apiPost, SourceToMartMapping, MartToYbtMapping } from "@/lib/api";
import { useProjectPermissions } from "@/lib/project-permissions";
import { MappingGenerationProvenance } from "@/components/MappingGenerationProvenance";
import { WorkspaceHeader } from "@/components/WorkspaceHeader";
import { ApiError } from "@/lib/http-response.mjs";

const KINDS = {source_to_mart: {title: "源到集市", path: "source-to-mart-mappings"}, mart_to_ybt: {title: "集市到一表通", path: "mart-to-ybt-mappings"}};
type Kind = keyof typeof KINDS;
type Mapping = SourceToMartMapping | MartToYbtMapping;

export default function Page() {
  const params = useParams<{mappingType: string; mappingId: string}>();
  if (!Object.prototype.hasOwnProperty.call(KINDS, params.mappingType) || !/^[1-9]\d*$/.test(params.mappingId)) return <p role="alert" className="p-6">映射地址无效。</p>;
  return <DraftEditor key={`${params.mappingType}:${params.mappingId}`} kind={params.mappingType as Kind} id={Number(params.mappingId)}/>;
}

function DraftEditor({kind, id}: {kind: Kind; id: number}) {
  const [mapping, setMapping] = useState<Mapping | null>(null);
  const [busy, setBusy] = useState(false), [error, setError] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [notice, setNotice] = useState("");
  const alive = useRef(false), flight = useRef(false);
  const permissions = useProjectPermissions(mapping?.project_id);
  const base = `/${KINDS[kind].path}/${id}`;
  useEffect(() => {
    alive.current = true;
    const controller = new AbortController();
    setError(""); setMapping(null);
    apiGet<Mapping>(base, {signal: controller.signal}).then(setMapping).catch(cause => {
      if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : "读取失败");
    });
    return () => {alive.current = false;controller.abort();};
  }, [base, attempt]);
  const editable = mapping?.mapping_status === "draft" && !mapping.final_content?.trim() && permissions.can("technical.edit");
  async function action(operation: "generate-draft" | "adopt-ai-draft") {
    if (!editable || flight.current || (operation === "adopt-ai-draft" && !confirmed)) return;
    flight.current = true; setBusy(true);setError("");setNotice("");
    try {
      let payload = {};
      if (operation === "adopt-ai-draft") {
        if (!globalThis.crypto?.subtle) throw new Error("当前连接无法核验候选正文，请使用安全连接重新打开页面。");
        const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(mapping?.ai_generated_content || ""));
        payload = {expected_draft_hash: Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, "0")).join("")};
      }
      const result = await apiPost<Mapping>(`${base}/${operation}`, payload);
      if (alive.current) {setMapping(result);setConfirmed(false);setNotice(operation === "generate-draft" ? "候选已生成，尚未采用。" : "已人工采用为最终内容，仍须完成审核。");}
    } catch (cause) {
      if (alive.current) {
        setConfirmed(false);
        if (cause instanceof ApiError && cause.errorCode === "mapping_draft_changed") {
          setMapping(null);
          setError("候选草稿已变化，请重新读取并核对后采用。");
        } else setError(cause instanceof Error ? cause.message : "操作失败");
      }
    }
    finally {flight.current = false;if (alive.current) setBusy(false);}
  }
  return <main><WorkspaceHeader title={`${KINDS[kind].title}草稿核验`} meta="当前映射 · AI 候选与人工最终内容分别保留"/>
    <div className="mx-auto max-w-5xl space-y-4 p-6">
      {error && <p role="alert" className="text-red-700">{error} <button className="underline" disabled={busy} onClick={() => {setConfirmed(false);setAttempt(value => value + 1);}}>重新读取</button></p>}
      {!mapping && !error && <p role="status">正在读取映射…</p>}
      {mapping && <>
        <p className="text-sm">{mapping.mapping_name || `映射 #${id}`} · 状态：{mapping.mapping_status} · <Link className="underline" href={`/workspace?projectId=${mapping.project_id}`}>返回项目工作台</Link></p>
        <section className="panel p-4" aria-label="跨层映射草稿">
          <h2 className="font-semibold">AI 候选草稿</h2><p className="mt-2 whitespace-pre-wrap break-words text-sm">{mapping.ai_generated_content || "尚未生成候选。"}</p>
          <div className="mt-4"><MappingGenerationProvenance mappingType={kind} mappingId={id} draftText={mapping.ai_generated_content}/></div>
          <button className="button-secondary mt-3" disabled={!editable || busy} onClick={() => void action("generate-draft")}>{busy ? "正在处理…" : "生成候选草稿"}</button>
        </section>
        <section className="panel p-4" aria-label="跨层映射人工内容">
          <h2 className="font-semibold">人工最终内容</h2><p className="mt-2 whitespace-pre-wrap break-words text-sm">{mapping.final_content || "尚未采用，AI 草稿不会自动填入。"}</p>
          {!editable && <p className="mt-2 text-xs text-amber-800">已有人工内容、非草稿状态或缺少编辑权限时不能生成或覆盖；审核中的操作由服务端进一步校验。</p>}
          {editable && <><label className="mt-3 flex items-center gap-2 text-sm"><input type="checkbox" checked={confirmed} disabled={busy || !mapping.ai_generated_content} onChange={event => setConfirmed(event.target.checked)}/>我已核对候选内容与出处，确认采用</label>
            <button className="button-primary mt-3" disabled={busy || !confirmed || !mapping.ai_generated_content} onClick={() => void action("adopt-ai-draft")}>采用为人工最终内容</button></>}
        </section>
        {notice && <p role="status" className="text-sm text-emerald-800">{notice}</p>}
      </>}
    </div>
  </main>;
}

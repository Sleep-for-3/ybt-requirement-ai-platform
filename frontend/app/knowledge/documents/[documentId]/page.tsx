"use client";

import { KnowledgeDocumentViewer } from "@/components/knowledge/KnowledgeDocumentViewer";
import { knowledgeLabel } from "@/lib/knowledge-contract.mjs";
import { Ban, CheckCircle2, PlayCircle, RefreshCw, Send } from "lucide-react";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import { useProjectWorkspace } from "@/components/ProjectContext";
import { WorkspaceHeader } from "@/components/WorkspaceHeader";
import { AsyncActionButton } from "@/components/feedback/AsyncActionButton";
import { ConfirmDialog } from "@/components/feedback/ConfirmDialog";
import { JobProgressPanel } from "@/components/jobs/JobProgressPanel";
import { useAsyncAction } from "@/hooks/useAsyncAction";
import { useJobPolling } from "@/hooks/useJobPolling";
import { BackgroundJobSummary, KnowledgeRagDocument, KnowledgeUnit, apiDelete, apiGet, apiPost } from "@/lib/api";

const DOCUMENT_TABS = ["原文预览", "解析内容", "版本记录", "索引状态"];
type DocumentVersion={id:number;version_no:number;file_name:string;parse_status:string;lifecycle_status?:string;regulatory_version?:string|null;internal_revision?:string|null;publisher?:string|null;published_at?:string|null;effective_at?:string|null;expires_at?:string|null;replaces_version_id?:number|null;change_note?:string|null;reviewed_by?:string|null;reviewed_at?:string|null;activated_at?:string|null;warnings_json?:string[];parse_summary_json?:{unit_count?:number;semantic_index_status?:string}};
const LIFE:Record<string,string>={draft:"草稿",pending_review:"待审核",approved:"已审核",active:"已生效",superseded:"已替代",withdrawn:"已撤回"};

export default function Page() {
  const id = Number(useParams<{ documentId: string }>().documentId);
  const { projectId } = useProjectWorkspace();
  const [tab,setTab]=useState("原文预览");
  const [versionId,setVersionId]=useState<number|undefined>();
  const [error,setError]=useState("");
  const [doc, setDoc] = useState<KnowledgeRagDocument | null>(null);
  const [units, setUnits] = useState<KnowledgeUnit[]>([]);
  const [versions, setVersions] = useState<DocumentVersion[]>([]);
  const [activeJob, setActiveJob] = useState<BackgroundJobSummary | null>(null);
  const [confirmDisable, setConfirmDisable] = useState(false);
  const reindexAction = useAsyncAction<KnowledgeRagDocument | BackgroundJobSummary>({
    successMessage: (result) => "job_type" in result
      ? result.deduplicated ? "相同重建任务已存在，已打开当前任务" : "索引重建任务已提交"
      : "索引重建完成"
  });
  const disableAction = useAsyncAction<unknown>({ successMessage: "知识文档已禁用" });
  const generation=useRef(0);
  const load=useCallback(async () => {
    if (!projectId) return;
    const request=++generation.current;
    try {
      const [document,parsed,history]=await Promise.all([
        apiGet<KnowledgeRagDocument>(`/knowledge/documents/${id}?project_id=${projectId}`),
        apiGet<KnowledgeUnit[]>(`/projects/${projectId}/knowledge/units?document_id=${id}`),
        apiGet<DocumentVersion[]>(`/knowledge/documents/${id}/versions?project_id=${projectId}`)
      ]);
      if(request!==generation.current)return;
      setDoc(document);setUnits(parsed);setVersions(history);setVersionId(current=>current??document.current_version_id??history[0]?.id);setError("");
    }catch{if(request===generation.current)setError("文档已不可用或当前项目无访问权限。");}
  },[id,projectId]);
  const polledJob = useJobPolling(activeJob?.id, { initialJob: activeJob, onTerminal: load });

  useEffect(() => {
    setDoc(null);setUnits([]);setVersions([]);setVersionId(undefined);setError("");setActiveJob(null);
    if (id && projectId) void load();
    const counter=generation;
    return()=>{counter.current++;};
  }, [id, projectId,load]);

  async function reindex() {
    const result = await reindexAction.run(() => apiPost<KnowledgeRagDocument | BackgroundJobSummary>(`/knowledge/documents/${id}/reindex?project_id=${projectId}`, {}));
    if (!result) return;
    if ("job_type" in result) setActiveJob(result);
    else await load();
  }

  async function disableDocument() {
    const result = await disableAction.run(() => apiDelete(`/knowledge/documents/${id}?project_id=${projectId}`));
    if (result !== undefined) {
      setConfirmDisable(false);
      await load();
    }
  }

  async function govern(version:DocumentVersion, action:"submit-review"|"review"|"activate"){
    try{await apiPost(`/knowledge/document-versions/${version.id}/${action}?project_id=${projectId}`,{});await load();}
    catch(failure){setError(failure instanceof Error?failure.message:"版本治理操作失败");}
  }
  const parsedUnitCount=Number(doc?.parse_summary_json?.unit_count);
  const unitCount=Number.isFinite(parsedUnitCount)&&parsedUnitCount>0?parsedUnitCount:units.length;

  return (
    <main>
      <WorkspaceHeader title={doc?.file_name || "知识文档"} meta={`${knowledgeLabel(doc?.document_status)} / 解析 ${unitCount} 个知识单元 / ${doc?.current_version_id?`当前生效内部版本 ${doc.current_version_no}`:"尚无生效版本"}`} />
      <div className="mx-auto max-w-5xl space-y-4 p-4 lg:p-6">
        {!projectId?<p role="status">请先选择项目。</p>:null}{error?<p role="alert">{error}</p>:null}
        <div role="tablist" aria-label="文档内容" className="flex flex-wrap gap-2">{DOCUMENT_TABS.map((name,index)=><button key={name} role="tab" tabIndex={tab===name?0:-1} aria-selected={tab===name} className={tab===name?"button-primary":"button-secondary"} onClick={()=>setTab(name)} onKeyDown={event=>{
          if (!["ArrowLeft","ArrowRight","Home","End"].includes(event.key)) return;
          event.preventDefault();
          const next=event.key==="Home"?0:event.key==="End"?DOCUMENT_TABS.length-1:(index+(event.key==="ArrowRight"?1:-1)+DOCUMENT_TABS.length)%DOCUMENT_TABS.length;
          setTab(DOCUMENT_TABS[next]);
          event.currentTarget.parentElement?.querySelectorAll<HTMLButtonElement>('[role="tab"]')[next]?.focus();
        }}>{name}</button>)}</div>
        {doc && doc.document_status !== "archived" ? <div className="flex justify-end" aria-label="文档操作">
          <AsyncActionButton
            actionStatus={disableAction.status}
            className="button-danger"
            disabled={!projectId}
            disabledReason={!projectId ? "请先选择项目" : undefined}
            onClick={() => setConfirmDisable(true)}
          >
            <Ban size={15} />
            禁用知识
          </AsyncActionButton>
        </div> : null}
        {(tab==="原文预览"||tab==="解析内容")&&projectId&&!error?<KnowledgeDocumentViewer key={`${projectId}-${id}-${versionId}`} projectId={projectId} documentId={id} versionId={versionId} parsedOnly={tab==="解析内容"}/>:null}
        {tab==="索引状态"?<><p>当前状态：{knowledgeLabel(doc?.document_status)}</p><div className="flex gap-2">
          <AsyncActionButton
            actionStatus={polledJob && ["queued", "running"].includes(polledJob.status) ? polledJob.status as "queued" | "running" : reindexAction.status}
            className="button-primary"
            disabled={!projectId || doc?.document_status === "archived"}
            disabledReason={!projectId ? "请先选择项目" : doc?.document_status === "archived" ? "已归档文档不能重建索引" : undefined}
            onClick={() => void reindex()}
          >
            <RefreshCw size={15} />
            重建索引
          </AsyncActionButton>
        </div></> : null}
        {polledJob ? <JobProgressPanel job={polledJob} resultHref={`/knowledge/documents/${id}`} /> : null}
        <ConfirmDialog
          busy={disableAction.isRunning}
          danger
          description="禁用后，该文档的知识单元将不再参与检索。此操作会保留审计和历史版本。"
          onCancel={() => setConfirmDisable(false)}
          onConfirm={disableDocument}
          open={confirmDisable}
          title="确认禁用知识文档？"
          confirmText="确认禁用"
        />

        {tab==="版本记录"?<section className="panel p-5">
          <h2 className="mb-2 font-semibold">版本记录</h2>
          <p className="mb-4 text-sm text-slate-500">监管版本与内部修订版本分别展示；解析失败或未激活版本不会替换当前问答语料。</p>
          {versions.some(v=>v.parse_status==="failed")&&doc?.current_version_id?<p className="mb-4 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm">存在解析失败的新版本；问答仍在使用内部版本 {doc.current_version_no}。</p>:null}
          {versions.length?<ul className="divide-y">{versions.map(v=><li className="grid gap-3 py-4 md:grid-cols-[1fr_1fr_auto] md:items-start" key={v.id}>
            <div>
              <strong>内部版本 {v.version_no}</strong>
              <p className="mt-1 text-sm text-slate-500">监管版本：{v.regulatory_version||"未提供"} · 内部修订：{v.internal_revision||`R${v.version_no}`}</p>
              <p className="mt-1 text-sm">{v.file_name} · {knowledgeLabel(v.parse_status)} · <span className={v.lifecycle_status==="active"?"badge-success":v.lifecycle_status==="pending_review"?"badge-warning":"badge-neutral"}>{LIFE[v.lifecycle_status||""]||"历史导入"}</span></p>
              {typeof v.parse_summary_json?.unit_count==="number"?<p className="mt-1 text-sm text-slate-500">解析知识单元：{v.parse_summary_json.unit_count}</p>:null}
              {v.warnings_json?.length?<details className="mt-2 text-sm text-amber-800"><summary className="cursor-pointer font-medium">查看解析警告（{v.warnings_json.length}）</summary><ul className="mt-1 list-disc space-y-1 pl-5">{v.warnings_json.map((warning,index)=><li key={`${v.id}-${index}`}>{warning}</li>)}</ul></details>:null}
            </div>
            <div className="text-sm text-slate-600">
              <p>发布机构：{v.publisher||doc?.publisher||"未提供"}</p>
              <p>生效日期：{v.effective_at?new Date(v.effective_at).toLocaleDateString("zh-CN"):"未提供"}</p>
              <p className="mt-1 break-words">变更说明：{v.change_note||"未填写"}</p>
            </div>
            <div className="flex flex-wrap gap-2">
              <button className="button-secondary" onClick={()=>{setVersionId(v.id);setTab("原文预览");}}>阅读此版本</button>
              {v.lifecycle_status==="draft"&&v.parse_status!=="failed"?<button className="button-primary" onClick={()=>void govern(v,"submit-review")}><Send size={15}/>提交审核</button>:null}
              {v.lifecycle_status==="pending_review"&&v.parse_status!=="failed"?<button className="button-primary" onClick={()=>void govern(v,"review")}><CheckCircle2 size={15}/>审核通过</button>:null}
              {v.lifecycle_status==="approved"?<button className="button-primary" onClick={()=>void govern(v,"activate")}><PlayCircle size={15}/>激活生效</button>:null}
            </div>
          </li>)}</ul>:<p>暂无版本记录</p>}
        </section>:null}
      </div>
    </main>
  );
}

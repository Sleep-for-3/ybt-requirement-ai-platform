"use client";

import { Database, FileText, RefreshCw, Upload } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useCallback, useEffect, useRef, useState } from "react";

import { useProjectWorkspace } from "@/components/ProjectContext";
import { StatefulLink } from "@/components/StatefulLink";
import { WorkspaceHeader } from "@/components/WorkspaceHeader";
import { knowledgeLabel } from "@/lib/knowledge-contract.mjs";
import { AsyncActionButton } from "@/components/feedback/AsyncActionButton";
import { ConfirmDialog } from "@/components/feedback/ConfirmDialog";
import { JobProgressPanel } from "@/components/jobs/JobProgressPanel";
import { useAsyncAction } from "@/hooks/useAsyncAction";
import { useJobPolling } from "@/hooks/useJobPolling";
import { BackgroundJobSummary, KnowledgeRagDocument, apiGet, apiPost, uploadForm } from "@/lib/api";

type IndexVersion = {
  id: number;
  model_name: string;
  vector_dimension: number;
  status: string;
  document_count: number;
  chunk_count: number;
  created_at: string;
  activated_at?: string | null;
};

type SemanticStatus = {
  mode: string;
  formal_ready: boolean;
  embedding_provider: string;
  embedding_model?: string | null;
  vector_dimension?: number | null;
  vector_store: string;
  milvus_health: { healthy?: boolean; status?: string };
  active_index?: IndexVersion | null;
  active_index_current: boolean;
  document_count: number;
  chunk_count: number;
  last_indexed_at?: string | null;
  last_evaluated_at?: string | null;
};

type ReindexResponse = Partial<BackgroundJobSummary> & {
  already_active: boolean;
  job_id?: number;
  message: string;
};

const STATUS_BADGE: Record<string, string> = {
  indexed: "badge-success",
  parsed: "badge-info",
  parsing: "badge-warning",
  pending: "badge-warning",
  failed: "badge-danger",
  archived: "badge-neutral"
};

const GRID_COLS = "grid-cols-[minmax(150px,1fr)_110px_70px_55px_85px] min-w-[520px]";

export default function Page() {
  const { projectId } = useProjectWorkspace();
  const router = useRouter();
  const [items, setItems] = useState<KnowledgeRagDocument[]>([]);
  const generation = useRef(0);
  const [loadError, setLoadError] = useState("");
  const [semanticStatus, setSemanticStatus] = useState<SemanticStatus | null>(null);
  const [indexVersions, setIndexVersions] = useState<IndexVersion[]>([]);
  const [confirmReindex, setConfirmReindex] = useState(false);
  const [confirmForceReindex, setConfirmForceReindex] = useState(false);
  const [activeJob, setActiveJob] = useState<BackgroundJobSummary | null>(null);
  const uploadAction = useAsyncAction<KnowledgeRagDocument | BackgroundJobSummary>({
    successMessage: (result) => "job_type" in result
      ? result.deduplicated ? "相同知识摄取任务已在执行，已打开当前任务" : "文件已上传，知识摄取任务已提交"
      : "知识文档解析和索引完成"
  });
  const reindexAction = useAsyncAction<ReindexResponse>({
    successMessage: (result) => result.message || "正式语义索引任务已提交"
  });

  const load = useCallback(async () => {
    const request = ++generation.current;
    if (projectId) {
      setLoadError("");
      try {
      const [documents, status, versions] = await Promise.all([
        apiGet<KnowledgeRagDocument[]>(`/projects/${projectId}/knowledge/documents`),
        apiGet<SemanticStatus>(`/projects/${projectId}/semantic-index/status`),
        apiGet<IndexVersion[]>(`/projects/${projectId}/semantic-index/versions`)
      ]);
      if (request !== generation.current) return;
      setItems(documents);
      setSemanticStatus(status);
      setIndexVersions(versions);
      } catch {
        if (request === generation.current) setLoadError("文档列表暂不可用，请确认项目权限或稍后重试。");
      }
    }
  }, [projectId]);

  useEffect(() => {
    setItems([]); setSemanticStatus(null); setIndexVersions([]); setActiveJob(null);
    void load();
    return () => { generation.current += 1; };
  }, [load]);

  const polledJob = useJobPolling(activeJob?.id, {
    initialJob: activeJob,
    onTerminal: async (job) => {
      if (["completed", "partially_completed"].includes(job.status)) await load();
    }
  });
  const uploadButtonStatus = polledJob && ["queued", "running"].includes(polledJob.status)
    ? polledJob.status as "queued" | "running"
    : uploadAction.status;

  async function upload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!projectId) return;
    const formElement = event.currentTarget;
    const formData = new FormData(formElement);
    formData.forEach((value,key)=>{if(typeof value==="string"&&!value.trim())formData.delete(key);});
    setActiveJob(null);
    const result = await uploadAction.run(() =>
      uploadForm<KnowledgeRagDocument | BackgroundJobSummary>(
        `/projects/${projectId}/knowledge/documents/upload`,
        formData
      )
    );
    if (result) {
      formElement.reset();
      if ("job_type" in result) {
        setActiveJob(result);
      } else {
        await load();
      }
    }
  }

  async function startFormalReindex(force = false) {
    if (!projectId) return;
    const result = await reindexAction.run(() =>
      apiPost<ReindexResponse>(`/projects/${projectId}/semantic-index/reindex`, { force })
    );
    if (!result) return;
    setConfirmReindex(false);
    if (result.already_active) {
      await load();
      setConfirmForceReindex(true);
      return;
    }
    const jobId = result.job_id || result.id;
    if (jobId) router.push(`/jobs/${jobId}`);
  }

  return (
    <main>
      <WorkspaceHeader title="知识文档" meta="版本、去重、解析状态与出处" />
      <div className="mx-auto max-w-6xl space-y-4 p-4 lg:p-6">
        {loadError ? <p role="alert" className="text-red-700">{loadError}</p> : null}
        <details><summary className="cursor-pointer text-sm text-slate-500">高级工具：索引状态</summary>
        <section className="panel">
          <div className="panel-header flex flex-wrap items-center justify-between gap-3">
            <div>
              <div className="flex items-center gap-2">
                <Database className="text-pine-700" size={18} />
                <h2 className="text-[15px] font-semibold text-ink">语义检索状态</h2>
                <span className={semanticStatus?.mode === "formal" && semanticStatus?.active_index_current ? "badge-success" : "badge-warning"}>
                  {semanticStatus?.mode !== "formal" ? "Mock 模式" : semanticStatus?.active_index_current ? "正式模式" : "待重新索引"}
                </span>
              </div>
              <p className="mt-1 text-xs text-slate-500">
                Chat 与 Embedding 独立配置；正式检索只读取已验证并激活的 Milvus 索引
              </p>
            </div>
            <div className="flex gap-2">
              <Link className="button-secondary" href="/evaluations">运行评测</Link>
              <AsyncActionButton
                actionStatus={reindexAction.status}
                className="button-primary"
                disabled={!semanticStatus?.formal_ready}
                disabledReason={semanticStatus?.formal_ready ? undefined : "请先配置真实 Embedding、向量维度和 Milvus"}
                loadingText="正在创建任务…"
                onClick={() => setConfirmReindex(true)}
              >
                <RefreshCw size={15} />
                重新构建语义索引
              </AsyncActionButton>
            </div>
          </div>
          <div className="panel-body grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <div className="stat-card"><div className="stat-label">Embedding</div><div className="mt-1 text-sm font-semibold text-ink">{semanticStatus?.embedding_provider || "—"} / {semanticStatus?.embedding_model || "—"}</div></div>
            <div className="stat-card"><div className="stat-label">向量与存储</div><div className="mt-1 text-sm font-semibold text-ink">{semanticStatus?.vector_dimension || "—"} 维 / {semanticStatus?.vector_store || "—"}</div></div>
            <div className="stat-card"><div className="stat-label">当前语料</div><div className="mt-1 text-sm font-semibold text-ink">{semanticStatus?.document_count ?? 0} 文档 / {semanticStatus?.chunk_count ?? 0} Chunk</div></div>
            <div className="stat-card">
              <div className="stat-label">Active 索引</div>
              <div className="mt-1 text-sm font-semibold text-ink">{semanticStatus?.active_index ? `v${semanticStatus.active_index.id}` : "尚未激活"} · Milvus {semanticStatus?.milvus_health?.healthy ? "正常" : "未就绪"}</div>
              <div className="mt-1 text-xs text-slate-500">索引 {semanticStatus?.last_indexed_at ? new Date(semanticStatus.last_indexed_at).toLocaleString("zh-CN", { hour12: false }) : "—"} · 评测 {semanticStatus?.last_evaluated_at ? new Date(semanticStatus.last_evaluated_at).toLocaleString("zh-CN", { hour12: false }) : "—"}</div>
            </div>
          </div>
        </section>

        {indexVersions.length ? (
          <section className="panel overflow-hidden">
            <div className="panel-header"><h2 className="text-[15px] font-semibold text-ink">索引版本</h2></div>
            <div className="overflow-x-auto">
              <div className="min-w-[780px]">
                <div className="grid-head grid grid-cols-[70px_minmax(0,1fr)_80px_110px_120px_180px_80px] gap-3">
                  <span>版本</span><span>模型</span><span>维度</span><span>状态</span><span>规模</span><span>激活时间</span><span>评测</span>
                </div>
                {indexVersions.map((version) => (
                  <div className="grid-row grid grid-cols-[70px_minmax(0,1fr)_80px_110px_120px_180px_80px] gap-3" key={version.id}>
                    <span>v{version.id}</span><span className="truncate">{version.model_name}</span><span>{version.vector_dimension}</span>
                    <span className={version.status === "active" ? "badge-success" : version.status === "failed" ? "badge-danger" : "badge-neutral"}>{version.status}</span>
                    <span>{version.document_count} / {version.chunk_count}</span>
                    <span>{version.activated_at ? new Date(version.activated_at).toLocaleString("zh-CN", { hour12: false }) : "—"}</span>
                    <Link className="font-medium text-pine-700 hover:underline" href="/evaluations">查看评测</Link>
                  </div>
                ))}
              </div>
            </div>
          </section>
        ) : null}

        </details>
        <form className="panel" onSubmit={upload}>
          <div className="panel-header">
            <h2 className="text-[15px] font-semibold text-ink">上传知识文档</h2>
          </div>
          <div className="panel-body grid gap-3 md:grid-cols-2 lg:grid-cols-3">
            <label className="text-sm">上传方式<select className="control mt-1" name="document_id"><option value="">新文档</option>{items.map(item=><option key={item.id} value={item.id}>为“{item.file_name}”上传新版本</option>)}</select></label>
            <label className="text-sm">选择文件<input className="control mt-1" name="file" required type="file" /></label>
            <label className="text-sm">来源类别<select className="control mt-1" name="source_category" required><option value="regulatory_formal">监管正式文件</option><option value="regulatory_qa">监管正式答疑</option><option value="internal_policy">行内制度</option><option value="internal_interpretation">行内解释</option><option value="business_material">业务沉淀</option><option value="technical_evidence">技术证据</option></select></label>
            <label className="text-sm">知识用途<select className="control mt-1" name="knowledge_type">
              <option value="regulatory_qa">监管答疑</option>
              <option value="regulatory_policy">监管制度</option>
              <option value="field_explanation">字段解释</option>
              <option value="historical_mapping">历史业务口径</option>
              <option value="historical_traceability">历史技术溯源</option>
              <option value="east_mapping">EAST 映射</option>
              <option value="business_research">业务调研</option>
              <option value="technical_research">技术调研</option>
              <option value="data_dictionary">数据字典</option>
              <option value="code_mapping">码值映射</option>
              <option value="manual_note">人工备注</option>
              <option value="sql_evidence">SQL 证据</option>
            </select></label>
            <label className="text-sm">可见范围<select className="control mt-1" name="knowledge_scope">
              <option value="project">项目</option>
              <option value="institution">银行</option>
              <option value="global">全局</option>
            </select></label>
            <label className="text-sm">保密级别<select className="control mt-1" name="confidentiality_level">
              <option value="internal">内部</option>
              <option value="public">公开</option>
              <option value="confidential">机密</option>
              <option value="restricted">受限</option>
            </select></label>
            <label className="text-sm">逻辑文档代码<input className="control mt-1" name="logical_code" placeholder="新文档可填写稳定业务标识" /></label>
            <label className="text-sm">监管文号<input className="control mt-1" name="regulatory_document_no" /></label>
            <label className="text-sm">监管版本<input className="control mt-1" name="regulatory_version" /></label>
            <label className="text-sm">内部修订版本<input className="control mt-1" name="internal_revision" placeholder="例如 R2" /></label>
            <label className="text-sm">发布机构<input className="control mt-1" name="publisher" /></label>
            <label className="text-sm">发布日期<input className="control mt-1" name="published_at" type="datetime-local" /></label>
            <label className="text-sm">生效日期<input className="control mt-1" name="effective_at" type="datetime-local" /></label>
            <label className="text-sm">失效日期<input className="control mt-1" name="expires_at" type="datetime-local" /></label>
            <label className="text-sm">适用机构<input className="control mt-1" name="applicable_institutions" placeholder="用逗号分隔机构名称" /></label>
            <label className="text-sm">适用字段<input className="control mt-1" name="applicable_fields" placeholder="用逗号分隔字段代码" /></label>
            <label className="text-sm">适用场景<input className="control mt-1" name="applicable_scenarios" placeholder="用逗号分隔已选场景编号" /></label>
            <label className="text-sm">银行名称<input className="control mt-1" name="institution_name" placeholder="仅银行作用域需要" /></label>
            <label className="text-sm md:col-span-2">变更说明<textarea className="control mt-1 min-h-20" name="change_note" placeholder="说明本次修订内容和依据" /></label>
            <AsyncActionButton actionStatus={uploadButtonStatus} className="button-primary" loadingText="正在上传…" type="submit">
              <Upload size={16} />
              上传草稿并解析
            </AsyncActionButton>
          </div>
        </form>

        {polledJob ? <JobProgressPanel job={polledJob} resultHref="/knowledge/documents" /> : null}

        {items.length ? (
          <section className="panel overflow-x-auto">
            <div className={`grid-head grid ${GRID_COLS}`}>
              <span>文件名</span>
              <span>类型</span>
              <span>作用域</span>
              <span>版本</span>
              <span>状态</span>
            </div>
            {items.map((item) => (
              <StatefulLink
                className={`grid-row grid ${GRID_COLS} items-center`}
                href={`/knowledge/documents/${item.id}`}
                key={item.id}
              >
                <strong className="truncate font-semibold text-ink">{item.file_name}</strong>
                <span className="text-slate-500">{knowledgeLabel(item.knowledge_type)}</span>
                <span className="text-slate-500">{knowledgeLabel(item.knowledge_scope)}</span>
                <span className="text-slate-500">{item.current_version_id?`内部版本 ${item.current_version_no}`:"无生效版本"}</span>
                <span>
                  <span className={STATUS_BADGE[item.document_status] || "badge-neutral"}>{knowledgeLabel(item.document_status)}</span>
                </span>
              </StatefulLink>
            ))}
          </section>
        ) : (
          <div className="empty-state">
            <FileText className="text-slate-300" size={28} />
            <p>还没有知识文档，先在上方上传第一份监管制度或答疑文件</p>
          </div>
        )}
      </div>
      <ConfirmDialog
        busy={reindexAction.isRunning}
        confirmText="创建重新索引任务"
        description={`将对当前 ${semanticStatus?.document_count ?? 0} 份文档、${semanticStatus?.chunk_count ?? 0} 个 Chunk 调用独立 Embedding 服务并写入新的 Milvus Collection，可能产生调用费用。旧 active 索引会保留到新索引验证通过。`}
        onCancel={() => setConfirmReindex(false)}
        onConfirm={() => startFormalReindex(false)}
        open={confirmReindex}
        title="确认重新构建正式语义索引？"
      />
      <ConfirmDialog
        busy={reindexAction.isRunning}
        confirmText="确认强制重建"
        description="当前知识库已经使用相同模型和相同语料完成索引。强制重建会再次调用 Embedding 并可能产生费用；如只需验证效果，请取消并运行评测。"
        onCancel={() => setConfirmForceReindex(false)}
        onConfirm={async () => {
          setConfirmForceReindex(false);
          await startFormalReindex(true);
        }}
        open={confirmForceReindex}
        title="相同索引已经 Active"
      />
    </main>
  );
}

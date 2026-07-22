"use client";

import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { CheckCircle2, Download, FileCheck2, GitCompare, Play, RefreshCw, Send, Sheet } from "lucide-react";

import { WorkspaceHeader } from "@/components/WorkspaceHeader";
import { BackgroundJobSummary, DeliverablePackage, DeliverablePackageVersion, ValidationResult, apiDownload, apiGet, apiPost } from "@/lib/api";
import { useProjectPermissions } from "@/lib/project-permissions";

type ActionResult = { package?:DeliverablePackage;job?:BackgroundJobSummary;error_count?:number;warning_count?:number;issues?:ValidationResult["issues"];workflow_instance?:{id:number;status:string;current_step?:string|null};version?:DeliverablePackageVersion;idempotent?:boolean };

export default function Page() {
  const packageId = Number(useParams().packageId);
  const [item, setItem] = useState<DeliverablePackage | null>(null);
  const permissions = useProjectPermissions(item?.project_id);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState("");
  const [compareIds, setCompareIds] = useState<[string,string]>(["",""]);

  async function load() {
    try { setItem(await apiGet(`/deliverables/${packageId}`)); }
    catch (error) { setMessage(readError(error)); }
  }
  useEffect(() => { if (packageId) void load(); }, [packageId]);

  async function act(path:string, success:string) {
    setBusy(path);
    try {
      const result = await apiPost<ActionResult>(`/deliverables/${packageId}/${path}`, {});
      const suffix = result.job ? `任务 #${result.job.id}：${result.job.status}（${result.job.progress}%）` : result.version ? `正式版本 v${result.version.version_no}${result.idempotent ? "（幂等复用）" : ""}` : result.error_count !== undefined ? `${result.error_count} 个错误，${result.warning_count || 0} 个告警` : "";
      setMessage(`${success}${suffix ? `；${suffix}` : ""}`); await load();
    } catch (error) { setMessage(readError(error)); }
    finally { setBusy(""); }
  }
  async function download(path:string, fallback:string) {
    try { const file = await apiDownload(path); saveBlob(file.blob, file.fileName || fallback); }
    catch (error) { setMessage(readError(error)); }
  }
  async function compare() {
    if (!item || !compareIds[0] || !compareIds[1]) return;
    try { const result = await apiPost<{id:number}>(`/projects/${item.project_id}/caliber-comparisons`, {left_package_version_id:Number(compareIds[0]), right_package_version_id:Number(compareIds[1])}); setMessage(`版本比较已生成，比较记录 #${result.id}。`); }
    catch (error) { setMessage(readError(error)); }
  }

  if (!item) return <main><WorkspaceHeader title="交付包详情" meta="加载中" /><p className="mx-auto max-w-5xl p-6 text-sm">{message || "正在读取服务端状态…"}</p></main>;
  const validation = item.summary_json.validation;
  const renderValidation = item.summary_json.render_validation;
  const canGenerate = permissions.can("deliverable.generate") && !["generating","pending_review"].includes(item.status);
  const canReview = permissions.can("deliverable.review");
  const canExport = permissions.can("deliverable.export");

  return <main>
    <WorkspaceHeader title={item.package_name} meta={`${statusLabel(item.status)} · 正式版本 v${item.version_no}`} />
    <div className="mx-auto max-w-7xl space-y-5 p-6">
      <section className="panel flex flex-wrap gap-2 p-4">
        {canGenerate ? <button className="button-primary" disabled={Boolean(busy)} onClick={() => act("generate", "交付内容生产已完成")}><Play size={15} />生成交付内容</button> : null}
        <button className="button-secondary" disabled={Boolean(busy)} onClick={load}><RefreshCw size={15} />重新计算准备度</button>
        {canGenerate ? <button className="button-secondary" disabled={Boolean(busy)} onClick={() => act("validate", "正式校验已执行")}><FileCheck2 size={15} />执行正式校验</button> : null}
        {canExport ? <button className="button-secondary" disabled={Boolean(busy) || item.status === "generating"} onClick={() => act("render", "正式 Excel 渲染已完成")}><Sheet size={15} />渲染正式 Excel</button> : null}
        {canReview ? <button className="button-secondary" disabled={Boolean(busy) || item.status !== "generated"} onClick={() => act("submit-review", "已提交最终审核")}><Send size={15} />提交最终审核</button> : null}
        {canReview ? <button className="button-primary" disabled={Boolean(busy) || item.status !== "pending_review"} onClick={() => act("approve", "批准完成")}><CheckCircle2 size={15} />批准正式版本</button> : null}
        {canExport && item.generated_file_id ? <button className="button-secondary" onClick={() => download(`/deliverables/${packageId}/download`, "deliverable.xlsx")}><Download size={15} />下载当前预览</button> : null}
      </section>
      {message ? <p className="panel p-3 text-sm">{message}</p> : null}

      <section className="grid gap-3 md:grid-cols-3 xl:grid-cols-6">
        <Stat label="当前状态" value={statusLabel(item.status)} /><Stat label="审核步骤" value={item.workflow?.current_step || "尚未提交"} /><Stat label="负责人" value={item.workflow?.current_assignee_user_id ? `用户 #${item.workflow.current_assignee_user_id}` : item.workflow?.current_assignee_role || "待分配"} /><Stat label="字段完成" value={`${item.approved_field_count}/${item.field_count}`} /><Stat label="真实血缘" value={`${item.lineage_record_count || 0} 条`} /><Stat label="脚本影响" value={`${item.change_impact_record_count || 0} 条`} />
      </section>
      <section className="grid gap-4 md:grid-cols-2"><JobCard title="内容生成任务" job={item.generation_job} /><JobCard title="Excel 渲染任务" job={item.render_job} /></section>

      {(validation?.issues.length || renderValidation?.issues.length) ? <section className="panel overflow-hidden"><div className="panel-header font-semibold">校验与渲染问题</div>{[...(validation?.issues || []), ...(renderValidation?.issues || [])].map((issue, index) => <div className="grid gap-2 border-b p-3 text-sm md:grid-cols-[90px_180px_1fr]" key={`${issue.code}-${index}`}><span className={issue.severity === "error" ? "text-coral" : "text-amber-700"}>{issue.severity}</span><code>{issue.code}</code><span>{issue.message}{issue.sheet_name ? ` · ${issue.sheet_name}${issue.cell ? `!${issue.cell}` : ""}` : ""}</span></div>)}</section> : null}

      <section className="panel overflow-hidden">
        <div className="panel-header flex items-center justify-between"><b>字段生产进度与阻断原因</b><span className="text-xs text-slate-500">阻断 {item.blocking_field_count} · 高优问题 {item.high_priority_question_count} · 未审核影响 {item.unreviewed_impact_count}</span></div>
        {item.items.map(field => { const readiness = field.readiness || field.validation_result_json; return <div className="border-b p-4 text-sm" key={field.id}>
          <div className="grid gap-3 md:grid-cols-[100px_130px_1fr_1fr]"><b>字段 #{field.field_order}</b><span>{statusLabel(readiness?.status || field.field_status)}</span><div><div className="text-xs text-slate-500">业务口径摘要</div><p className="mt-1 whitespace-pre-wrap">{field.business_summary || "待生成"}</p></div><div><div className="text-xs text-slate-500">技术溯源摘要</div><p className="mt-1 whitespace-pre-wrap">{field.technical_summary || "待生成"}</p></div></div>
          <div className="mt-3 flex flex-wrap gap-2 text-xs"><Tag text={`证据 ${Math.round((readiness?.evidence_completeness ?? field.evidence_completeness) * 100)}%`} /><Tag text={`来源→集市 ${readiness?.source_to_mart_status || "未知"}`} /><Tag text={`集市→一表通 ${readiness?.mart_to_ybt_status || "未知"}`} /><Tag text={`待确认 ${readiness?.open_question_count ?? field.open_question_count}`} /></div>
          {readiness?.blocking_reasons?.length ? <ul className="mt-3 space-y-1 rounded bg-rose-50 p-3 text-xs text-rose-800">{readiness.blocking_reasons.map(reason => <li key={reason.code}><code>{reason.code}</code>：{reason.message}</li>)}</ul> : null}
        </div>; })}
      </section>

      <section className="grid gap-5 lg:grid-cols-2">
        <div className="panel overflow-hidden"><div className="panel-header font-semibold">待确认问题</div>{item.questions?.map(question => <div className="border-b p-3 text-sm" key={question.id}><div className="flex justify-between gap-3"><b>{question.question_text}</b><span>{question.priority} · {question.question_status}</span></div><p className="mt-1 text-xs text-slate-500">{question.question_type} · {question.assigned_role || "未分派"}{question.resolution_text ? ` · 回答：${question.resolution_text}` : ""}</p></div>)}{!item.questions?.length ? <p className="p-4 text-sm text-slate-500">暂无待确认问题。</p> : null}</div>
        <div className="panel overflow-hidden"><div className="panel-header font-semibold">正式版本</div>{item.versions?.map(version => <div className="flex items-center justify-between border-b p-3 text-sm" key={version.id}><div><b>v{version.version_no}</b><div className="text-xs text-slate-500">审核流 #{version.workflow_instance_id || "-"} · {version.approved_at ? new Date(version.approved_at).toLocaleString() : "-"}</div></div>{canExport ? <button className="button-secondary" onClick={() => download(`/deliverable-package-versions/${version.id}/download`, `deliverable-v${version.version_no}.xlsx`)}><Download size={14} />下载正式版本</button> : null}</div>)}{!item.versions?.length ? <p className="p-4 text-sm text-slate-500">尚无已批准正式版本。</p> : null}</div>
      </section>

      {item.versions && item.versions.length >= 2 ? <section className="panel flex flex-wrap items-end gap-3 p-4"><label className="text-xs">左侧版本<select className="control mt-1" value={compareIds[0]} onChange={event => setCompareIds([event.target.value, compareIds[1]])}><option value="">选择版本</option>{item.versions.map(version => <option value={version.id} key={version.id}>v{version.version_no}</option>)}</select></label><label className="text-xs">右侧版本<select className="control mt-1" value={compareIds[1]} onChange={event => setCompareIds([compareIds[0], event.target.value])}><option value="">选择版本</option>{item.versions.map(version => <option value={version.id} key={version.id}>v{version.version_no}</option>)}</select></label><button className="button-secondary" disabled={!compareIds[0] || !compareIds[1] || compareIds[0] === compareIds[1]} onClick={compare}><GitCompare size={15} />比较版本</button></section> : null}
    </div>
  </main>;
}

function Stat({label, value}:{label:string;value:string}) { return <div className="panel p-3"><div className="text-xs text-slate-500">{label}</div><b className="mt-1 block">{value}</b></div>; }
function Tag({text}:{text:string}) { return <span className="rounded bg-slate-100 px-2 py-1">{text}</span>; }
function JobCard({title, job}:{title:string;job?:BackgroundJobSummary|null}) { return <div className="panel p-4"><div className="flex justify-between"><b>{title}</b><span className="text-sm">{job?.status || "尚未启动"}</span></div><div className="mt-3 h-2 overflow-hidden rounded bg-slate-100"><div className="h-full bg-pine" style={{width:`${job?.progress || 0}%`}} /></div><p className="mt-2 text-xs text-slate-500">{job?.current_step || "无运行阶段"}{job?.error_message ? ` · ${job.error_message}` : ""}</p></div>; }
function statusLabel(value:string) { return ({not_started:"未开始",pending_business_confirmation:"待业务确认",pending_technical_confirmation:"待技术确认",pending_mapping_review:"待映射审核",blocked:"已阻断",approved:"已批准",draft:"草稿",generating:"生成中",generated:"已渲染",pending_review:"最终审核中",render_failed:"渲染失败",generation_failed:"生成失败",validation_failed:"校验失败",cancelled:"已取消",rejected:"已驳回"} as Record<string,string>)[value] || value; }
function saveBlob(blob:Blob, name:string) { const url = URL.createObjectURL(blob); const link = document.createElement("a"); link.href = url; link.download = name; link.click(); URL.revokeObjectURL(url); }
function readError(error:unknown) { return error instanceof Error ? error.message : "操作失败"; }

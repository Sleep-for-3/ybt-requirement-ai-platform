"use client";

import { useEffect, useMemo, useState } from "react";
import { Download, Filter, Send } from "lucide-react";

import { useProjectWorkspace } from "@/components/ProjectContext";
import { WorkspaceHeader } from "@/components/WorkspaceHeader";
import { PendingQuestion, ProjectMembership, TargetField, TargetTable, apiDownload, apiGet, apiPatch, apiPost } from "@/lib/api";
import { useProjectPermissions } from "@/lib/project-permissions";

const ROLES = ["business_analyst","technical_analyst","business_reviewer","technical_reviewer","final_reviewer","project_manager","auditor"];

export default function Page() {
  const { projectId } = useProjectWorkspace();
  const permissions = useProjectPermissions(projectId);
  const [items, setItems] = useState<PendingQuestion[]>([]);
  const [tables, setTables] = useState<TargetTable[]>([]);
  const [fields, setFields] = useState<TargetField[]>([]);
  const [members, setMembers] = useState<ProjectMembership[]>([]);
  const [tableId, setTableId] = useState(""); const [fieldId, setFieldId] = useState(""); const [text, setText] = useState(""); const [priority, setPriority] = useState("medium");
  const [statusFilter, setStatusFilter] = useState(""); const [priorityFilter, setPriorityFilter] = useState(""); const [tableFilter, setTableFilter] = useState(""); const [fieldFilter, setFieldFilter] = useState("");
  const [answers, setAnswers] = useState<Record<number,string>>({}); const [message, setMessage] = useState("");

  async function load() {
    if (!projectId) return;
    try {
      const [questions, targetTables, targetFields, projectMembers] = await Promise.all([
        apiGet<PendingQuestion[]>(`/projects/${projectId}/questions`), apiGet<TargetTable[]>(`/target-tables?project_id=${projectId}`), apiGet<TargetField[]>(`/fields?project_id=${projectId}`), apiGet<ProjectMembership[]>(`/projects/${projectId}/members`),
      ]);
      setItems(questions); setTables(targetTables); setFields(targetFields); setMembers(projectMembers.filter(item => item.status === "active"));
    } catch (error) { setMessage(readError(error)); }
  }
  useEffect(() => { void load(); }, [projectId]);
  const visible = useMemo(() => items.filter(item => (!statusFilter || item.question_status === statusFilter) && (!priorityFilter || item.priority === priorityFilter) && (!tableFilter || item.target_table_id === Number(tableFilter)) && (!fieldFilter || item.target_field_id === Number(fieldFilter))), [items, statusFilter, priorityFilter, tableFilter, fieldFilter]);

  async function create() {
    if (!projectId || !tableId || !text.trim()) return;
    try { await apiPost(`/projects/${projectId}/questions`, {target_table_id:Number(tableId), target_field_id:fieldId ? Number(fieldId) : null, question_type:"other", question_text:text.trim(), priority}); setText(""); setMessage("问题已创建。"); await load(); }
    catch (error) { setMessage(readError(error)); }
  }
  async function answer(id:number) {
    const resolution = answers[id]?.trim(); if (!resolution) { setMessage("请先输入真实回答内容。"); return; }
    try { await apiPost(`/questions/${id}/answer`, {resolution_text:resolution}); setAnswers(current => ({...current, [id]:""})); setMessage("回答已提交，等待接受或驳回。"); await load(); }
    catch (error) { setMessage(readError(error)); }
  }
  async function decide(id:number, decision:string) { try { await apiPost(`/questions/${id}/${decision}`, {}); setMessage("问题状态已更新。"); await load(); } catch (error) { setMessage(readError(error)); } }
  async function assign(id:number, patch:Record<string,unknown>) { try { await apiPatch(`/questions/${id}`, patch); await load(); } catch (error) { setMessage(readError(error)); } }
  async function exportExcel() { if (!projectId) return; try { const file = await apiDownload(`/projects/${projectId}/questions/export`); saveBlob(file.blob, file.fileName); } catch (error) { setMessage(readError(error)); } }

  return <main>
    <WorkspaceHeader title="待确认问题工作台" meta="真实回答、分派、筛选与闭环" />
    <div className="mx-auto max-w-7xl space-y-5 p-6">
      {permissions.can("question.manage") ? <section className="panel grid gap-3 p-4 lg:grid-cols-[240px_240px_1fr_140px_auto]">
        <select className="control" value={tableId} onChange={event => {setTableId(event.target.value);setFieldId("");}}><option value="">选择目标表</option>{tables.map(table => <option value={table.id} key={table.id}>{table.table_name}</option>)}</select>
        <select className="control" value={fieldId} onChange={event => setFieldId(event.target.value)}><option value="">目标字段（可选）</option>{fields.filter(field => !tableId || field.target_table_id === Number(tableId)).map(field => <option value={field.id} key={field.id}>{field.field_code} {field.field_name}</option>)}</select>
        <input className="control" value={text} onChange={event => setText(event.target.value)} placeholder="输入需要确认的具体问题" />
        <select className="control" value={priority} onChange={event => setPriority(event.target.value)}><option value="low">低优先级</option><option value="medium">中优先级</option><option value="high">高优先级</option></select>
        <button className="button-primary" disabled={!tableId || !text.trim()} onClick={create}>创建问题</button>
      </section> : null}
      <section className="panel flex flex-wrap items-center gap-2 p-4"><Filter size={16} /><select className="control max-w-44" value={priorityFilter} onChange={event => setPriorityFilter(event.target.value)}><option value="">全部优先级</option><option value="high">高</option><option value="medium">中</option><option value="low">低</option></select><select className="control max-w-44" value={statusFilter} onChange={event => setStatusFilter(event.target.value)}><option value="">全部状态</option>{["open","assigned","answered","accepted","rejected","closed"].map(value => <option key={value}>{value}</option>)}</select><select className="control max-w-52" value={tableFilter} onChange={event => {setTableFilter(event.target.value);setFieldFilter("");}}><option value="">全部目标表</option>{tables.map(table => <option value={table.id} key={table.id}>{table.table_name}</option>)}</select><select className="control max-w-52" value={fieldFilter} onChange={event => setFieldFilter(event.target.value)}><option value="">全部目标字段</option>{fields.filter(field => !tableFilter || field.target_table_id === Number(tableFilter)).map(field => <option value={field.id} key={field.id}>{field.field_code}</option>)}</select>{permissions.can("deliverable.export") ? <button className="button-secondary ml-auto" onClick={exportExcel}><Download size={15} />导出 Excel</button> : null}</section>
      {message ? <p className="panel p-3 text-sm">{message}</p> : null}
      <section className="panel divide-y">
        {visible.map(question => <div className="p-4" key={question.id}><div className="flex flex-wrap justify-between gap-3"><div><b>{question.question_text}</b><p className="mt-1 text-xs text-slate-500">{question.question_type} · 表 #{question.target_table_id} · 字段 #{question.target_field_id || "-"} · 来源 {question.source_type || "人工"} #{question.source_id || "-"}</p></div><span>{question.priority} / {question.question_status}</span></div>
          {question.resolution_text ? <p className="mt-3 rounded bg-emerald-50 p-3 text-sm">当前回答：{question.resolution_text}</p> : null}
          <div className="mt-3 grid gap-2 lg:grid-cols-[1fr_auto_auto_auto]">
            {permissions.can("question.answer") ? <><textarea className="control min-h-10" value={answers[question.id] || ""} onChange={event => setAnswers(current => ({...current, [question.id]:event.target.value}))} placeholder="输入真实回答，不会使用固定占位内容" /><button className="button-secondary" disabled={!answers[question.id]?.trim()} onClick={() => answer(question.id)}><Send size={14} />提交回答</button></> : <div />}
            {permissions.can("question.manage") ? <select className="control" value={question.assigned_role || ""} onChange={event => assign(question.id, {assigned_role:event.target.value || null})}><option value="">分派角色</option>{ROLES.map(role => <option key={role}>{role}</option>)}</select> : null}
            {permissions.can("question.manage") ? <select className="control" value={question.assigned_user_id || ""} onChange={event => assign(question.id, {assigned_user_id:Number(event.target.value) || null})}><option value="">分派项目成员</option>{members.map(member => <option value={member.user_id} key={member.id}>用户 #{member.user_id} · {member.project_role}</option>)}</select> : null}
          </div>
          {permissions.can("question.manage") ? <div className="mt-3 flex flex-wrap gap-2"><button className="button-secondary" disabled={question.question_status !== "answered"} onClick={() => decide(question.id, "accept")}>接受</button><button className="button-danger" onClick={() => decide(question.id, "reject")}>驳回</button><button className="button-secondary" onClick={() => decide(question.id, "close")}>关闭</button></div> : null}
        </div>)}
        {!visible.length ? <p className="p-6 text-sm text-slate-500">没有符合当前筛选条件的问题。</p> : null}
      </section>
    </div>
  </main>;
}

function saveBlob(blob:Blob, name:string) { const url = URL.createObjectURL(blob); const link = document.createElement("a"); link.href = url; link.download = name; link.click(); URL.revokeObjectURL(url); }
function readError(error:unknown) { return error instanceof Error ? error.message : "操作失败"; }

"use client";

import { useParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { CheckCircle2, Download, Plus, ShieldCheck, Trash2, Upload } from "lucide-react";

import { WorkspaceHeader } from "@/components/WorkspaceHeader";
import { DeliverableTemplateVersion, ValidationResult, apiGet, apiPost, apiPostDownload, uploadForm } from "@/lib/api";
import { useProjectPermissions } from "@/lib/project-permissions";

type Detail = { id:number;project_id:number;template_name:string;template_type:string;enabled:boolean;is_default:boolean;versions:DeliverableTemplateVersion[] };
type ColumnDraft = { business_field:string;excel_column:string;write_mode:string;merge_strategy:string;required:boolean };
type SheetDraft = { business_section:string;sheet_name:string;header_row_start:number;header_row_end:number;data_start_row:number;repeat_direction:string;enabled:boolean;columns:ColumnDraft[] };

const SECTIONS = ["target_field","scenario_business_mapping","scenario_technical_lineage","source_to_mart","mart_to_ybt","pending_question","evidence","review_record","lineage","change_impact"];
const FIELDS: Record<string, string[]> = {
  target_field: ["target_table_code","target_table_name","target_field_code","target_field_name","regulatory_definition","data_type","field_order"],
  scenario_business_mapping: ["target_field_code","target_field_name","scenario_code","scenario_name","business_final_content","business_ai_draft","business_confirm_status","business_confidence_level","business_open_questions"],
  scenario_technical_lineage: ["target_field_code","target_field_name","scenario_code","scenario_name","technical_final_content","source_system_name","database_name","schema_name","source_table_name","source_field_name","technical_confirm_status","lineage_status"],
  source_to_mart: ["mapping_id","source_to_mart_final_content","source_to_mart_status","source_system_name","source_field_name","filter_condition","join_condition","code_mapping_rule","priority_rule","null_handling_rule"],
  mart_to_ybt: ["mapping_id","target_field_id","mart_to_ybt_final_content","mart_to_ybt_status","filter_condition","join_condition","code_mapping_rule","null_handling_rule"],
  pending_question: ["id","question_type","question_text","question_status","priority","assigned_role","resolution_text","target_table_id","target_field_id","scenario_id","source_type","source_id"],
  evidence: ["target_field_id","evidence_type","evidence_source","evidence_location","evidence_summary","citation","claim_type"],
  review_record: ["action","resource_type","resource_id","reviewer","approved_at","review_comment"],
  lineage: ["source_script","script_version","source_database","source_schema","source_table","source_column","target_database","target_schema","target_table","target_column","edge_type","transformation_summary","filter_summary","join_summary","lineage_status","reviewed_status","reviewed_at","affected_target_field_code","affected_mapping_type","affected_mapping_id"],
  change_impact: ["script_path","old_version_no","new_version_no","change_type","impact_severity","impact_status","affected_target_table","affected_target_field","affected_scenario","affected_source_to_mart_mapping","affected_mart_to_ybt_mapping","change_summary","review_decision","reviewer","reviewed_at"],
};

export default function Page() {
  const templateId = Number(useParams().templateId);
  const [detail, setDetail] = useState<Detail | null>(null);
  const [versionId, setVersionId] = useState<number | null>(null);
  const [mappings, setMappings] = useState<SheetDraft[]>([]);
  const [validation, setValidation] = useState<ValidationResult | null>(null);
  const [newFile, setNewFile] = useState<File | null>(null);
  const [message, setMessage] = useState("");
  const permissions = useProjectPermissions(detail?.project_id);
  const version = detail?.versions.find(item => item.id === versionId) || null;
  const immutable = version?.parse_status === "active" || !permissions.can("template.manage");
  const configuredSections = useMemo(() => new Set(mappings.filter(item => item.enabled).map(item => item.business_section)).size, [mappings]);

  async function loadDetail(preferredVersion?: number) {
    const item = await apiGet<Detail>(`/deliverable-templates/${templateId}`);
    setDetail(item);
    setVersionId(preferredVersion || versionId || item.versions[0]?.id || null);
  }
  useEffect(() => { void loadDetail().catch(error => setMessage(readError(error))); }, [templateId]);
  useEffect(() => {
    if (!versionId) return;
    setValidation(detail?.versions.find(item => item.id === versionId)?.validation || null);
    void apiGet<{sheet_mappings:Array<Record<string,unknown>>;column_mappings:Array<Record<string,unknown>>}>(`/deliverable-template-versions/${versionId}/preview`).then(result => {
      setMappings(result.sheet_mappings.map(raw => ({
        business_section: String(raw.business_section), sheet_name: String(raw.sheet_name), header_row_start: Number(raw.header_row_start), header_row_end: Number(raw.header_row_end), data_start_row: Number(raw.data_start_row), repeat_direction: String(raw.repeat_direction), enabled: Boolean(raw.enabled),
        columns: result.column_mappings.filter(column => column.template_sheet_mapping_id === raw.id).map(column => ({ business_field:String(column.business_field), excel_column:String(column.excel_column), write_mode:String(column.write_mode), merge_strategy:String(column.merge_strategy), required:Boolean(column.required) })),
      })));
    }).catch(error => setMessage(readError(error)));
  }, [versionId, detail]);

  function patchSheet(index:number, patch:Partial<SheetDraft>) { setMappings(rows => rows.map((row, i) => i === index ? {...row, ...patch} : row)); }
  function patchColumn(sheetIndex:number, columnIndex:number, patch:Partial<ColumnDraft>) { setMappings(rows => rows.map((row, i) => i === sheetIndex ? {...row, columns:row.columns.map((column, j) => j === columnIndex ? {...column, ...patch} : column)} : row)); }
  function addColumn(index:number) { const fields = FIELDS[mappings[index].business_section] || []; patchSheet(index, {columns:[...mappings[index].columns, {business_field:fields[0] || "target_field_code", excel_column:"A", write_mode:"overwrite", merge_strategy:"none", required:false}]}); }
  function removeColumn(sheetIndex:number, columnIndex:number) { patchSheet(sheetIndex, {columns:mappings[sheetIndex].columns.filter((_, index) => index !== columnIndex)}); }

  async function save() {
    if (!versionId || immutable) return;
    try { await apiPost(`/deliverable-template-versions/${versionId}/configure`, {sheet_mappings:mappings.filter(item => item.enabled)}); setMessage("映射已保存，请执行正式校验。"); await loadDetail(versionId); }
    catch (error) { setMessage(readError(error)); }
  }
  async function validate() {
    if (!versionId) return;
    try { const result = await apiPost<ValidationResult>(`/deliverable-template-versions/${versionId}/validate`, {}); setValidation(result); setMessage(result.valid ? "模板校验通过，可以激活。" : `模板存在 ${result.error_count} 个阻断错误。`); }
    catch (error) { setMessage(readError(error)); }
  }
  async function activate() {
    if (!versionId) return;
    try {
      const result = await apiPost<ValidationResult>(`/deliverable-template-versions/${versionId}/validate`, {}); setValidation(result);
      if (!result.valid) { setMessage(`激活已阻止：仍有 ${result.error_count} 个错误。`); return; }
      await apiPost(`/deliverable-template-versions/${versionId}/activate`, {}); setMessage("模板版本已激活并设为当前默认版本。"); await loadDetail(versionId);
    } catch (error) { setMessage(readError(error)); }
  }
  async function preview() {
    if (!versionId) return;
    try { const file = await apiPostDownload(`/deliverable-template-versions/${versionId}/preview-render`); saveBlob(file.blob, file.fileName); }
    catch (error) { setMessage(readError(error)); }
  }
  async function uploadVersion() {
    if (!detail || !newFile) return;
    const form = new FormData(); form.append("file", newFile); form.append("template_id", String(detail.id)); form.append("template_name", detail.template_name); form.append("template_type", detail.template_type);
    try { const uploaded = await uploadForm<{version:{id:number}}>(`/projects/${detail.project_id}/deliverable-templates/upload`, form); setMessage("新版本已上传，旧激活版本保持不可变。"); setNewFile(null); await loadDetail(uploaded.version.id); }
    catch (error) { setMessage(readError(error)); }
  }

  return <main>
    <WorkspaceHeader title={detail?.template_name || "模板配置"} meta="Sheet、业务字段、校验与版本激活" />
    <div className="mx-auto max-w-7xl space-y-5 p-6">
      <section className="panel grid gap-4 p-4 lg:grid-cols-[220px_1fr_auto]">
        <label className="text-xs">当前查看版本<select className="control mt-1" value={versionId || ""} onChange={event => setVersionId(Number(event.target.value))}>{detail?.versions.map(item => <option key={item.id} value={item.id}>v{item.version_no} / {statusLabel(item.parse_status)}</option>)}</select></label>
        <div className="grid grid-cols-2 gap-2 text-sm md:grid-cols-4"><Stat label="业务区域" value={`${configuredSections}/10`} /><Stat label="Sheet 映射" value={String(version?.enabled_sheet_mapping_count ?? mappings.filter(item => item.enabled).length)} /><Stat label="校验错误" value={String(validation?.error_count ?? 0)} /><Stat label="版本状态" value={statusLabel(version?.parse_status)} /></div>
        <div className="flex flex-wrap items-end gap-2">{permissions.can("template.manage") ? <button className="button-secondary" onClick={validate}><ShieldCheck size={15} />正式校验</button> : null}{permissions.can("template.manage") ? <button className="button-primary" disabled={immutable || validation?.valid !== true} onClick={activate}><CheckCircle2 size={15} />激活版本</button> : null}{permissions.can("template.manage") ? <button className="button-secondary" onClick={preview}><Download size={15} />预览下载</button> : null}</div>
      </section>
      {version?.parse_status === "active" ? <p className="rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">此版本已激活并保持不可变。如需调整，请在下方上传新版本。</p> : !permissions.can("template.manage") ? <p className="rounded-md border border-line bg-white p-3 text-sm text-slate-500">当前角色为 {permissions.role || "只读角色"}，只能查看模板配置。</p> : null}
      {message ? <p className="panel p-3 text-sm">{message}</p> : null}
      {validation?.issues.length ? <section className="panel overflow-hidden"><div className="panel-header font-semibold">模板校验问题</div>{validation.issues.map((issue, index) => <div className="grid gap-2 border-b p-3 text-sm md:grid-cols-[80px_180px_1fr]" key={`${issue.code}-${index}`}><span className={issue.severity === "error" ? "text-coral" : "text-amber-700"}>{issue.severity}</span><code>{issue.code}</code><span>{issue.message}{issue.sheet_name ? ` · ${issue.sheet_name}${issue.cell ? `!${issue.cell}` : ""}` : ""}</span></div>)}</section> : null}
      {mappings.map((sheet, sheetIndex) => <section className="panel p-4" key={`${sheet.sheet_name}-${sheetIndex}`}>
        <div className="grid gap-3 md:grid-cols-7"><label className="text-xs">启用<input className="ml-2" disabled={immutable} type="checkbox" checked={sheet.enabled} onChange={event => patchSheet(sheetIndex, {enabled:event.target.checked})} /></label><label className="text-xs md:col-span-2">Sheet<input className="control mt-1" value={sheet.sheet_name} readOnly /></label><label className="text-xs">业务区域<select className="control mt-1" disabled={immutable} value={sheet.business_section} onChange={event => patchSheet(sheetIndex, {business_section:event.target.value, columns:[]})}>{SECTIONS.map(section => <option key={section}>{section}</option>)}</select></label><NumberField label="表头起始行" value={sheet.header_row_start} disabled={immutable} onChange={value => patchSheet(sheetIndex, {header_row_start:value})} /><NumberField label="表头结束行" value={sheet.header_row_end} disabled={immutable} onChange={value => patchSheet(sheetIndex, {header_row_end:value})} /><NumberField label="数据起始行" value={sheet.data_start_row} disabled={immutable} onChange={value => patchSheet(sheetIndex, {data_start_row:value})} /></div>
        <label className="mt-3 block max-w-xs text-xs">展开方向<select className="control mt-1" disabled={immutable} value={sheet.repeat_direction} onChange={event => patchSheet(sheetIndex, {repeat_direction:event.target.value})}><option value="vertical">多来源纵向</option><option value="horizontal">多场景横向</option></select></label>
        <div className="mt-4 overflow-x-auto"><table className="w-full text-left text-sm"><thead><tr><th>平台业务字段</th><th>Excel 列</th><th>写入方式</th><th>合并方式</th><th>必填</th><th /></tr></thead><tbody>{sheet.columns.map((column, columnIndex) => <tr key={columnIndex}><td><select className="control" disabled={immutable} value={column.business_field} onChange={event => patchColumn(sheetIndex, columnIndex, {business_field:event.target.value})}>{(FIELDS[sheet.business_section] || []).map(field => <option key={field}>{field}</option>)}</select></td><td><input className="control w-24" disabled={immutable} value={column.excel_column} onChange={event => patchColumn(sheetIndex, columnIndex, {excel_column:event.target.value.toUpperCase()})} /></td><td><select className="control" disabled={immutable} value={column.write_mode} onChange={event => patchColumn(sheetIndex, columnIndex, {write_mode:event.target.value})}>{["overwrite","append","fill_blank_only","repeat_by_scenario","repeat_by_source"].map(value => <option key={value}>{value}</option>)}</select></td><td><select className="control" disabled={immutable} value={column.merge_strategy} onChange={event => patchColumn(sheetIndex, columnIndex, {merge_strategy:event.target.value})}>{["none","merge_same_target_field","merge_same_scenario","preserve_template"].map(value => <option key={value}>{value}</option>)}</select></td><td><input disabled={immutable} type="checkbox" checked={column.required} onChange={event => patchColumn(sheetIndex, columnIndex, {required:event.target.checked})} /></td><td><button className="button-secondary" disabled={immutable} onClick={() => removeColumn(sheetIndex, columnIndex)}><Trash2 size={14} /></button></td></tr>)}</tbody></table></div>
        <button className="button-secondary mt-3" disabled={immutable} onClick={() => addColumn(sheetIndex)}><Plus size={14} />添加列映射</button>
      </section>)}
      {permissions.can("template.manage") ? <section className="flex flex-wrap gap-2"><button className="button-primary" disabled={immutable} onClick={save}>保存映射</button><input className="control max-w-md" type="file" accept=".xlsx" onChange={event => setNewFile(event.target.files?.[0] || null)} /><button className="button-secondary" disabled={!newFile} onClick={uploadVersion}><Upload size={15} />上传新版本</button></section> : null}
    </div>
  </main>;
}

function Stat({label, value}:{label:string;value:string}) { return <div className="rounded bg-slate-50 p-2"><div className="text-xs text-slate-500">{label}</div><b>{value}</b></div>; }
function NumberField({label, value, disabled, onChange}:{label:string;value:number;disabled:boolean;onChange:(value:number)=>void}) { return <label className="text-xs">{label}<input className="control mt-1" min={1} disabled={disabled} type="number" value={value} onChange={event => onChange(Number(event.target.value))} /></label>; }
function statusLabel(status?:string|null) { return ({parsed:"待配置",configured:"已配置",active:"已激活"} as Record<string,string>)[status || ""] || status || "未知"; }
function readError(error:unknown) { return error instanceof Error ? error.message : "操作失败"; }
function saveBlob(blob:Blob, name:string) { const url = URL.createObjectURL(blob); const link = document.createElement("a"); link.href = url; link.download = name; link.click(); URL.revokeObjectURL(url); }

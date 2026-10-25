"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiDownload, apiGet, apiPost, uploadForm, uploadFormDownload } from "@/lib/api";

type Snapshot = { id: number; requirement_version: number; created_at: string };
type RenderArtifact = {
  id: number;
  format: string;
  file_name: string;
  file_size: number;
  file_sha256: string;
  template_sha256: string | null;
  renderer_version: string;
  config_version: string | null;
  source_kind: string;
  source_id: number;
  status: string;
  created_at: string | null;
};

type PreviewSheet = {
  name: string;
  rows: (string | null)[][];
  total_rows: number;
  total_columns: number;
  merged: string[];
  freeze_panes: string | null;
  truncated: boolean;
  truncated_cells: number;
  formulas_without_cache: number;
};

type DeliveryCheckItem = { key: string; label: string; ok: boolean; detail: string; severity: string };
type DeliveryCheckRecord = {
  id: number;
  artifact_id: number;
  checklist_version: string;
  verdict: string;
  blocking_keys: string[];
  created_by: number | null;
  created_at: string | null;
};
type DeliveryCheckHistory = { requirement_id: number; count: number; items: DeliveryCheckRecord[] };
type DeliveryChecklist = {
  checklist_version: string;
  artifact: {
    id: number;
    format: string;
    file_name: string;
    file_size: number;
    file_sha256: string;
    renderer_version: string;
    source_kind: string;
    source_id: number;
  };
  checks: DeliveryCheckItem[];
  summary: { blocking_total: number; blocking_failed: number; preview_truncated: boolean };
  verdict: string;
  blocking_keys: string[];
  note: string;
};

type StructureCheckItem = {
  key: string;
  label: string;
  ok: boolean;
  detail: string;
  severity: string;
};

type StructureCheckContract = {
  version: string;
  generation: number | null;
  renderer_version: string | null;
  label: string;
  required_keys: string[];
};

type FidelityColumn = {
  key: string;
  label: string;
  checked_count: number;
  matched_count: number;
  mismatched_count: number;
  blank_in_document_count: number;
  template_empty_count: number;
  samples: { field_code: string; expected: string; actual: string }[];
};

type FidelityPayload = {
  fidelity_version: string;
  artifact: { id: number; format: string; file_name: string; file_size: number; file_sha256: string; renderer_version: string };
  sheet_name: string;
  field_count: number;
  columns: FidelityColumn[];
  missing_in_document: string[];
  extra_in_document: string[];
  unexpected_values: { label: string; field_code: string; actual: string }[];
  verdict: "pass" | "fail";
  failed_labels: string[];
  note: string;
};

type StructureCheckPayload = {
  contract?: StructureCheckContract;
  skipped_keys?: string[];
  upgrade_hint?: string | null;
  check_version: string;
  /** xlsx（一表通调研表式）专属统计 */
  sheet_name?: string;
  field_rows?: number;
  column_count?: number;
  row_count?: number;
  groups?: string[];
  placeholder_cells?: number;
  /** docx（内置版式）专属统计 */
  section_titles?: string[];
  field_section_count?: number;
  checks: StructureCheckItem[];
  summary: { blocking_total: number; blocking_failed: number; info_total: number };
  verdict: "pass" | "fail";
  failed_keys: string[];
  artifact: { id: number; format: string; file_name: string; file_sha256: string; renderer_version: string };
};

type PreviewParagraph = { style: string; text: string; chars: number; truncated: boolean };
type PreviewTable = { rows: number; columns: number; header: string[]; sample_rows: string[][]; truncated: boolean };
type PreviewSection = { title: string; style: string; paragraphs: PreviewParagraph[]; tables: PreviewTable[]; chars: number };

type PreviewPayload = {
  preview_version: string;
  format: string;
  sheet_count: number;
  sheets: PreviewSheet[];
  section_count?: number;
  section_titles?: string[];
  sections?: PreviewSection[];
  max_blocks?: number;
  max_chars?: number;
  max_table_rows?: number;
  truncated_blocks?: number;
  max_rows: number;
  max_columns: number;
  note: string;
  artifact: {
    id: number;
    format: string;
    file_name: string;
    file_size: number;
    file_sha256: string;
    template_sha256: string | null;
    renderer_version: string;
    config_version: string | null;
    source_kind: string;
    source_id: number;
  };
};

type CheckResult = {
  artifact_id: number;
  format: string;
  file_name: string;
  file_size: number;
  file_sha256: string;
  template_sha256: string;
  renderer_version: string;
  config_version: string | null;
  warnings: string[];
  diagnostics: Record<string, unknown>;
};

type RegisteredTemplate = {
  id: number;
  name: string;
  version_no: number;
  format: string;
  file_sha256: string;
  config_digest: string;
  supported_scope?: { supported?: boolean; missing?: string[] };
};

function download(blob: Blob, fileName: string) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = fileName;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

export function RequirementTemplateExportPanel({ projectId, requirementId }: { projectId: number; requirementId: number }) {
  const base = `/projects/${projectId}/requirements/${requirementId}`;
  const [format, setFormat] = useState<"docx" | "xlsx">("docx");
  const [layout, setLayout] = useState<"standard" | "survey">("standard");
  const [templateFile, setTemplateFile] = useState<File | null>(null);
  const [config, setConfig] = useState("");
  const [sourceKind, setSourceKind] = useState<"draft_snapshot" | "formal_delivery">("draft_snapshot");
  const [sourceId, setSourceId] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [checked, setChecked] = useState<CheckResult | null>(null);
  const [templateId, setTemplateId] = useState("");
  const [registryName, setRegistryName] = useState("");
  const [preview, setPreview] = useState<PreviewPayload | null>(null);
  const [previewBusy, setPreviewBusy] = useState(false);
  const [previewSheetIndex, setPreviewSheetIndex] = useState(0);
  // 在预览里按字段定位：评审最常问"这份文件里 H010001 到底写了什么"，
  // 没有搜索就只能自己在一百多行/九个章节里翻。
  const [previewQuery, setPreviewQuery] = useState("");
  const previewNeedle = previewQuery.trim().toLowerCase();
  const previewSheet = preview && preview.format !== "docx"
    ? preview.sheets[Math.min(previewSheetIndex, Math.max(preview.sheets.length - 1, 0))] || null
    : null;
  // 命中只做"这一份文件里有没有这段文字"的判断：不猜字段语义、不跨产物搜索。
  const docxHitSections = useMemo(() => {
    const hits: number[] = [];
    if (!preview || preview.format !== "docx" || !previewNeedle) return hits;
    (preview.sections ?? []).forEach((section, index) => {
      const haystack = [
        section.title,
        ...section.paragraphs.map((paragraph) => paragraph.text),
        ...section.tables.flatMap((table) => [...table.header, ...table.sample_rows.flat()]),
      ].join("\n").toLowerCase();
      if (haystack.includes(previewNeedle)) hits.push(index);
    });
    return hits;
  }, [preview, previewNeedle]);
  // 多工作表的 xlsx：只查当前工作表会让"字段在另一个 sheet"看起来像查不到，
  // 所以先在所有工作表里找，再自动切到第一个命中的工作表。
  const sheetSearch = useMemo(() => {
    const counts: number[] = [];
    let targetIndex = -1;
    let rows: number[] = [];
    if (!preview || preview.format === "docx" || !previewNeedle) return { counts, targetIndex, rows };
    preview.sheets.forEach((sheet, sheetIndex) => {
      const hits: number[] = [];
      sheet.rows.forEach((row, rowIndex) => {
        const haystack = row.map((cell) => (cell == null ? "" : String(cell))).join(" ").toLowerCase();
        if (haystack.includes(previewNeedle)) hits.push(rowIndex);
      });
      counts.push(hits.length);
      if (targetIndex < 0 && hits.length) {
        targetIndex = sheetIndex;
        rows = hits;
      }
    });
    return { counts, targetIndex, rows };
  }, [preview, previewNeedle]);
  const sheetHitRows = sheetSearch.rows;
  const previewHitCount = preview && preview.format === "docx" ? docxHitSections.length : sheetHitRows.length;
  const firstDocxHit = docxHitSections[0] ?? -1;
  const firstSheetHit = sheetHitRows[0] ?? -1;
  const hitSheetName = preview && sheetSearch.targetIndex >= 0 ? preview.sheets[sheetSearch.targetIndex]?.name : null;
  const otherHitSheets = sheetSearch.counts.filter((count) => count > 0).length - (hitSheetName ? 1 : 0);
  useEffect(() => {
    if (sheetSearch.targetIndex >= 0 && sheetSearch.targetIndex !== previewSheetIndex) setPreviewSheetIndex(sheetSearch.targetIndex);
  }, [sheetSearch.targetIndex, previewSheetIndex, previewNeedle]);
  // 命中后滚到第一处：不滚用户还得自己找"命中 12 处"里的第一处。
  useEffect(() => {
    if (!previewNeedle) return;
    const target = document.querySelector('[data-preview-hit="first"]');
    if (target && typeof target.scrollIntoView === "function") target.scrollIntoView({ block: "center" });
  }, [previewNeedle, previewHitCount]);
  const [structureCheck, setStructureCheck] = useState<StructureCheckPayload | null>(null);
  const [structureBusy, setStructureBusy] = useState(false);
  const [fidelity, setFidelity] = useState<FidelityPayload | null>(null);
  const [fidelityBusy, setFidelityBusy] = useState(false);
  const locked = useRef(false);

  const access = useQuery({
    queryKey: ["requirement-template-export-access", projectId],
    queryFn: ({ signal }) => apiGet<{ effective_project_permissions?: Record<string, string[]> }>("/auth/me", { signal }),
  });
  const permissions = access.data?.effective_project_permissions?.[String(projectId)] || [];
  const canExport = permissions.includes("deliverable.export");

  const snapshots = useQuery({
    queryKey: ["requirement-snapshots", projectId, requirementId],
    enabled: canExport,
    queryFn: ({ signal }) => apiGet<Snapshot[]>(`${base}/snapshots`, { signal }),
  });
  const artifacts = useQuery({
    queryKey: ["requirement-render-artifacts", projectId, requirementId],
    enabled: canExport,
    queryFn: ({ signal }) => apiGet<RenderArtifact[]>(`${base}/render-artifacts`, { signal }),
  });
  const registered = useQuery({
    queryKey: ["customer-templates", projectId],
    enabled: canExport,
    queryFn: ({ signal }) => apiGet<{ items: RegisteredTemplate[] }>(`/projects/${projectId}/customer-templates`, { signal }),
  });

  function buildForm(): FormData | null {
    const registeredId = templateId.trim();
    if (!registeredId && !templateFile) {
      setMessage("请选择已注册模板，或直接选择客户的 DOCX / XLSX 模板文件。");
      return null;
    }
    const trimmed = sourceId.trim();
    if (!trimmed) {
      setMessage("请填写冻结来源编号：草稿快照 id 或正式交付 id。客户模板导出只接受已冻结内容。");
      return null;
    }
    const form = new FormData();
    if (registeredId) {
      form.append("template_id", registeredId);
    } else if (templateFile) {
      form.append("template", templateFile);
    }
    form.append("format", format);
    // 选定注册模板时忽略手填配置：后端用注册时固定的配置，避免两处配置打架。
    if (!registeredId && config.trim()) form.append("config", config);
    form.append(sourceKind === "draft_snapshot" ? "snapshot_id" : "delivery_id", trimmed);
    return form;
  }

  async function check() {
    if (locked.current || !canExport) return;
    const form = buildForm();
    if (!form) return;
    locked.current = true;
    setBusy(true);
    setMessage("");
    setChecked(null);
    try {
      const result = await uploadForm<CheckResult>(`${base}/template-exports/check`, form);
      setChecked(result);
      setMessage("模板已按冻结内容渲染一次并保存为产物；以下是身份与诊断信息。");
      await artifacts.refetch();
    } catch (error) {
      const detail = (error as { message?: string })?.message;
      setMessage(detail || "模板校验失败。请检查模板锚点、适配配置与冻结来源。");
    } finally {
      locked.current = false;
      setBusy(false);
    }
  }

  async function exportFile() {
    if (locked.current || !canExport) return;
    const form = buildForm();
    if (!form) return;
    locked.current = true;
    setBusy(true);
    setMessage("");
    try {
      const file = await uploadFormDownload(`${base}/template-exports`, form);
      download(file.blob, file.fileName);
      setMessage("已下载按客户模板渲染的文件。相同冻结内容与模板重复导出会复用同一产物。");
      await artifacts.refetch();
    } catch (error) {
      const detail = (error as { message?: string })?.message;
      setMessage(detail || "导出失败。请确认模板适配配置与权限后重试。");
    } finally {
      locked.current = false;
      setBusy(false);
    }
  }

  async function exportBuiltin() {
    if (locked.current || !canExport) return;
    const trimmed = sourceId.trim();
    if (!trimmed) {
      setMessage("请填写冻结来源编号：草稿快照 id 或正式交付 id。平台只用已冻结内容导出。");
      return;
    }
    if (layout === "survey" && format !== "xlsx") {
      setMessage("一表通调研表式只支持 xlsx；需要 Word 请切换到标准版式。");
      return;
    }
    locked.current = true;
    setBusy(true);
    setMessage("");
    try {
      const form = new FormData();
      form.append("format", format);
      form.append("layout", layout);
      form.append("source_kind", sourceKind);
      form.append("source_id", trimmed);
      const file = await uploadFormDownload(`${base}/exports`, form);
      download(file.blob, file.fileName);
      setMessage(layout === "survey"
        ? "已按一表通调研表式导出（表级信息 + 按来源系统重复的业务口径/溯源列组）。与其它导出共用同一套产物身份，重复导出复用同一文件。"
        : "已用平台内置版式导出（未套客户模板）。与客户模板共用同一套产物身份，重复导出复用同一文件。");
      await artifacts.refetch();
    } catch (error) {
      const detail = (error as { message?: string })?.message;
      setMessage(detail || "内置版式导出失败。请确认冻结来源与权限后重试。");
    } finally {
      locked.current = false;
      setBusy(false);
    }
  }

  async function registerTemplate() {
    if (locked.current || !canExport) return;
    if (!templateFile) {
      setMessage("请先选择要注册的模板文件。");
      return;
    }
    if (!registryName.trim()) {
      setMessage("请填写模板名称；同名再注册会形成新版本，内容与配置都相同则复用旧版本。");
      return;
    }
    locked.current = true;
    setBusy(true);
    setMessage("");
    try {
      const form = new FormData();
      form.append("name", registryName.trim());
      form.append("format", format);
      form.append("template", templateFile);
      if (config.trim()) form.append("config", config);
      const result = await uploadForm<{ created: boolean; template: RegisteredTemplate }>(
        `/projects/${projectId}/customer-templates`, form);
      setTemplateId(String(result.template.id));
      setMessage(result.created
        ? `已注册模板「${result.template.name}」v${result.template.version_no}；之后导出可直接按模板 id 复用，无需再上传文件。`
        : `该模板文件与配置已注册过（v${result.template.version_no}），直接复用，未产生重复版本。`);
      await registered.refetch();
      await artifacts.refetch();
    } catch (error) {
      const detail = (error as { message?: string })?.message;
      setMessage(detail || "注册模板失败。请检查模板锚点与适配配置是否匹配。");
    } finally {
      locked.current = false;
      setBusy(false);
    }
  }

  async function downloadArtifact(item: Pick<RenderArtifact, "id">) {
    if (locked.current || !canExport) return;
    locked.current = true;
    setBusy(true);
    setMessage("");
    try {
      const file = await apiDownload(`${base}/render-artifacts/${item.id}/download`);
      download(file.blob, file.fileName);
    } catch (error) {
      const detail = (error as { message?: string })?.message;
      setMessage(detail || "下载失败。产物文件可能已被替换或丢失，平台不会重新渲染。");
    } finally {
      locked.current = false;
      setBusy(false);
    }
  }

  // 评审者应先看到最新产物：列表按产物号倒序，旧版本仍在库里可下载，但不抢占视线。
  const orderedArtifacts = [...(artifacts.data ?? [])].sort((left, right) => right.id - left.id);

  const [checklist, setChecklist] = useState<DeliveryChecklist | null>(null);
  const [checklistBusy, setChecklistBusy] = useState(false);
  // 检查结论要能留痕：审计问"交付前查过吗、当时过没过"，光有实时计算回答不了。
  const [checkHistory, setCheckHistory] = useState<DeliveryCheckHistory | null>(null);
  const [checkArtifactFilter, setCheckArtifactFilter] = useState<number | null>(null);
  const [checkHistoryBusy, setCheckHistoryBusy] = useState(false);
  const [checkNotice, setCheckNotice] = useState("");

  async function loadCheckHistory(artifactId: number | null = checkArtifactFilter) {
    setCheckHistoryBusy(true);
    try {
      const suffix = artifactId ? `&artifact_id=${artifactId}` : "";
      setCheckHistory(await apiGet<DeliveryCheckHistory>(`${base}/delivery-checks?limit=10${suffix}`));
    } catch {
      setCheckHistory(null);
    } finally {
      setCheckHistoryBusy(false);
    }
  }

  /** 把当前（可能已按产物筛选的）检查记录导出成 CSV，供审计留档。 */
  function downloadCheckHistoryCsv() {
    const items = checkHistory?.items ?? [];
    if (!items.length) return;
    const header = ["记录号", "产物号", "检查结论", "阻断项", "检查清单版本", "记录人", "记录时间"];
    const escape = (value: unknown) => {
      const text = value === null || value === undefined ? "" : String(value);
      const guarded = /^[=+\-@]/.test(text) ? `'${text}` : text;
      return `"${guarded.replace(/"/g, '""')}"`;
    };
    const rows = items.map((record) => [
      record.id,
      record.artifact_id,
      record.verdict === "pass" ? "通过" : "未通过",
      record.blocking_keys.join("、"),
      record.checklist_version,
      record.created_by ?? "未知",
      record.created_at ? record.created_at.replace("T", " ").slice(0, 19) : "时间未知",
    ]);
    const csv = [header, ...rows].map((row) => row.map(escape).join(",")).join("\r\n");
    const blob = new Blob(["\ufeff" + csv + "\r\n"], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    // 文件名要跟着**筛选**走：名字写当前打开的产物号、内容却是别的产物，审计会拿错文件。
    link.download = `交付检查记录-${checkArtifactFilter ? `产物${checkArtifactFilter}` : "全部"}-${items.length}条.csv`;
    link.click();
    URL.revokeObjectURL(url);
  }

  async function recordCheck() {
    if (!checklist) return;
    setChecklistBusy(true);
    setCheckNotice("");
    try {
      const body = await apiPost<{ record: DeliveryCheckRecord }>(
        `${base}/render-artifacts/${checklist.artifact.id}/delivery-checks`,
        {},
      );
      setCheckNotice(
        `已记录本次检查：记录 #${body.record.id}（${body.record.verdict === "pass" ? "通过" : "未通过"}）。这份记录只会被追加，不会被覆盖。`,
      );
      await loadCheckHistory();
    } catch (reason) {
      setMessage((reason as { detail?: string })?.detail || "记录检查结果失败：可能需要 project.view 权限，或该产物已被清理。");
    } finally {
      setChecklistBusy(false);
    }
  }

  async function openChecklist(item: RenderArtifact) {
    // 交付前检查单：一次给出字节完整性、身份可回查、结构契约、字段齐备四项结论，
    // 全部读已落库字节与冻结内容，不重渲染、不改任何内容。
    setChecklistBusy(true);
    setChecklist(null);
    try {
      const body = await apiGet<DeliveryChecklist>(`${base}/render-artifacts/${item.id}/delivery-checklist`);
      setChecklist(body);
      await loadCheckHistory();
    } catch (reason) {
      const error = reason as { message?: string; detail?: unknown };
      const detail = typeof error?.detail === "string" ? error.detail : error?.message;
      setMessage(detail || "交付检查单读取失败：产物可能已被清理，或完整性校验未通过。");
    } finally {
      setChecklistBusy(false);
    }
  }

  async function openFidelity(item: RenderArtifact) {
    // 模板一致性：逐字段比对这份文件里的模板列与当前标准模板。
    // 与结构自检不同，这里看的是"值对不对"——监管原始口径、报表名称被改过就要能查出来。
    setFidelityBusy(true);
    setFidelity(null);
    try {
      const body = await apiGet<FidelityPayload>(`${base}/render-artifacts/${item.id}/template-fidelity`);
      setFidelity(body);
      setMessage(
        `模板一致性：产物 #${item.id} ${body.verdict === "pass" ? "与标准模板一致" : `与模板不一致（${body.failed_labels.join("、")}）`}`,
      );
    } catch (reason) {
      const error = reason as { message?: string; detail?: unknown };
      const detail = typeof error?.detail === "string" ? error.detail : error?.message;
      setMessage(detail || "模板一致性比对失败：产物可能已被清理，或不是一表通调研表式。");
    } finally {
      setFidelityBusy(false);
    }
  }

  async function openStructureCheck(item: RenderArtifact) {
    // 只读自检：读的是已落库产物字节，和后端下载返回同一份文件，不会重渲染或改内容
    setStructureBusy(true);
    setPreview(null);
    try {
      const body = await apiGet<StructureCheckPayload>(`${base}/render-artifacts/${item.id}/structure-check`);
      setStructureCheck(body);
      setMessage(`结构自检：产物 #${item.id} ${body.verdict === "pass" ? "通过" : "未通过"}（${body.summary.blocking_failed}/${body.summary.blocking_total} 项阻断检查失败）`);
    } catch (reason) {
      // ApiError.message 是给人看的通用文案（如"输入数据不完整或格式不正确"），
      // 具体拒绝原因在 detail 里；结构自检的拒绝理由（例如"不是平台内置版式"）必须原样呈现，
      // 否则用户只会看到"格式不正确"，无法判断该换版式还是该修文件。
      const error = reason as { message?: string; detail?: unknown };
      const detail = typeof error?.detail === "string" ? error.detail : error?.message;
      setMessage(detail || "结构自检失败：产物可能已被清理，或不是当前格式对应的版式（一表通调研表式 xlsx / 内置版式 docx）。");
    } finally {
      setStructureBusy(false);
    }
  }

  async function openPreview(item: RenderArtifact) {
    if (!canExport) return;
    setPreviewBusy(true);
    setMessage("");
    try {
      const body = await apiGet<PreviewPayload>(`${base}/render-artifacts/${item.id}/preview`);
      setPreviewSheetIndex(0);
    setPreviewQuery("");
      setPreview(body);
    } catch (error) {
      const detail = (error as { message?: string })?.message;
      setMessage(detail || "预览失败。产物文件可能已被替换或丢失，平台不会重新渲染。");
    } finally {
      setPreviewBusy(false);
    }
  }

  return <section className="panel mb-3 p-4" aria-label="客户模板导出">
    <h2 className="text-sm font-semibold">按客户模板导出</h2>
    <p className="my-2 text-xs text-slate-500">
      用客户自己的 DOCX / XLSX 版式渲染<strong>已冻结</strong>的内容。未提供冻结来源时平台拒绝导出；必需锚点缺失会直接失败，不会产出残缺文件。不套模板时可用「内置版式导出」——两条路径共用同一套产物身份与文件 hash。
    </p>
    {access.isPending ? <p role="status" className="text-xs">正在核验导出权限…</p> : null}
    {!canExport && access.isSuccess ? <p className="mt-2 text-xs">当前角色没有导出权限（deliverable.export）。</p> : null}
    {canExport ? <div className="mt-3 space-y-2">
      <div className="flex flex-wrap items-center gap-3 text-xs">
        <label className="flex items-center gap-1">格式
          <select className="rounded border p-1" value={format} onChange={(event) => setFormat(event.target.value === "xlsx" ? "xlsx" : "docx")}>
            <option value="docx">Word (.docx)</option>
            <option value="xlsx">Excel (.xlsx)</option>
          </select>
        </label>
        <label className="flex items-center gap-1">内置版式
          <select aria-label="内置导出布局" className="rounded border p-1" value={layout} onChange={(event) => setLayout(event.target.value === "survey" ? "survey" : "standard")}>
            <option value="standard">标准版式（整份需求）</option>
            <option value="survey">一表通调研表式（仅 xlsx）</option>
          </select>
        </label>
        <label className="flex items-center gap-1">冻结来源
          <select className="rounded border p-1" value={sourceKind} onChange={(event) => setSourceKind(event.target.value === "formal_delivery" ? "formal_delivery" : "draft_snapshot")}>
            <option value="draft_snapshot">草稿快照</option>
            <option value="formal_delivery">正式交付</option>
          </select>
        </label>
        <label className="flex items-center gap-1">编号
          <input className="w-24 rounded border p-1" inputMode="numeric" value={sourceId} onChange={(event) => setSourceId(event.target.value)} placeholder="必填" />
        </label>
        {sourceKind === "draft_snapshot" && snapshots.data?.length ? <span className="text-slate-500">可用快照：{snapshots.data.map((item) => `#${item.id}（v${item.requirement_version}）`).join("、")}</span> : null}
      </div>
      <label className="block text-xs">已注册模板（可选，选定后无需再上传文件）
        <select aria-label="已注册客户模板" className="mt-1 w-full rounded border p-1 text-xs" value={templateId} onChange={(event) => setTemplateId(event.target.value)}>
          <option value="">不使用已注册模板</option>
          {(registered.data?.items || []).map((item) => <option key={item.id} value={String(item.id)}>
            {`#${item.id} ${item.name} v${item.version_no}（${item.format}，模板 ${item.file_sha256.slice(0, 10)}…）${item.supported_scope?.supported === false ? " · 当前不满足必需锚点" : ""}`}
          </option>)}
        </select>
      </label>
      <label className="block text-xs">客户模板文件{templateId ? "（已选注册模板，上传将被拒绝）" : ""}
        <input type="file" accept={format === "xlsx" ? ".xlsx" : ".docx"} disabled={Boolean(templateId)} className="mt-1 block text-xs" onChange={(event) => setTemplateFile(event.target.files?.[0] || null)} />
      </label>
      <div className="flex flex-wrap items-end gap-2 text-xs">
        <label className="flex-1">注册为新模板版本（名称）
          <input aria-label="模板注册名称" className="mt-1 w-full rounded border p-1" value={registryName} onChange={(event) => setRegistryName(event.target.value)} placeholder="例如：XX 银行需求文档模板" />
        </label>
        <button className="button-secondary" disabled={busy || Boolean(templateId)} onClick={() => void registerTemplate()}>注册当前模板文件</button>
      </div>
      <label className="block text-xs">适配配置（可选，JSON；锚点/命名单元格/样板行）{templateId ? " —— 已选注册模板，此处配置不会发送" : ""}
        <textarea aria-label="模板适配配置" className="mt-1 h-20 w-full rounded border p-2 font-mono text-xs" value={config} onChange={(event) => setConfig(event.target.value)} placeholder={'{\n  "config_version": "customer-1",\n  "template_sha256": "…",\n  "anchors": {"cover.title": "…"}\n}'} />
      </label>
      <div className="flex flex-wrap gap-2">
        <button className="button-secondary" disabled={busy} onClick={() => void check()}>{busy ? "处理中…" : "校验模板并预渲染"}</button>
        <button className="button-secondary" disabled={busy} onClick={() => void exportFile()}>渲染并下载</button>
        <button className="button-secondary" disabled={busy} onClick={() => void exportBuiltin()}>内置版式导出（不套模板）</button>
      </div>
      {checked ? <div className="rounded border bg-slate-50 p-2 text-xs">
        <p className="font-medium">{checked.file_name} · {Math.round(checked.file_size / 1024)} KB · 产物 #{checked.artifact_id}</p>
        <p className="mt-1 text-slate-600">文件 sha256 {checked.file_sha256.slice(0, 16)}… · 模板 sha256 {checked.template_sha256.slice(0, 16)}…</p>
        <p className="mt-1 text-slate-600">渲染器 {checked.renderer_version} · 配置版本 {checked.config_version || "未标注"}</p>
        {checked.warnings.length ? <p className="mt-1 text-amber-700">警告：{checked.warnings.join("；")}</p> : null}
      </div> : null}
    </div> : null}
    {canExport ? <div className="mt-4 border-t pt-3">
      <h3 className="text-xs font-semibold">已冻结导出产物</h3>
      <p className="mt-1 text-xs text-slate-500">同一冻结内容与模板只渲染一次；模板换了会生成新产物，旧文件保留可追溯。</p>
      {artifacts.isError ? <p role="alert" className="mt-2 text-xs">无法读取产物记录。<button onClick={() => void artifacts.refetch()}>重试</button></p>
        : artifacts.isPending ? <p role="status" className="mt-2 text-xs">正在读取产物…</p>
        : <ul className="mt-2 max-h-56 space-y-2 overflow-auto text-xs">{artifacts.data?.length ? orderedArtifacts.map((item) => <li key={item.id} className="flex flex-wrap items-center justify-between gap-2 border-t pt-2">
          <span>
            #{item.id} · {item.format} · {item.file_name} · {Math.round(item.file_size / 1024)} KB · {item.source_kind} #{item.source_id}
            <span className="ml-2 text-slate-500">文件 {item.file_sha256.slice(0, 12)}… · 模板 {(item.template_sha256 || "无").slice(0, 12)}… · {item.created_at ? new Date(item.created_at).toLocaleString("zh-CN") : "时间未知"}</span>
          </span>
          <span className="flex items-center gap-3">
            {(item.format === "xlsx" || item.format === "docx") ? <button className="text-sky-700 underline" disabled={busy || previewBusy} onClick={() => void openPreview(item)}>在页面预览</button> : null}
            {item.format === "xlsx" || item.format === "docx" ? <button className="text-indigo-700 underline" disabled={busy || structureBusy} onClick={() => void openStructureCheck(item)}>结构自检</button> : null}
                    {item.format === "xlsx" ? <button className="text-teal-700 underline" disabled={busy || fidelityBusy} onClick={() => void openFidelity(item)} aria-label={`查看模板一致性 ${item.file_name}`}>模板一致性</button> : null}
            <button className="text-rose-700 underline" disabled={busy || checklistBusy} onClick={() => void openChecklist(item)} aria-label={`查看交付检查单 ${item.file_name}`}>交付检查单</button>
            <button className="text-emerald-700 underline" disabled={busy} onClick={() => void downloadArtifact(item)}>下载</button>
          </span>
        </li>) : <li>尚未生成按客户模板的导出产物。</li>}</ul>}
    </div> : null}
    {structureCheck ? <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4" onClick={() => setStructureCheck(null)}>
      <div role="dialog" aria-label="结构自检" className="flex max-h-[85vh] w-full max-w-3xl flex-col rounded-lg bg-white p-4 shadow-xl" onClick={(event) => event.stopPropagation()}>
        <div className="flex items-start justify-between gap-3 border-b pb-2">
          <div>
            <p className="text-sm font-semibold">结构自检 · 产物 #{structureCheck.artifact.id}</p>
            <p className="mt-1 text-slate-600">{structureCheck.artifact.file_name} · 文件 sha256 {structureCheck.artifact.file_sha256.slice(0, 16)}… · 渲染器 {structureCheck.artifact.renderer_version}</p>
            <p className="mt-1 text-slate-500">只读自检：只按标准模板结构判断这份文件，不重渲染、不修改任何内容，也不代表业务口径已被业务确认。</p>
            {structureCheck.upgrade_hint ? <p className="mt-1 text-amber-700" aria-label="版本提示">{structureCheck.upgrade_hint}</p> : null}
            {structureCheck.contract ? <p className="mt-1 text-slate-600" aria-label="结构契约">按渲染时结构判定：{structureCheck.contract.label}（契约 {structureCheck.contract.version}，渲染器 {structureCheck.contract.renderer_version || structureCheck.artifact.renderer_version}）{structureCheck.skipped_keys?.length ? `；本次不参与阻断判定：${structureCheck.skipped_keys.join("、")}` : ""}</p> : null}
          </div>
          <button className="button-secondary" onClick={() => setStructureCheck(null)}>关闭</button>
        </div>
        <p className={structureCheck.verdict === "pass" ? "mt-3 text-sm font-semibold text-emerald-700" : "mt-3 text-sm font-semibold text-rose-700"}>
          {structureCheck.verdict === "pass" ? "结构自检通过" : "结构自检未通过"}：{structureCheck.summary.blocking_failed} / {structureCheck.summary.blocking_total} 项阻断检查失败
        </p>
        <p className="mt-1 text-xs text-slate-600">
          {structureCheck.artifact.format === "docx"
            ? `章节 ${structureCheck.section_titles?.length ?? 0} 个（${structureCheck.section_titles?.join("、") || "无"}） · 字段块 ${structureCheck.field_section_count ?? 0} 个`
            : `工作表「${structureCheck.sheet_name}」${structureCheck.row_count} 行 × ${structureCheck.column_count} 列 · 数据项 ${structureCheck.field_rows} 行 · 来源系统分组 ${structureCheck.groups?.join("、") || "无"} · 占位单元格 ${structureCheck.placeholder_cells} 个`}
        </p>
        <div className="mt-3 flex-1 overflow-auto">
          <table className="w-full border-collapse text-[11px]">
            <thead><tr className="bg-slate-100"><th className="border px-2 py-1 text-left">检查项</th><th className="border px-2 py-1 text-left">结果</th><th className="border px-2 py-1 text-left">说明</th></tr></thead>
            <tbody>{structureCheck.checks.map((item) => <tr key={item.key} className={item.ok ? "" : "bg-rose-50"}>
              <td className="border px-2 py-1">{item.label}{item.severity === "info" ? "（信息项）" : ""}</td>
              <td className={item.ok ? "border px-2 py-1 text-emerald-700" : "border px-2 py-1 text-rose-700"}>{item.ok ? "通过" : "未通过"}</td>
              <td className="border px-2 py-1 text-slate-600">{item.detail}</td>
            </tr>)}</tbody>
          </table>
        </div>
      </div>
    </div> : null}
    {fidelity ? <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4" onClick={() => setFidelity(null)}>
      <div role="dialog" aria-label="模板一致性" className="flex max-h-[85vh] w-full max-w-3xl flex-col rounded-lg bg-white p-4 shadow-xl" onClick={(event) => event.stopPropagation()}>
        <div className="flex items-start justify-between gap-3 border-b pb-2">
          <div>
            <p className="text-sm font-semibold">模板一致性 · 产物 #{fidelity.artifact.id}</p>
            <p className="mt-1 text-slate-600">{fidelity.artifact.file_name} · 工作表「{fidelity.sheet_name}」· {fidelity.field_count} 个数据项 · 文件 sha256 {fidelity.artifact.file_sha256.slice(0, 16)}…</p>
            <p className="mt-1 text-slate-500">{fidelity.note}</p>
          </div>
          <button className="button-secondary" onClick={() => setFidelity(null)}>关闭</button>
        </div>
        <p className={fidelity.verdict === "pass" ? "mt-3 text-sm font-semibold text-emerald-700" : "mt-3 text-sm font-semibold text-rose-700"}>
          {fidelity.verdict === "pass" ? "与标准模板一致" : `与标准模板不一致：${fidelity.failed_labels.join("、")}`}
        </p>
        <div className="mt-3 min-h-0 flex-1 overflow-auto">
          <table className="w-full text-xs">
            <thead><tr className="bg-slate-100 text-left"><th className="border px-2 py-1">模板列</th><th className="border px-2 py-1">可比字段</th><th className="border px-2 py-1">一致</th><th className="border px-2 py-1">不一致</th><th className="border px-2 py-1">文档为空</th><th className="border px-2 py-1">模板未给值</th></tr></thead>
            <tbody>{fidelity.columns.map((column) => (
              <tr key={column.key} className={column.mismatched_count || column.blank_in_document_count ? "bg-rose-50" : ""}>
                <td className="border px-2 py-1">{column.label}</td>
                <td className="border px-2 py-1">{column.checked_count}</td>
                <td className="border px-2 py-1 text-emerald-700">{column.matched_count}</td>
                <td className={column.mismatched_count ? "border px-2 py-1 text-rose-700" : "border px-2 py-1"}>{column.mismatched_count}</td>
                <td className={column.blank_in_document_count ? "border px-2 py-1 text-rose-700" : "border px-2 py-1"}>{column.blank_in_document_count}</td>
                <td className="border px-2 py-1 text-slate-500">{column.template_empty_count}</td>
              </tr>))}</tbody>
          </table>
          {fidelity.columns.some((column) => column.samples.length) ? <div className="mt-3">
            <p className="text-xs font-medium">不一致明细（最多各列 5 条）</p>
            <ul className="mt-1 space-y-1 text-xs text-slate-700">{fidelity.columns.flatMap((column) => column.samples.map((sample) => (
              <li key={`${column.key}-${sample.field_code}`}>· {column.label} · {sample.field_code}：模板「{sample.expected || "（空）"}」／文档「{sample.actual || "（空）"}」</li>
            )))}</ul>
          </div> : null}
          {fidelity.unexpected_values.length ? <p className="mt-3 text-xs text-amber-700">模板未给值但文档写了内容（需求侧补充，非模板事实）：{fidelity.unexpected_values.slice(0, 5).map((item) => `${item.label}/${item.field_code}`).join("、")}</p> : null}
          <p className="mt-3 text-[11px] text-slate-500">比对只读：不修改文件、不修改需求。模板更新后要看新值需重新生成并重新冻结。</p>
        </div>
      </div>
    </div> : null}
    {checklist ? <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4" onClick={() => setChecklist(null)}>
      <div role="dialog" aria-label="交付检查单" className="flex max-h-[85vh] w-full max-w-2xl flex-col rounded-lg bg-white p-4 shadow-xl" onClick={(event) => event.stopPropagation()}>
        <div className="flex items-start justify-between gap-3 border-b pb-2">
          <div>
            <p className="text-sm font-semibold">交付前检查单 · 产物 #{checklist.artifact.id}</p>
            <p className="mt-1 text-slate-600">{checklist.artifact.file_name} · {Math.round(checklist.artifact.file_size / 1024)} KB · 文件 sha256 {checklist.artifact.file_sha256.slice(0, 16)}… · 渲染器 {checklist.artifact.renderer_version}</p>
            <p className="mt-1 text-slate-500">{checklist.note}</p>
          </div>
          <button className="button-secondary" onClick={() => setChecklist(null)}>关闭</button>
        </div>
        <p className={checklist.verdict === "pass" ? "mt-3 text-sm font-semibold text-emerald-700" : "mt-3 text-sm font-semibold text-rose-700"}>
          {checklist.verdict === "pass" ? "交付检查单通过" : "交付检查单未通过"}：{checklist.summary.blocking_failed} / {checklist.summary.blocking_total} 项阻断检查失败
        </p>
        {checklist.summary.preview_truncated ? <p className="mt-1 text-xs text-amber-700" aria-label="预览截断提示">预览内容被截断：字段齐备性检查只覆盖可见部分，缺失字段按信息项提示，不当作阻断。</p> : null}
        <p className="mt-1 text-xs text-slate-500">检查清单版本 {checklist.checklist_version}；四项检查都读已落库文件与冻结内容，通过只代表这份文件与冻结内容自洽，不代表业务口径已被业务确认。</p>
        <div className="mt-3 rounded border border-line p-3" aria-label="交付检查记录">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs font-medium">检查记录</span>
            <button className="button-secondary" disabled={checklistBusy} onClick={() => void recordCheck()} type="button" aria-label="记录本次交付检查">记录本次检查结果</button>
            <button className="text-xs text-slate-600 underline" disabled={checkHistoryBusy} onClick={() => void loadCheckHistory()} type="button">刷新记录</button>
            <select
              aria-label="按产物筛选检查记录"
              className="control w-52 text-xs"
              value={checkArtifactFilter ?? ""}
              onChange={(event) => {
                const next = event.target.value ? Number(event.target.value) : null;
                setCheckArtifactFilter(next);
                void loadCheckHistory(next);
              }}
            >
              <option value="">全部产物</option>
              {(artifacts.data ?? []).map((item) => (
                <option key={item.id} value={item.id}>产物 #{item.id} · {item.file_name}</option>
              ))}
            </select>
            <button
              className="text-xs text-slate-600 underline"
              disabled={!checkHistory?.items.length}
              onClick={downloadCheckHistoryCsv}
              type="button"
              aria-label="导出检查记录 CSV"
            >导出 CSV</button>
            <span className="text-[11px] text-slate-500">记录是追加的，用来回答"交付前查过没、当时过没过"。</span>
          </div>
          {checkNotice ? <p className="mt-2 text-xs text-emerald-700" aria-label="检查记录结果">{checkNotice}</p> : null}
          {checkHistory && checkHistory.items.length ? <ul className="mt-2 space-y-1 text-[11px] text-slate-600">{checkHistory.items.map((record) => <li key={record.id}>
            记录 #{record.id} · 产物 #{record.artifact_id} · {record.verdict === "pass" ? "通过" : "未通过"}{record.blocking_keys.length ? `（阻断：${record.blocking_keys.join("、")}）` : ""} · {record.created_at ? record.created_at.replace("T", " ").slice(0, 19) : "时间未知"}
          </li>)}</ul> : <p className="mt-2 text-[11px] text-slate-500">{checkHistoryBusy ? "正在读取检查记录…" : "这个需求还没有检查记录：点「记录本次检查结果」留痕。"}</p>}
        </div>
        <div className="mt-3 flex-1 overflow-auto">
          <table className="w-full border-collapse text-[11px]">
            <thead><tr className="bg-slate-100"><th className="border px-2 py-1 text-left">检查项</th><th className="border px-2 py-1 text-left">结果</th><th className="border px-2 py-1 text-left">说明</th></tr></thead>
            <tbody>{checklist.checks.map((item) => <tr key={item.key} className={item.ok ? "" : "bg-rose-50"}>
              <td className="border px-2 py-1">{item.label}{item.severity === "info" ? "（信息项）" : ""}</td>
              <td className={item.ok ? "border px-2 py-1 text-emerald-700" : "border px-2 py-1 text-rose-700"}>{item.ok ? "通过" : "未通过"}</td>
              <td className="border px-2 py-1 text-slate-600">{item.detail}</td>
            </tr>)}</tbody>
          </table>
        </div>
      </div>
    </div> : null}
    {preview ? <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4" onClick={() => setPreview(null)}>
      <div role="dialog" aria-label="产物预览" className="flex max-h-[90vh] w-full max-w-[95vw] flex-col rounded-lg bg-white shadow-xl" onClick={(event) => event.stopPropagation()}>
        <div className="flex flex-wrap items-start justify-between gap-2 border-b p-3">
          <div className="text-xs">
            <p className="text-sm font-semibold">{preview.artifact.file_name} · 产物 #{preview.artifact.id}</p>
            <p className="mt-1 text-slate-600">文件 sha256 {preview.artifact.file_sha256.slice(0, 16)}… · 模板 {(preview.artifact.template_sha256 || "无").slice(0, 12)}… · 渲染器 {preview.artifact.renderer_version}</p>
            <p className="mt-1 text-slate-500">{preview.note}</p>
          </div>
          <div className="flex items-center gap-2">
            <button className="button-secondary" disabled={busy} onClick={() => void downloadArtifact(preview.artifact)}>下载原文件</button>
            <button className="button-secondary" onClick={() => setPreview(null)}>关闭预览</button>
          </div>
        </div>
        {preview.sheet_count > 1 ? <div className="flex flex-wrap gap-1 border-b p-2 text-xs">{preview.sheets.map((sheet, index) =>
          <button key={sheet.name} className={index === previewSheetIndex ? "rounded bg-slate-900 px-2 py-1 text-white" : "rounded border px-2 py-1"}
            onClick={() => setPreviewSheetIndex(index)}>{sheet.name}</button>)}</div> : null}
        <div className="flex flex-wrap items-center gap-2 border-b p-2 text-xs">
          <input
            aria-label="在产物里查找"
            className="control w-64"
            placeholder="字段编码或名称，如 H010001"
            value={previewQuery}
            onChange={(event) => setPreviewQuery(event.target.value)}
          />
          {previewNeedle ? (
            <span className={previewHitCount ? "text-emerald-700" : "text-amber-700"}>
              {previewHitCount
                ? `命中 ${previewHitCount} ${preview.format === "docx" ? "个章节" : `行（工作表「${hitSheetName}」）`}（已滚到第一处${otherHitSheets > 0 ? `，另外 ${otherHitSheets} 个工作表也有命中` : ""}）`
                : `没有找到「${previewQuery.trim()}」：${preview.format === "docx" ? "这份文件里没有这段文字（也可能被预览截断）" : "所有工作表里都没有这段文字（也可能被预览截断，只显示了前若干行/列）"}`}
            </span>
          ) : (
            <span className="text-slate-500">只在当前这份产物里查找，不跨文件、不重新渲染</span>
          )}
        </div>
        <div className="flex-1 overflow-auto p-3">
          {preview.format === "docx" ? <div className="space-y-3">
            <p className="text-xs text-slate-600">Word 结构：{preview.section_count ?? 0} 个章节 · 段落与表格按顺序列出
              {preview.max_chars ? ` · 单个段落最多显示 ${preview.max_chars} 字符` : ""}
              {preview.max_table_rows ? ` · 每个表格最多显示 ${preview.max_table_rows} 行` : ""}
              {preview.truncated_blocks ? ` · ${preview.truncated_blocks} 处内容被截断` : ""}</p>
            {(preview.sections ?? []).map((section, index) => <div
              key={`${section.title}-${index}`}
              data-preview-hit={docxHitSections.includes(index) ? (index === firstDocxHit ? "first" : "true") : undefined}
              className={`space-y-1 rounded border p-2${docxHitSections.includes(index) ? " border-amber-400 bg-amber-50/60" : ""}`}
            >
              <p className="text-xs font-semibold">§{index + 1} {section.title} <span className="font-normal text-slate-500">（{section.style || "正文"} · {section.chars} 字符）</span></p>
              {section.paragraphs.length === 0 && section.tables.length === 0 ? <p className="text-xs text-slate-500">这一章节没有可见内容。</p> : null}
              {section.paragraphs.map((paragraph, paragraphIndex) => <p key={`p-${paragraphIndex}`} className="whitespace-pre-wrap break-words text-[11px] text-slate-700">
                {paragraph.text}{paragraph.truncated ? <span className="ml-1 text-amber-700">…</span> : null}
              </p>)}
              {section.tables.map((table, tableIndex) => <div key={`t-${tableIndex}`} className="overflow-auto">
                <p className="text-[11px] text-slate-500">表格 {table.rows} 行 × {table.columns} 列{table.truncated ? ` · 仅显示前 ${table.sample_rows.length} 行` : ""}</p>
                <table className="border-collapse text-[11px]">
                  <tbody>
                    {table.header.length ? <tr className="bg-slate-100 font-medium">{table.header.map((cell, cellIndex) => <th key={`h-${cellIndex}`} className="max-w-[200px] break-words border px-1 py-0.5 text-left">{cell}</th>)}</tr> : null}
                    {table.sample_rows.map((row, rowIndex) => <tr key={`r-${rowIndex}`}>{row.map((cell, cellIndex) => <td key={`c-${cellIndex}`} className="max-w-[220px] whitespace-pre-wrap break-words border px-1 py-0.5 align-top">{cell}</td>)}</tr>)}
                  </tbody>
                </table>
              </div>)}
            </div>)}
          </div> : (() => {
            const sheet = preview.sheets[Math.min(previewSheetIndex, preview.sheets.length - 1)];
            if (!sheet) return <p className="text-xs">产物没有可预览的工作表。</p>;
            return <div className="space-y-2">
              <p className="text-xs text-slate-600">工作表 {sheet.name}：{sheet.total_rows} 行 × {sheet.total_columns} 列 · 合并区 {sheet.merged.length} 处{sheet.freeze_panes ? ` · 冻结 ${sheet.freeze_panes}` : ""}
                {sheet.truncated ? ` · 仅显示前 ${preview.max_rows} 行 / ${preview.max_columns} 列` : ""}
                {sheet.truncated_cells ? ` · ${sheet.truncated_cells} 个单元格内容被截断` : ""}
                {sheet.formulas_without_cache ? ` · ${sheet.formulas_without_cache} 个公式没有缓存值，显示为公式原文` : ""}</p>
              <table className="border-collapse text-[11px]">
                <tbody>{sheet.rows.map((row, rowIndex) => <tr key={rowIndex}
                  data-preview-hit={sheetHitRows.includes(rowIndex) ? (rowIndex === firstSheetHit ? "first" : "true") : undefined}
                  className={`${rowIndex === 0 ? "bg-slate-100 font-medium" : ""}${sheetHitRows.includes(rowIndex) ? " bg-amber-50" : ""}`}>
                  <td className="border px-1 py-0.5 text-slate-400">{rowIndex + 1}</td>
                  {row.map((cell, cellIndex) => <td key={cellIndex} className="max-w-[220px] whitespace-pre-wrap break-words border px-1 py-0.5 align-top">{cell ?? ""}</td>)}
                </tr>)}</tbody>
              </table>
            </div>;
          })()}
        </div>
      </div>
    </div> : null}
    {message ? <p role="status" className="mt-2 text-xs">{message}</p> : null}
  </section>;
}

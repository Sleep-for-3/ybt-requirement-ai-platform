"use client";

import { AlertTriangle, CheckCircle2, CircleDashed } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useState, useSyncExternalStore } from "react";

import { WorkspaceHeader } from "@/components/WorkspaceHeader";
import {
  clearAcceptanceNotice,
  describeAcceptanceNotice,
  getAcceptanceNotice,
  getServerAcceptanceNotice,
  noticeForProject,
  publishAcceptanceNotice,
  subscribeAcceptanceNotice,
} from "@/lib/acceptance-notice";
import { apiDownload, apiGet, apiPost, ProjectReadiness, ReadinessDimension, uploadForm, uploadFormDownload } from "@/lib/api";
import {
  ATTESTATION_CONCLUSIONS,
  AUDIT_STATE_BADGE,
  REPLAY_BADGE,
  DELIVERY_AUDIT_FILTERS,
  DeliveryAuditFilter,
  DeliveryAuditItem,
  DeliveryAuditResponse,
  attestationText,
  auditCheckText,
  auditReplayText,
  replayItemText,
  auditFilterCount,
  auditHeadline,
  auditManualPending,
  auditPendingSupported,
  auditState,
  filterAuditItems,
  formatAuditTime,
} from "@/lib/delivery-audit";
import {
  DELIVERY_STATE_BADGE,
  DELIVERY_STATE_LABELS,
  DeliveryStatusItem,
  DeliveryStatusResponse,
  deliveryActionText,
  deliveryArtifactText,
  scriptBindingText,
  scriptBindingUnboundLabel,
  deliveryDetail,
  deliveryAttestationText,
  deliveryHeadline,
  deliveryState,
  formalDeliveryText,
  deliveryReadiness,
  DELIVERY_STATUS_FILTERS,
  DeliveryStatusFilter,
  deliveryFilterCount,
  deliveryFilterHint,
  filterDeliveryItems,
  pendingCandidateText,
  readinessHeadline,
  sortDeliveryItems,
  READINESS_BADGE,
  READINESS_LABELS,
} from "@/lib/delivery-status";
import {
  DECISION_BADGE,
  FRESHNESS_BADGE,
  FRESHNESS_LABELS,
  FRESHNESS_NOTE,
  SCRIPT_BASIS_DECISION_CHOICES,
  decisionText,
  freshnessStateOf,
  freshnessText,
  freshnessVersionText,
  type ScriptBasisDecision,
  type ScriptBasisFreshnessItem,
  type ScriptBasisFreshnessResponse,
  type ScriptBasisVersionFreshness,
} from "@/lib/script-basis-freshness";
import {
  IMPACT_BADGE,
  affectedFieldTexts,
  impactText,
  scriptDiffEntryText,
  scriptDiffText,
  type ScriptBasisDiffResponse,
} from "@/lib/script-basis-diff";
import { gapBreakdownHeadline, gapFieldText, type GapBreakdownResponse } from "@/lib/gap-breakdown";
import {
  TEMPLATE_SOURCE_BADGE,
  TEMPLATE_SOURCE_SHORT,
  TemplateColumnCoverageResponse,
  TemplateGapResponse,
  fillPercent,
  gapSummaryText,
  templateGapCsv,
  templateColumnState,
  templateCoverageHeadline,
} from "@/lib/template-column-coverage";
import {
  COVERAGE_BADGE,
  COVERAGE_FILTERS,
  COVERAGE_LABELS,
  CoverageFilterKey,
  TableCoverageItem,
  TableCoverageResponse,
  coverageDetail,
  coverageFilterCount,
  coverageHeadline,
  filterCoverage,
} from "@/lib/table-coverage";
import { describeError, describeUserMessage } from "@/lib/user-message.mjs";
import {
  WORKLIST_REASON_HINTS,
  DISPATCH_STATUS_OPTIONS,
  dispatchHistoryText,
  dispatchText,
  WORKLIST_REASON_ORDER,
  WorklistItem,
  WorklistReason,
  WorklistResponse,
  filterWorklist,
  worklistCsv,
  worklistFieldText,
  worklistFieldHref,
  GAP_CONSISTENCY_BADGE,
  gapConsistencyText,
  artifactRejectedText,
  worklistRejectedHeadline,
  worklistHeadline,
  worklistReasonCount,
} from "@/lib/requirement-worklist";
import { followupItemText, followupNeedsAttention, followupText } from "@/lib/rejection-followup";
import {
  EXPORT_STABILITY_DISCLAIMER,
  stabilityHeadline,
  stabilityItemText,
  stabilityVerdictText,
  type ExportStabilityPayload,
} from "@/lib/export-stability";
import {
  manifestFilterText,
  manifestHeadline,
  manifestItemText,
  manifestRendererFacetText,
  manifestTableFacetText,
  REPLAY_MANIFEST_DISCLAIMER,
  REPLAY_MANIFEST_STATES,
  REPLAY_MANIFEST_TONE,
  type ReplayManifestItem,
  type ReplayManifestPayload,
  type ReplayManifestState,
} from "@/lib/replay-manifest";
import {
  FIELD_COVERAGE_BUCKETS,
  FIELD_COVERAGE_DISCLAIMER,
  coverageBucketText as fieldCoverageBucketText,
  coverageHeadline as fieldCoverageHeadline,
  coverageOutsideScopeText as fieldCoverageOutsideScopeText,
  coverageRowText as fieldCoverageRowText,
  type FieldCoveragePayload,
} from "@/lib/field-coverage";

const LABELS: Record<string, string> = {
  project_configuration: "项目配置",
  target_field_definition: "目标字段",
  scenario_definition: "产品场景",
  knowledge_base: "知识库",
  datasource_and_catalog: "数据源与目录",
  source_profiling: "源数据剖析",
  business_mapping: "业务映射",
  technical_lineage: "技术血缘",
  double_layer_mapping: "双层映射",
  governance_review: "治理复核",
  sql_lineage: "SQL 血缘",
  change_impact: "变更影响",
  deliverable_template: "交付模板",
  deliverable_package: "交付包",
  open_questions: "待确认问题",
  uat_status: "验收状态",
  deployment_readiness: "部署准备"
};

const STATUS: Record<string, string> = {
  ready: "已就绪",
  partial: "进行中",
  blocked: "被阻断",
  not_started: "未开始"
};

const STATUS_BADGE: Record<string, string> = {
  ready: "badge-success",
  partial: "badge-warning",
  blocked: "badge-danger",
  not_started: "badge-neutral"
};

export default function ReadinessPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const [data, setData] = useState<ProjectReadiness | null>(null);
  const [error, setError] = useState("");
  const [delivery, setDelivery] = useState<DeliveryStatusResponse | null>(null);
  const [deliveryError, setDeliveryError] = useState("");
  const [deliverySort, setDeliverySort] = useState<"priority" | "id">("priority");
  const [deliveryFilter, setDeliveryFilter] = useState<DeliveryStatusFilter>("all");
  const [selected, setSelected] = useState<number[]>([]);
  const [batchBusy, setBatchBusy] = useState(false);
  const [batchError, setBatchError] = useState("");
  const [batchNotice, setBatchNotice] = useState("");
  const [audit, setAudit] = useState<DeliveryAuditResponse | null>(null);
  const [auditError, setAuditError] = useState("");
  const [auditFilter, setAuditFilter] = useState<DeliveryAuditFilter>("all");
  const [auditLimit, setAuditLimit] = useState(12);
  const [coverage, setCoverage] = useState<TableCoverageResponse | null>(null);
  const [coverageError, setCoverageError] = useState("");
  const [coverageFilter, setCoverageFilter] = useState<CoverageFilterKey>("all");
  const [coverageLimit, setCoverageLimit] = useState(15);
  const [templateCoverage, setTemplateCoverage] = useState<TemplateColumnCoverageResponse | null>(null);
  const [templateCoverageError, setTemplateCoverageError] = useState("");
  const [gapColumn, setGapColumn] = useState<string | null>(null);
  const [gapPanel, setGapPanel] = useState<TemplateGapResponse | null>(null);
  const [gapBusy, setGapBusy] = useState(false);
  const [gapError, setGapError] = useState("");
  // 按监管表缩小缺口清单（2422 条缺口里派工时通常只想派某一张表）。
  const [gapFilter, setGapFilter] = useState("");
  const [gapBreakdownFor, setGapBreakdownFor] = useState<DeliveryStatusItem | null>(null);
  const [gapBreakdown, setGapBreakdown] = useState<GapBreakdownResponse | null>(null);
  const [gapBreakdownBusy, setGapBreakdownBusy] = useState(false);
  const [gapBreakdownError, setGapBreakdownError] = useState("");
  const [downloadingId, setDownloadingId] = useState<number | null>(null);
  const [artifactNotice, setArtifactNotice] = useState("");
  const [artifactError, setArtifactError] = useState("");
  const [refreezeBusy, setRefreezeBusy] = useState(false);
  const [refreezeNotice, setRefreezeNotice] = useState("");
  const [refreezeError, setRefreezeError] = useState("");
  const [deliveryReload, setDeliveryReload] = useState(0);
  const [freshness, setFreshness] = useState<ScriptBasisFreshnessResponse | null>(null);
  const [freshnessError, setFreshnessError] = useState("");
  const [freshnessFor, setFreshnessFor] = useState<ScriptBasisFreshnessItem | null>(null);
  const [scriptDiff, setScriptDiff] = useState<ScriptBasisDiffResponse | null>(null);
  const [decisionNotes, setDecisionNotes] = useState<Record<number, string>>({});
  const [decisionBusy, setDecisionBusy] = useState(false);
  const [decisionError, setDecisionError] = useState("");
  // 待办派工清单（只读聚合）：项目负责人按字段派工，不用逐条需求点开数。
  const [worklist, setWorklist] = useState<WorklistResponse | null>(null);
  const [worklistOpen, setWorklistOpen] = useState(false);
  const [worklistBusy, setWorklistBusy] = useState(false);
  const [worklistError, setWorklistError] = useState("");
  const [worklistFilter, setWorklistFilter] = useState<WorklistReason | "all">("all");
  const [dispatchEditing, setDispatchEditing] = useState<string | null>(null);
  const [dispatchStatus, setDispatchStatus] = useState<string>("in_progress");
  const [dispatchOwner, setDispatchOwner] = useState("");
  const [dispatchNote, setDispatchNote] = useState("");
  const [dispatchBusy, setDispatchBusy] = useState(false);
  const [dispatchNotice, setDispatchNotice] = useState("");
  const [dispatchError, setDispatchError] = useState("");
// 按监管表分装导出：派工是按表派的，平铺一份 CSV 让经办人自己切分等于没派工。
const [worklistArchiveBusy, setWorklistArchiveBusy] = useState(false);
  const [decisionNotice, setDecisionNotice] = useState("");
  const [scriptDiffBusy, setScriptDiffBusy] = useState(false);
  const [scriptDiffError, setScriptDiffError] = useState("");
  // 覆盖度区块的"从脚本建需"：单独记状态，避免和交付状态刷新互相干扰。
  const [coverageReload, setCoverageReload] = useState(0);
  const [authoringCode, setAuthoringCode] = useState("");
  const [authorNotice, setAuthorNotice] = useState("");
  const [authorError, setAuthorError] = useState("");
  // 批量建需：先给看板一排复选框，再一次性预检 + 建需，逐表回显结果。
  const [authorSelected, setAuthorSelected] = useState<string[]>([]);
  const [authorBatchBusy, setAuthorBatchBusy] = useState(false);
  const [scriptBindingFor, setScriptBindingFor] = useState<DeliveryStatusItem | null>(null);
  // 字段覆盖核对：监管表里没进本需求范围的字段是什么性质（有集市映射 / 只在脚本血缘里 / 都没有）。
  const [fieldCoverageTarget, setFieldCoverageTarget] = useState<DeliveryStatusItem | null>(null);
  const [fieldCoveragePayload, setFieldCoveragePayload] = useState<FieldCoveragePayload | null>(null);
  const [fieldCoverageBusy, setFieldCoverageBusy] = useState(false);
  const [fieldCoverageError, setFieldCoverageError] = useState("");
  const [authorResults, setAuthorResults] = useState<
    { table_code: string; created: boolean; requirement_id?: number | null; content_version?: number | null; bound_field_count?: number | null; reason?: string | null }[] | null
  >(null);

  const visibleDeliveryItems = useMemo(
    () => (delivery ? filterDeliveryItems(delivery.items, deliveryFilter) : []),
    [delivery, deliveryFilter],
  );

  function selectVisible() {
    if (!visibleDeliveryItems.length) return;
    setSelected((current) => {
      const next = new Set(current);
      for (const item of visibleDeliveryItems) next.add(item.requirement_id);
      return Array.from(next);
    });
  }

  function toggleSelected(requirementId: number) {
    setSelected((current) =>
      current.includes(requirementId)
        ? current.filter((item) => item !== requirementId)
        : [...current, requirementId],
    );
  }

  function toggleAll() {
    if (!delivery) return;
    setSelected((current) =>
      current.length === delivery.items.length ? [] : delivery.items.map((item) => item.requirement_id),
    );
  }

  async function authorFromScript(item: TableCoverageItem) {
    if (authoringCode) return;
    setAuthoringCode(item.table_code);
    setAuthorNotice("");
    setAuthorError("");
    try {
      const preview = await apiPost<{ items: { table_code: string; authorable: boolean; bound_field_count?: number; field_count?: number; reason?: string }[] }>(
        `/projects/${projectId}/requirements/author-preview`,
        { table_codes: [item.table_code] },
      );
      const candidate = preview.items?.[0];
      if (!candidate?.authorable) {
        setAuthorError(`${item.table_code} 不能一键建需：${candidate?.reason || "脚本与监管字段没有可绑定的同名项"}`);
        return;
      }
      const result = await apiPost<{
        created_count: number;
        items: { requirement_id?: number; content_version?: number; bound_field_count?: number; created?: boolean; deduplicated?: boolean; reason?: string }[];
      }>(`/projects/${projectId}/requirements/author-from-scripts`, { table_codes: [item.table_code] });
      const done = result.items?.[0];
      if (!done?.created) {
        setAuthorError(`${item.table_code} 没有建出需求：${done?.reason || "服务端未返回新建项"}`);
        return;
      }
      setAuthorNotice(
        `已为 ${item.table_code} 建需：需求 #${done.requirement_id}（内容 v${done.content_version}），按同名规则绑定 ${done.bound_field_count ?? candidate.bound_field_count ?? 0} 个监管字段；正文仍需到工作台生成候选并采纳。`,
      );
      setCoverageReload((value) => value + 1);
      setDeliveryReload((value) => value + 1);
    } catch (reason) {
      setAuthorError(describeError(reason, "从脚本建需失败：可能需要 technical.edit / business.edit 权限，或该表已有需求。"));
    } finally {
      setAuthoringCode("");
    }
  }

  async function authorBatch() {
    if (!authorSelected.length || authorBatchBusy) return;
    setAuthorBatchBusy(true);
    setAuthorNotice("");
    setAuthorError("");
    setAuthorResults(null);
    try {
      const codes = authorSelected.slice(0, 10);
      const preview = await apiPost<{ items: { table_code: string; authorable: boolean; reason?: string }[] }>(
        `/projects/${projectId}/requirements/author-preview`,
        { table_codes: codes },
      );
      const authorable = (preview.items || []).filter((item) => item.authorable).map((item) => item.table_code);
      if (!authorable.length) {
        setAuthorResults((preview.items || []).map((item) => ({ table_code: item.table_code, created: false, reason: item.reason })));
        setAuthorError("这批表都不能自动建需，具体原因见下方逐表结果。");
        return;
      }
      const result = await apiPost<{
        created_count: number;
        items: { table_code: string; created: boolean; requirement_id?: number | null; content_version?: number | null; bound_field_count?: number | null; reason?: string | null }[];
      }>(`/projects/${projectId}/requirements/author-from-scripts`, { table_codes: authorable });
      setAuthorResults(result.items || []);
      setAuthorNotice(
        `批量建需完成：新建 ${result.created_count} 条需求（提交 ${authorable.length} 张表，最多一次 10 张）；正文仍需到工作台逐字段生成候选并采纳。`,
      );
      setAuthorSelected([]);
      setCoverageReload((value) => value + 1);
      setDeliveryReload((value) => value + 1);
    } catch (reason) {
      setAuthorError(describeError(reason, "批量建需失败：可能需要 technical.edit / business.edit 权限。"));
    } finally {
      setAuthorBatchBusy(false);
    }
  }

  async function exportSelected() {
    if (!delivery || !selected.length || batchBusy) return;
    const items = delivery.items.filter((item) => selected.includes(item.requirement_id));
    if (items.some((item) => !item.current_content_hash)) {
      setBatchError("有需求的内容哈希还没返回，无法保证导出的是你屏幕上看到的那一版；请刷新后重试。");
      return;
    }
    setBatchBusy(true);
    setBatchError("");
    setBatchNotice("");
    try {
      const form = new FormData();
      form.append("selection", JSON.stringify(items.map((item) => ({
        requirement_id: item.requirement_id,
        expected_version: item.requirement_version,
        expected_hash: item.current_content_hash,
      }))));
      form.append("format", "xlsx");
      form.append("layout", "survey");
      const { blob, fileName, headers } = await uploadFormDownload(
        `/projects/${projectId}/requirements/exports-batch`, form);
      const batchHeaders = headers as Record<string, string | null | undefined>;
      const link = document.createElement("a");
      link.href = URL.createObjectURL(blob);
      link.download = fileName;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(link.href);
      setBatchNotice(
        `已导出 ${batchHeaders["x-requirement-batch-items"] || items.length} 条需求；`
        + `本次新建快照 ${batchHeaders["x-requirement-batch-snapshots-created"] ?? "未返回"} 份；`
        + `压缩包 sha256 ${batchHeaders["x-requirement-batch-file-sha256"] ?? "未返回"}。`
        + "压缩包里的 manifest.json 记录每份文件来自哪份快照与哪个产物。",
      );
      setSelected([]);
    } catch (reason) {
      setBatchError(describeError(reason, "批量导出失败，本次没有冻结任何需求。"));
    } finally {
      setBatchBusy(false);
    }
  }

  async function refreezeSelected() {
    if (!delivery || !selected.length || refreezeBusy) return;
    const items = delivery.items.filter((item) => selected.includes(item.requirement_id));
    if (items.some((item) => !item.current_content_hash)) {
      setRefreezeError("有需求的内容哈希还没返回，无法确认冻结的就是你屏幕上看到的那一版；请刷新后重试。");
      return;
    }
    setRefreezeBusy(true);
    setRefreezeError("");
    setRefreezeNotice("");
    try {
      // 只冻结、不渲染：把快照对齐到当前内容，不产生新文件。
      const result = await apiPost<{ item_count: number; snapshots_created: number }>(
        `/projects/${projectId}/requirements/refreeze-batch`,
        {
          selection: items.map((item) => ({
            requirement_id: item.requirement_id,
            expected_version: item.requirement_version,
            expected_hash: item.current_content_hash,
          })),
        },
      );
      setRefreezeNotice(
        `已重新冻结 ${result.item_count} 条需求；本次新建快照 ${result.snapshots_created} 份`
        + `（其余内容与已有快照相同，复用原快照）。这次没有生成任何文件，需要文件请在导出面板单独导出。`,
      );
      setSelected([]);
      setDeliveryReload((value) => value + 1);
    } catch (reason) {
      setRefreezeError(describeError(reason, "批量重新冻结失败，本次没有冻结任何需求。"));
    } finally {
      setRefreezeBusy(false);
    }
  }

  async function openGapBreakdown(item: DeliveryStatusItem) {
    setGapBreakdownFor(item);
    setGapBreakdown(null);
    setGapBreakdownError("");
    setGapBreakdownBusy(true);
    try {
      // 归类与条数都由服务端给，前端不按 message 猜类别——否则看板与工作台会各说各的。
      setGapBreakdown(
        await apiGet<GapBreakdownResponse>(
          `/projects/${projectId}/requirements/${item.requirement_id}/gap-breakdown`,
        ),
      );
    } catch (reason) {
      setGapBreakdownError(describeError(reason, "缺口摘要读取失败，可稍后重试；不影响上方统计。"));
    } finally {
      setGapBreakdownBusy(false);
    }
  }

  const [acceptanceBusy, setAcceptanceBusy] = useState<number | null>(null);
  // 页面子树会被 AppShell 按 project-scope 重挂载，把结果放在组件 state 里会在那次重挂载中丢掉，
  // 所以结果存模块级 store，重挂载后新实例仍能读到（见 lib/acceptance-notice.ts 的说明）。
  const acceptanceNotice = useSyncExternalStore(
    subscribeAcceptanceNotice,
    getAcceptanceNotice,
    getServerAcceptanceNotice,
  );
  const acceptanceResult = noticeForProject(acceptanceNotice, Number(projectId));
  const [auditReload, setAuditReload] = useState(0);
  const [stabilityOpen, setStabilityOpen] = useState(false);
  const [stabilityPayload, setStabilityPayload] = useState<ExportStabilityPayload | null>(null);
  const [stabilityBusy, setStabilityBusy] = useState(false);
  const [stabilityError, setStabilityError] = useState<string | null>(null);
  // 复核清单：只列元数据（不重放），用来回答"到底哪些需求/渲染器版本受影响"。
  const [manifestOpen, setManifestOpen] = useState(false);
  const [manifestPayload, setManifestPayload] = useState<ReplayManifestPayload | null>(null);
  const [manifestState, setManifestState] = useState<ReplayManifestState | "">("");
  const [manifestKeyword, setManifestKeyword] = useState("");
  const [manifestBusy, setManifestBusy] = useState(false);
  const [manifestError, setManifestError] = useState<string | null>(null);

  const [acceptanceBatchBusy, setAcceptanceBatchBusy] = useState(false);
  // 人工核对登记：只对「自动验收跑不了」的产物开，表单就挂在那一行下面。
  const [attestTarget, setAttestTarget] = useState<DeliveryAuditItem | null>(null);
  const [attestConclusion, setAttestConclusion] = useState<"confirmed" | "rejected">("confirmed");
  const [attestBasis, setAttestBasis] = useState("");
  const [attestBusy, setAttestBusy] = useState(false);
  const [attestError, setAttestError] = useState("");

  async function runAcceptance(item: DeliveryAuditItem) {
    setAcceptanceBusy(item.artifact_id);
    clearAcceptanceNotice();
    try {
      const payload = await apiPost<{
        verdict: string;
        blocking_keys: string[];
        record?: { id: number } | null;
      }>(
        `/projects/${projectId}/requirements/${item.requirement_id}/render-artifacts/${item.artifact_id}/acceptance-run`,
        {},
      );
      const recordId = payload.record?.id;
      const passed = payload.verdict === "pass";
      publishAcceptanceNotice({
        projectId: Number(projectId),
        artifactId: item.artifact_id,
        kind: passed ? "pass" : "blocked",
        recordId: recordId ?? null,
        at: Date.now(),
        text: passed
          ? `产物 #${item.artifact_id} 一键验收通过${recordId ? `，已存档为检查记录 #${recordId}` : ""}。通过只说明文件本身对得上，不代表业务口径已确认。`
          : `产物 #${item.artifact_id} 一键验收未通过：${payload.blocking_keys.join("、") || "未知项"}。${
              recordId ? `已存档为检查记录 #${recordId}。` : ""
            }未通过不是"文件坏了"，先看阻断项再决定重渲染还是改数据。`,
      });
      setAuditReload((value) => value + 1);
    } catch (reason) {
      publishAcceptanceNotice({
        projectId: Number(projectId),
        artifactId: item.artifact_id,
        kind: "error",
        recordId: null,
        at: Date.now(),
        text:
          (reason as { detail?: string; message?: string })?.detail ??
          (reason as { message?: string })?.message ??
          "一键验收失败，可稍后重试。",
      });
    } finally {
      setAcceptanceBusy(null);
    }
  }

  async function runAcceptanceBatch() {
    // 批量只跑"还没有检查记录"的产物：已查过的不重复刷记录，否则"查过几次"会被批量动作稀释。
    setAcceptanceBatchBusy(true);
    clearAcceptanceNotice();
    try {
      const payload = await apiPost<{
        summary: {
          attempted: number;
          passed: number;
          failed: number;
          errored: number;
          skipped: number;
          checked_after: number;
          unchecked_after: number;
        };
        results: Array<{
          artifact_id: number;
          verdict: string;
          blocking_keys: string[];
          record_id: number | null;
          message: string | null;
        }>;
        unsupported: Array<{ artifact_id: number; code: string; reason: string }>;
      }>(`/projects/${projectId}/requirements-acceptance/batch`, { only_unchecked: true, limit: 10 });
      const { summary, results } = payload;
      const bad = results
        .filter((row) => row.verdict !== "pass")
        .slice(0, 3)
        .map((row) =>
          row.verdict === "error"
            ? `#${row.artifact_id}（${row.message ?? "出错"}）`
            : `#${row.artifact_id}（${row.blocking_keys.join("、") || "未通过"}）`,
        );
      // 不适用自动验收的产物要单独说清楚：跳过不等于通过，它们仍然需要人工核对。
      const unsupported =
        summary.skipped > 0
          ? `另有 ${summary.skipped} 个产物不支持自动验收（内置版式 / 客户模板），需要人工核对：${(payload.unsupported ?? [])
              .slice(0, 3)
              .map((row) => `#${row.artifact_id}`)
              .join("、")}。`
          : "";
      const head =
        summary.attempted === 0
          ? `批量验收：没有可自动验收的未检查产物（已检查 ${summary.checked_after} 个）。`
          : `批量验收：跑完 ${summary.attempted} 个产物，通过 ${summary.passed} 个、未通过 ${summary.failed} 个、出错 ${summary.errored} 个；已检查 ${summary.checked_after} 个、仍未检查 ${summary.unchecked_after} 个。`;
      publishAcceptanceNotice({
        projectId: Number(projectId),
        artifactId: null,
        scope: "batch",
        kind: summary.failed + summary.errored === 0 ? "pass" : "blocked",
        recordId: null,
        at: Date.now(),
        text: `${head}${unsupported}${bad.length ? `未过：${bad.join("；")}。` : ""}每个产物各自写了一条检查记录；跳过的不写记录、也不算通过；通过只说明文件本身对得上，不代表业务口径已确认。`,
      });
      setAuditReload((value) => value + 1);
    } catch (reason) {
      publishAcceptanceNotice({
        projectId: Number(projectId),
        artifactId: null,
        scope: "batch",
        kind: "error",
        recordId: null,
        at: Date.now(),
        text:
          (reason as { detail?: string; message?: string })?.detail ??
          (reason as { message?: string })?.message ??
          "批量验收失败，可稍后重试。",
      });
    } finally {
      setAcceptanceBatchBusy(false);
    }
  }

  function openAttestation(item: DeliveryAuditItem) {
    // 每个人都从空依据开始写：复制上一条依据最容易让"核对"退化成走过场。
    setAttestTarget(item);
    setAttestConclusion("confirmed");
    setAttestBasis("");
    setAttestError("");
  }

  async function runAttestation() {
    const item = attestTarget;
    if (!item) return;
    setAttestBusy(true);
    setAttestError("");
    clearAcceptanceNotice();
    try {
      const payload = await apiPost<{
        attestation: { id: number; conclusion_label: string };
        note: string;
      }>(
        `/projects/${projectId}/requirements/${item.requirement_id}/render-artifacts/${item.artifact_id}/attestations`,
        { conclusion: attestConclusion, basis: attestBasis },
      );
      publishAcceptanceNotice({
        projectId: Number(projectId),
        artifactId: item.artifact_id,
        kind: attestConclusion === "confirmed" ? "pass" : "blocked",
        recordId: payload.attestation.id,
        at: Date.now(),
        text: `产物 #${item.artifact_id} 已登记人工核对 #${payload.attestation.id}（${payload.attestation.conclusion_label}）。人工核对只说明有人看过并写了依据：不改变交付状态、不关闭缺口，也不算机器检查。`,
      });
      setAttestTarget(null);
      setAttestBasis("");
      setAuditReload((value) => value + 1);
    } catch (reason) {
      setAttestError(
        (reason as { detail?: string; message?: string })?.detail ??
          (reason as { message?: string })?.message ??
          "人工核对登记失败，可稍后重试。",
      );
    } finally {
      setAttestBusy(false);
    }
  }

  async function openFieldCoverage(item: DeliveryStatusItem) {
    setFieldCoverageTarget(item);
    setFieldCoveragePayload(null);
    setFieldCoverageError("");
    setFieldCoverageBusy(true);
    try {
      setFieldCoveragePayload(
        await apiGet<FieldCoveragePayload>(
          `/projects/${projectId}/requirements/${item.requirement_id}/field-coverage?sample=200`,
        ),
      );
    } catch (reason) {
      setFieldCoverageError(describeError(reason, "字段覆盖读取失败，可稍后重试；不影响上方统计。"));
    } finally {
      setFieldCoverageBusy(false);
    }
  }

  function closeFieldCoverage() {
    setFieldCoverageTarget(null);
    setFieldCoveragePayload(null);
    setFieldCoverageError("");
  }

  async function openWorklist() {
    setWorklistOpen(true);
    setWorklistBusy(true);
    setWorklistError("");
    setWorklistFilter("all");
    try {
      // 四类待办原因与计数全部由服务端归并；前端只做展示、筛选与 CSV。
      setWorklist(await apiGet<WorklistResponse>(`/projects/${projectId}/requirements-worklist?limit=3000`));
    } catch (reason) {
      setWorklistError(describeError(reason, "待办清单读取失败，可稍后重试；不影响上方统计。"));
    } finally {
      setWorklistBusy(false);
    }
  }

  async function openStability() {
    setStabilityOpen(true);
    setStabilityBusy(true);
    setStabilityError(null);
    try {
      const payload = await apiGet<ExportStabilityPayload>(`/projects/${projectId}/export-stability?limit=20`);
      setStabilityPayload(payload);
    } catch (failure) {
      setStabilityError(failure instanceof Error ? failure.message : "稳定性核对失败");
    } finally {
      setStabilityBusy(false);
    }
  }

  function closeStability() {
    setStabilityOpen(false);
    setStabilityError(null);
  }

  async function loadManifest(nextState: ReplayManifestState | "" = manifestState, keyword: string = manifestKeyword) {
    setManifestBusy(true);
    setManifestError(null);
    try {
      const params = new URLSearchParams({ limit: "200" });
      if (nextState) {
        params.set("state", nextState);
      }
      if (keyword.trim()) {
        params.set("keyword", keyword.trim());
      }
      const payload = await apiGet<ReplayManifestPayload>(
        `/projects/${projectId}/replay-manifest?${params.toString()}`,
      );
      setManifestPayload(payload);
    } catch (failure) {
      setManifestError(failure instanceof Error ? failure.message : "复核清单加载失败");
    } finally {
      setManifestBusy(false);
    }
  }

  async function openManifest() {
    setManifestOpen(true);
    await loadManifest();
  }

  function closeManifest() {
    setManifestOpen(false);
    setManifestError(null);
  }

  async function reloadWorklist() {
    try {
      // 只刷新清单，不重置筛选：登记完处置后当前筛选结果要能就地看到变化。
      setWorklist(await apiGet<WorklistResponse>(`/projects/${projectId}/requirements-worklist?limit=3000`));
    } catch (reason) {
      setWorklistError(describeError(reason, "待办清单刷新失败，可稍后重试。"));
    }
  }

  function startDispatch(item: WorklistItem) {
    setDispatchEditing(`${item.requirement_id}:${item.field_id}`);
    setDispatchStatus(item.dispatch?.status || "in_progress");
    setDispatchOwner(item.dispatch?.owner || "");
    setDispatchNote(item.dispatch?.note || "");
    setDispatchNotice("");
    setDispatchError("");
  }

  async function saveDispatch(item: WorklistItem) {
    if (dispatchBusy) return;
    setDispatchBusy(true);
    setDispatchError("");
    try {
      await apiPost(`/projects/${projectId}/requirements-worklist/dispatch`, {
        requirement_id: item.requirement_id,
        field_id: item.field_id,
        owner: dispatchOwner,
        status: dispatchStatus,
        note: dispatchNote,
      });
      const label = DISPATCH_STATUS_OPTIONS.find((option) => option.value === dispatchStatus)?.label || dispatchStatus;
      setDispatchNotice(
        `已登记 ${worklistFieldText(item)} 的处置：${dispatchOwner.trim() || "未填责任人"} · ${label}。登记只记录进展，缺口是否关闭仍由工作台按内容重新评估。`,
      );
      setDispatchEditing(null);
      await reloadWorklist();
    } catch (reason) {
      setDispatchError(describeError(reason, "登记处置失败，可稍后重试。"));
    } finally {
      setDispatchBusy(false);
    }
  }

  function exportWorklistCsv() {
    if (!worklist) return;
    const items: WorklistItem[] = filterWorklist(worklist.items, worklistFilter);
    const blob = new Blob([worklistCsv(worklist, items)], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `待办派工清单-${worklistFilter === "all" ? "全部" : worklist.reason_labels[worklistFilter]}-${items.length}条.csv`;
    link.click();
    URL.revokeObjectURL(url);
  }

  async function exportWorklistArchive() {
    if (worklistArchiveBusy) return;
    setWorklistArchiveBusy(true);
    setWorklistError("");
    try {
      // 服务端按监管表分装（一张表一个 CSV + manifest.json），文件名与条目数都由服务端给。
      const { blob, fileName } = await apiDownload(
        `/projects/${projectId}/requirements-worklist/archive?limit=3000`,
      );
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = fileName;
      link.click();
      URL.revokeObjectURL(url);
    } catch (reason) {
      setWorklistError(describeError(reason, "按监管表导出失败，可稍后重试；不影响上方统计。"));
    } finally {
      setWorklistArchiveBusy(false);
    }
  }

  async function downloadArtifact(item: DeliveryStatusItem) {
    if (!item.last_artifact || downloadingId !== null) return;
    setDownloadingId(item.requirement_id);
    setArtifactError("");
    setArtifactNotice("");
    try {
      // 直接取已存产物（服务端按 sha256 校验），不重渲：下载到的就是那次导出的文件。
      const { blob, fileName } = await apiDownload(
        `/projects/${projectId}/requirements/${item.requirement_id}/render-artifacts/${item.last_artifact.id}/download`,
      );
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = fileName;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
      setArtifactNotice(
        `已下载需求「${item.name}」的产物 #${item.last_artifact.id}（${fileName}，${blob.size} 字节）。`,
      );
    } catch (reason) {
      setArtifactError(
        describeError(reason, "下载产物失败：文件可能已被清理或完整性校验未通过，请在导出面板重新导出。"),
      );
    } finally {
      setDownloadingId(null);
    }
  }

  async function openGapPanel(columnKey: string, limit = 500, tableCode?: string) {
    setGapColumn(columnKey);
    setGapBusy(true);
    setGapError("");
    const filter = (tableCode ?? "").trim();
    setGapFilter(filter);
    try {
      // 缺口清单由服务端按与填充率同一口径列出；前端只展示与导出，不按列名猜归属。
      // table_code 只缩小本次返回范围，不改变"该列共多少条缺口"的口径。
      const query = filter ? `&table_code=${encodeURIComponent(filter)}` : "";
      const body = await apiGet<TemplateGapResponse>(
        `/projects/${projectId}/template-coverage/gaps/${columnKey}?limit=${limit}${query}`,
      );
      setGapPanel(body);
    } catch (reason) {
      setGapPanel(null);
      setGapError(describeError(reason, "缺口清单读取失败，可稍后重试。"));
    } finally {
      setGapBusy(false);
    }
  }

  function downloadGapCsv() {
    if (!gapPanel) return;
    const blob = new Blob([templateGapCsv(gapPanel)], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `模板缺口-${gapPanel.column_label}-${gapPanel.returned}条.csv`;
    link.click();
    URL.revokeObjectURL(url);
  }

  useEffect(() => {
    apiGet<ProjectReadiness>(`/projects/${projectId}/readiness`)
      .then(setData)
      .catch((reason) => setError(describeError(reason, "项目就绪度加载失败，请稍后重试。")));
    // 覆盖度与上面两块互不阻塞：它回答的是"哪些监管表还没有需求/脚本"。
    apiGet<TableCoverageResponse>(`/projects/${projectId}/table-coverage`)
      .then(setCoverage)
      .catch((reason) =>
        setCoverageError(describeError(reason, "监管表覆盖度读取失败，该区块不影响上方内容，可稍后刷新。")),
      );
    // 交付审计回答的是"这一批交出去之前，有没有哪个文件没查过"。
    apiGet<DeliveryAuditResponse>(`/projects/${projectId}/delivery-audit?limit=200`)
      .then(setAudit)
      .catch((reason) =>
        setAuditError(describeError(reason, "交付审计读取失败，该区块不影响上方内容，可稍后刷新。")),
      );
    // 模板列填充率回答的是"导出文档里的空列，是模板没给还是平台没填"。
    apiGet<TemplateColumnCoverageResponse>(`/projects/${projectId}/template-coverage`)
      .then(setTemplateCoverage)
      .catch((reason) =>
        setTemplateCoverageError(describeError(reason, "模板列填充率读取失败，该区块不影响上方内容，可稍后刷新。")),
      );
  }, [projectId, coverageReload, auditReload]);
  // auditReload 必须进依赖：登记人工核对 / 一键验收 / 批量验收都只改库，不重跑这个 effect 就永远显示上一次的快照（曾因此把刚登记的行显示成「还没有人工核对登记」）。

  // 交付状态单独加载：重新冻结之后要能就地刷新，而不是让整页重新请求准备度与覆盖度。
  useEffect(() => {
    apiGet<DeliveryStatusResponse>(`/projects/${projectId}/requirements-status`)
      .then((payload) => {
        setDelivery(payload);
        setDeliveryError("");
      })
      .catch((reason) =>
        setDeliveryError(describeError(reason, "需求交付状态读取失败，该区块不影响上方准备度，可稍后刷新。")),
      );
  }, [projectId, deliveryReload]);

  // 打开「脚本依据」时顺带取"这次脚本更新到底改了哪些目标字段"：只读，且只对同一脚本文件的版本比较。
  async function reloadFreshness(): Promise<void> {
    const payload = await apiGet<ScriptBasisFreshnessResponse>("/projects/" + projectId + "/script-basis-freshness");
    setFreshness(payload);
    setFreshnessFor((current) =>
      current ? payload.items.find((row) => row.requirement_id === current.requirement_id) || null : null,
    );
  }

  // 登记"看过之后决定怎么办"：只写决定，不重新冻结、不改正文（真实动作仍在工作台里做）。
  async function recordDecision(
    version: ScriptBasisVersionFreshness,
    decision: string,
    requiresNote: boolean,
  ): Promise<void> {
    if (!freshnessFor) return;
    const note = (decisionNotes[version.version_id] || "").trim();
    if (requiresNote && !note) {
      setDecisionError("选择「复核后暂不跟随」或「认为新脚本有误」必须写明原因。");
      return;
    }
    setDecisionBusy(true);
    setDecisionError("");
    try {
      await apiPost<{ created: boolean; decision: ScriptBasisDecision }>(
        "/projects/" + projectId + "/requirements/" + freshnessFor.requirement_id + "/script-basis-decisions",
        {
          script_file_id: version.script_file_id,
          frozen_version_id: version.version_id,
          latest_version_id: version.latest_version_id,
          decision,
          note: note || null,
        },
      );
      setDecisionNotes((current) => ({ ...current, [version.version_id]: "" }));
      setDecisionNotice("");
      if (decision === "follow_planned") {
        // 决定"跟着新脚本走"之后立刻排出重新生成任务：只建输入与任务，不采纳、不冻结、不切换依据。
        const target = delivery?.items.find((row) => row.requirement_id === freshnessFor.requirement_id);
        if (!target) {
          setDecisionError("找不到这条需求的当前版本与内容哈希，请刷新后再排定重新生成。");
        } else {
          const form = new FormData();
          form.append("script_file_id", String(version.script_file_id));
          form.append("expected_version", String(target.requirement_version));
          form.append("expected_hash", target.current_content_hash);
          form.append("sections", "business,lineage");
          const rebuilt = await uploadForm<{
            input_id: number;
            job_id: number;
            field_count: number;
          }>("/projects/" + projectId + "/requirements/" + target.requirement_id + "/script-basis-regenerate", form);
          setDecisionNotice(
            `已按新脚本排定重新生成：${rebuilt.field_count} 个绑定字段 × 2 个章节（输入 #${rebuilt.input_id}，任务 #${rebuilt.job_id}）。` +
              "正文仍需在生成轮次里逐字段采纳；脚本依据不会自动切换。",
          );
        }
      }
      await reloadFreshness();
    } catch (reason) {
      setDecisionError(describeError(reason, "登记处置决定失败，可稍后重试；本次没有改动任何内容。"));
    } finally {
      setDecisionBusy(false);
    }
  }

  async function openFreshness(item: ScriptBasisFreshnessItem): Promise<void> {
    setFreshnessFor(item);
    setScriptDiff(null);
    setScriptDiffError("");
    setScriptDiffBusy(true);
    try {
      const payload = await apiGet<ScriptBasisDiffResponse>(
        `/projects/${projectId}/requirements/${item.requirement_id}/script-basis-diff`,
      );
      setScriptDiff(payload);
    } catch (reason) {
      setScriptDiffError(describeError(reason, "脚本版本差异读取失败，可稍后重试；不影响上方的任务与冻结状态。"));
    } finally {
      setScriptDiffBusy(false);
    }
  }

  // 脚本依据新鲜度：脚本重新导入后，哪条需求的依据落后了。只读、不做任何改动。
  useEffect(() => {
    apiGet<ScriptBasisFreshnessResponse>(`/projects/${projectId}/script-basis-freshness`)
      .then((payload) => {
        setFreshness(payload);
        setFreshnessError("");
      })
      .catch((reason) =>
        setFreshnessError(describeError(reason, "脚本依据新鲜度读取失败，该列不影响上方统计，可稍后刷新。")),
      );
  }, [projectId, deliveryReload]);

  return (
    <main>
      <WorkspaceHeader
        title="项目准备度"
        meta="关键阻断优先于加权完成度"
        actions={
          <Link className="button-secondary" href={`/projects/${projectId}/onboarding`}>
            查看初始化向导
          </Link>
        }
      />
      <div className="mx-auto max-w-7xl space-y-5 p-4 lg:p-6">
        {error ? (
          <div className="rounded-lg border border-coral-200 bg-coral-50 px-3 py-2 text-sm text-coral-700">{error}</div>
        ) : null}
        <section className="panel p-5">
          <div className="flex flex-wrap items-end justify-between gap-4">
            <div>
              <div className="stat-label">总体状态</div>
              <div className="stat-value">{data ? STATUS[data.overall_status] || "状态待同步" : "加载中"}</div>
            </div>
            <div className="text-right">
              <div className="stat-label">加权完成度</div>
              <div className="stat-value text-pine-600">{data ? `${Math.round(data.score * 100)}%` : "-"}</div>
            </div>
          </div>
          <div className="mt-4 h-2 rounded-full bg-slate-100">
            <div
              className="h-2 rounded-full bg-pine transition-all"
              style={{ width: `${Math.round((data?.score || 0) * 100)}%` }}
            />
          </div>
          {data?.critical_blockers.length ? (
            <div className="mt-5 rounded-lg border border-gold-200 bg-gold-50 p-4">
              <div className="flex items-center gap-2 font-semibold text-gold-800">
                <AlertTriangle size={18} />
                关键阻断项
              </div>
              <ul className="mt-2 space-y-1 text-sm text-gold-800">
                {data.critical_blockers.map((item) => (
                  <li key={`${item.dimension}-${item.code}`}>{describeUserMessage(item.message, "该原因说明待补充，请人工核验。")}</li>
                ))}
              </ul>
            </div>
          ) : null}
        </section>

        <section className="panel p-5" aria-label="需求交付状态">
          <div className="flex flex-wrap items-baseline justify-between gap-3">
            <div>
              <h2 className="text-sm font-semibold text-ink">需求交付状态</h2>
              <p className="mt-1 text-xs text-slate-500">
                判据与工作台一致：最近快照的 content hash 等于当前内容 hash 才算已冻结；"可直接重新导出"还要求已有产物。数字全部来自服务端聚合，不做推断。
              </p>
            </div>
            {delivery ? (
              <div className="flex flex-wrap items-center gap-3">
                <p className="text-xs text-slate-600">
                  {delivery.requirement_count} 条需求：{readinessHeadline(delivery.summary)}
                </p>
                <button
                  aria-label="打开待办派工清单"
                  className="button-secondary h-7 text-xs"
                  disabled={worklistBusy}
                  onClick={() => void openWorklist()}
                  type="button"
                >
                  待办派工清单
                </button>
              </div>
            ) : null}
          </div>
          {worklistOpen ? (
            <div className="fixed inset-0 z-40 flex items-start justify-center overflow-y-auto bg-ink/40 p-6">
              <div className="w-full max-w-6xl rounded-xl bg-white p-5 shadow-xl" aria-label="待办派工清单" role="dialog">
                <div className="flex flex-wrap items-baseline justify-between gap-3">
                  <h3 className="text-sm font-semibold text-ink">待办派工清单</h3>
                  <div className="flex items-center gap-2">
                    <button className="button-secondary h-7 text-xs" onClick={exportWorklistCsv} type="button">
                      下载 CSV
                    </button>
                    <button
                      className="button-secondary h-7 text-xs"
                      aria-label="按监管表导出待办清单"
                      disabled={worklistArchiveBusy}
                      onClick={() => void exportWorklistArchive()}
                      type="button"
                    >
                      {worklistArchiveBusy ? "正在分装…" : "按监管表导出（ZIP）"}
                    </button>
                    <button className="button-secondary h-7 text-xs" onClick={() => setWorklistOpen(false)} type="button">
                      关闭
                    </button>
                  </div>
                </div>
                {worklistBusy ? <p className="mt-3 text-xs text-slate-500">正在汇总四类待办事项…</p> : null}
                {worklistError ? (
                  <p className="mt-3 rounded-lg border border-coral-200 bg-coral-50 px-3 py-2 text-xs text-coral-700">
                    {worklistError}
                  </p>
                ) : null}
                {worklist ? (
                  <>
                    <p className="mt-2 text-xs text-slate-600">{worklistHeadline(worklist)}</p>
                    {worklist.rejected_requirement_count ? (
                      <div
                        aria-label="被否产物提示"
                        className="mt-2 rounded-lg border border-coral-200 bg-coral-50 px-3 py-2 text-xs"
                      >
                        <p className="font-medium text-coral-700">{worklistRejectedHeadline(worklist)}</p>
                        <ul className="mt-1 space-y-1 text-slate-700">
                          {(worklist.rejected_requirements ?? []).map((entry) => (
                            <li
                              data-rejected-artifact={entry.artifact_id}
                              key={`${entry.requirement_id}-${entry.artifact_id}`}
                            >
                              {`${entry.target_table_code || "—"} · ${entry.requirement_name} · 产物 #${entry.artifact_id}（${entry.field_count} 个字段）· 依据：${entry.basis}`}
                            </li>
                          ))}
                        </ul>
                      </div>
                    ) : null}
                    {worklist.rejection_followup?.summary?.rejected ? (
                      <div
                        aria-label="被否后续核对"
                        className="mt-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs"
                      >
                        <p className="font-medium text-amber-800">{followupText(worklist.rejection_followup)}</p>
                        <ul className="mt-1 space-y-1 text-slate-700">
                          {(worklist.rejection_followup.items ?? [])
                            .filter((entry) => followupNeedsAttention(entry))
                            .map((entry) => (
                              <li
                                data-followup-state={entry.state}
                                key={`followup-${entry.requirement_id}`}
                              >
                                {`${followupItemText(entry)} · ${entry.state_label}`}
                              </li>
                            ))}
                        </ul>
                        <p className="mt-1 text-slate-600">
                          重新导出只是让人再核对一次：内容变了不代表已通过，换版式更不代表改动。
                        </p>
                      </div>
                    ) : null}
                    {worklist.gap_consistency_totals ? (
                      <p className="mt-1 text-xs text-slate-600">
                        {`处置与缺口：处置中 ${worklist.gap_consistency_totals.in_progress ?? 0} · 已处置但缺口未清 ${
                          worklist.gap_consistency_totals.done_with_gaps ?? 0
                        } · 处置与缺口一致 ${worklist.gap_consistency_totals.done_clear ?? 0} · 未登记处置 ${
                          worklist.gap_consistency_totals.no_dispatch ?? 0
                        }`}
                      </p>
                    ) : null}
                    <p className="mt-1 text-xs text-slate-500">
                      判断口径：{WORKLIST_REASON_ORDER.map((reason) => worklist.reason_labels[reason]).join(" / ")}；
                      同一字段可能同时缺多项，所以各项计数相加会大于字段数。
                    </p>
                    {worklist.truncated ? (
                      <p className="mt-1 text-xs text-amber-700">
                        清单过长，只返回了前 {worklist.returned} / {worklist.field_count} 个字段；导出 CSV 也只包含已返回的部分。
                      </p>
                    ) : null}
                    <div className="mt-3 flex flex-wrap items-center gap-2 text-xs" aria-label="待办原因筛选">
                      <span className="text-slate-500">按原因</span>
                      <button
                        aria-pressed={worklistFilter === "all"}
                        className={worklistFilter === "all" ? "button-primary h-7 text-xs" : "button-secondary h-7 text-xs"}
                        onClick={() => setWorklistFilter("all")}
                        type="button"
                      >
                        全部字段 {worklist.field_count}
                      </button>
                      {WORKLIST_REASON_ORDER.map((reason) => (
                        <button
                          aria-pressed={worklistFilter === reason}
                          className={worklistFilter === reason ? "button-primary h-7 text-xs" : "button-secondary h-7 text-xs"}
                          key={reason}
                          onClick={() => setWorklistFilter(reason)}
                          type="button"
                        >
                          {worklist.reason_labels[reason]} {worklistReasonCount(worklist, reason)}
                        </button>
                      ))}
                    </div>
                    {worklistFilter !== "all" ? (
                      <p className="mt-2 rounded-lg border border-line bg-slate-50 px-3 py-2 text-xs text-slate-600">
                        {WORKLIST_REASON_HINTS[worklistFilter]}
                      </p>
                    ) : null}
                    {filterWorklist(worklist.items, worklistFilter).length ? (
                      <div className="mt-3 max-h-[55vh] overflow-auto">
                        <table className="w-full min-w-[1080px] text-left text-xs">
                          <thead className="sticky top-0 bg-white">
                            <tr className="text-slate-500">
                              <th className="py-1 pr-3 font-medium">监管表</th>
                              <th className="py-1 pr-3 font-medium">需求</th>
                              <th className="py-1 pr-3 font-medium">字段</th>
                              <th className="py-1 pr-3 font-medium">待办事项</th>
                              <th className="py-1 pr-3 font-medium">字段级缺口</th>
                              <th className="py-1 pr-3 font-medium">未采纳候选</th>
                              <th className="py-1 pr-3 font-medium">处置 vs 缺口</th>
                              <th className="py-1 pr-3 font-medium">处置</th>
                              <th className="py-1 font-medium">处理</th>
                            </tr>
                          </thead>
                          <tbody>
                            {filterWorklist(worklist.items, worklistFilter).slice(0, 300).map((item) => (
                              <tr
                                className="border-t border-line align-top"
                                key={`${item.requirement_id}-${item.field_id}-${item.primary_reason}`}
                              >
                                <td className="py-1 pr-3">{item.target_table_code || "—"}</td>
                                <td className="py-1 pr-3">{item.requirement_name}</td>
                                <td className="py-1 pr-3">{worklistFieldText(item)}</td>
                                <td className="py-1 pr-3">
                                  <span
                                    className={item.artifact_rejected ? "text-coral-700" : undefined}
                                    title={item.artifact_rejected ? artifactRejectedText(item) : undefined}
                                  >
                                    {item.reason_labels.join(" · ")}
                                  </span>
                                </td>
                                <td className="py-1 pr-3">{item.open_gap_count}</td>
                                <td className="py-1 pr-3">{item.pending_candidate_count}</td>
                                <td className="py-1 pr-3">
                                  <span
                                    className={`badge whitespace-nowrap ${GAP_CONSISTENCY_BADGE[item.gap_consistency?.state ?? "no_dispatch"]}`}
                                    title={gapConsistencyText(item)}
                                  >
                                    {item.gap_consistency?.label ?? "未登记处置"}
                                  </span>
                                </td>
                                <td className="py-1 pr-3">
                                  {dispatchEditing === `${item.requirement_id}:${item.field_id}` ? (
                                    <div className="flex flex-col gap-1">
                                      <select
                                        aria-label={`处置状态 ${worklistFieldText(item)}`}
                                        className="h-7 rounded border border-line bg-white px-1 text-xs"
                                        onChange={(event) => setDispatchStatus(event.target.value)}
                                        value={dispatchStatus}
                                      >
                                        {DISPATCH_STATUS_OPTIONS.map((option) => (
                                          <option key={option.value} value={option.value}>
                                            {option.label}
                                          </option>
                                        ))}
                                      </select>
                                      <input
                                        aria-label={`责任人 ${worklistFieldText(item)}`}
                                        className="h-7 rounded border border-line px-1 text-xs"
                                        onChange={(event) => setDispatchOwner(event.target.value)}
                                        placeholder="责任人"
                                        value={dispatchOwner}
                                      />
                                      <input
                                        aria-label={`处置说明 ${worklistFieldText(item)}`}
                                        className="h-7 rounded border border-line px-1 text-xs"
                                        onChange={(event) => setDispatchNote(event.target.value)}
                                        placeholder="说明（暂停时必须写）"
                                        value={dispatchNote}
                                      />
                                      <div className="flex items-center gap-2">
                                        <button
                                          aria-label={`保存处置 ${worklistFieldText(item)}`}
                                          className="button-primary h-6 text-[11px]"
                                          disabled={dispatchBusy}
                                          onClick={() => void saveDispatch(item)}
                                          type="button"
                                        >
                                          保存
                                        </button>
                                        <button
                                          className="button-secondary h-6 text-[11px]"
                                          onClick={() => setDispatchEditing(null)}
                                          type="button"
                                        >
                                          取消
                                        </button>
                                      </div>
                                    </div>
                                  ) : (
                                    <div className="flex flex-col gap-1">
                                      <span className="whitespace-nowrap text-slate-600">{dispatchText(item)}</span>
                                      {item.dispatch?.history?.length ? (
                                        <details className="text-[11px] text-slate-500">
                                          <summary className="cursor-pointer">处置轨迹（{item.dispatch.history.length}）</summary>
                                          <ul className="mt-1 space-y-1">
                                            {item.dispatch.history.map((entry) => (
                                              <li key={entry.id}>{dispatchHistoryText(entry)}</li>
                                            ))}
                                          </ul>
                                          <p className="mt-1">轨迹只记录处置进展，不代表缺口已关闭。</p>
                                        </details>
                                      ) : null}
                                      <button
                                        aria-label={`登记处置 ${worklistFieldText(item)}`}
                                        className="text-left text-pine-700 underline"
                                        onClick={() => startDispatch(item)}
                                        type="button"
                                      >
                                        {item.dispatch ? "更新处置" : "登记处置"}
                                      </button>
                                    </div>
                                  )}
                                </td>
                                <td className="whitespace-nowrap py-1">
                                  {worklistFieldHref(projectId, item) ? (
                                    <Link
                                      className="text-pine-700 underline"
                                      href={worklistFieldHref(projectId, item) as string}
                                      aria-label={`去工作台处理 ${worklistFieldText(item)}`}
                                    >
                                      去处理
                                    </Link>
                                  ) : (
                                    <span className="text-slate-400">无法定位</span>
                                  )}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    ) : (
                      <p className="mt-3 text-xs text-slate-500">当前原因下没有待办字段：换一个原因，或看全部字段。</p>
                    )}
                    {dispatchNotice ? (
                      <p className="mt-3 rounded-lg border border-pine-200 bg-pine-50 px-3 py-2 text-xs text-pine-700" aria-label="处置登记结果">
                        {dispatchNotice}
                      </p>
                    ) : null}
                    {dispatchError ? (
                      <p className="mt-2 rounded-lg border border-coral-200 bg-coral-50 px-3 py-2 text-xs text-coral-700" aria-label="处置登记失败">
                        {dispatchError}
                      </p>
                    ) : null}
                    <p className="mt-3 text-xs text-slate-500">{worklist.note}</p>
                  </>
                ) : null}
              </div>
            </div>
          ) : null}
          {freshnessError ? (
            <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-700">{freshnessError}</div>
          ) : null}
          {deliveryError ? (
            <p className="mt-3 rounded-lg border border-coral-200 bg-coral-50 px-3 py-2 text-xs text-coral-700">{deliveryError}</p>
          ) : null}
          {!delivery && !deliveryError ? (
            <div className="mt-3 h-24 animate-pulse rounded bg-slate-50" />
          ) : null}
          {delivery && !delivery.items.length ? (
            <p className="mt-3 text-xs text-slate-500">这个项目还没有需求：先由跑批脚本建需，再冻结并导出，才能在这里看到交付状态。</p>
          ) : null}
          {delivery && delivery.items.length ? (
            <>
            <div className="mt-3 flex flex-wrap items-center gap-2 text-xs" aria-label="交付状态筛选">
              <span className="text-slate-500">筛选</span>
              {DELIVERY_STATUS_FILTERS.map((filter) => (
                <button
                  aria-pressed={deliveryFilter === filter.key}
                  className={deliveryFilter === filter.key ? "button-primary h-7 text-xs" : "button-secondary h-7 text-xs"}
                  key={filter.key}
                  onClick={() => setDeliveryFilter(filter.key)}
                  type="button"
                >
                  {filter.label} {deliveryFilterCount(delivery.summary, filter.key)}
                </button>
              ))}
              <span className="text-slate-400">
                当前显示 {visibleDeliveryItems.length} / {delivery.items.length} 条
              </span>
            </div>
            {deliveryFilter !== "all" ? (
              <p className="mt-2 rounded-lg border border-line bg-slate-50 px-3 py-2 text-xs text-slate-600">
                {deliveryFilterHint(deliveryFilter)}
                {" "}
                <button
                  className="button-secondary h-6 text-xs"
                  onClick={() => selectVisible()}
                  type="button"
                >
                  勾选这 {visibleDeliveryItems.length} 条
                </button>
              </p>
            ) : null}
            <div className="mt-3 flex flex-wrap items-center gap-2 text-xs">
              <span className="text-slate-500">批量导出（xlsx · 一表通调研表式）</span>
              <button
                aria-pressed={delivery.items.length > 0 && selected.length === delivery.items.length}
                className="button-secondary h-7 text-xs"
                onClick={toggleAll}
                type="button"
              >
                全选
              </button>
              <button
                className="button-primary h-7 text-xs"
                disabled={!selected.length || batchBusy}
                onClick={() => void exportSelected()}
                type="button"
              >
                {batchBusy ? "冻结并打包中…" : `批量冻结并导出（${selected.length}）`}
              </button>
              <span className="text-slate-400">
                导出前整体预检版本与内容哈希：任何一条不一致就一条都不冻结；一个压缩包装齐所选需求 + manifest.json。
              </span>
            </div>
            <div className="mt-2 flex flex-wrap items-center gap-2 text-xs">
              <span className="text-slate-500">只对齐快照（不导出文件）</span>
              <button
                className="button-secondary h-7 text-xs"
                disabled={!selected.length || refreezeBusy}
                onClick={() => void refreezeSelected()}
                type="button"
              >
                {refreezeBusy ? "重新冻结中…" : `重新冻结这 ${selected.length} 条（不导出）`}
              </button>
              <span className="text-slate-400">
                用于"正文没改、只是模板表级口径变了"的需求：把快照对齐到当前内容，不产生文件。
              </span>
            </div>
            {batchError ? (
              <p className="mt-2 rounded-lg border border-coral-200 bg-coral-50 px-3 py-2 text-xs text-coral-700">{batchError}</p>
            ) : null}
            {batchNotice ? (
              <p className="mt-2 rounded-lg border border-pine-200 bg-pine-50 px-3 py-2 text-xs text-pine-700" aria-label="批量导出结果">
                {batchNotice}
              </p>
            ) : null}
            {refreezeError ? (
              <p className="mt-2 rounded-lg border border-coral-200 bg-coral-50 px-3 py-2 text-xs text-coral-700">{refreezeError}</p>
            ) : null}
            {refreezeNotice ? (
              <p className="mt-2 rounded-lg border border-pine-200 bg-pine-50 px-3 py-2 text-xs text-pine-700" aria-label="重新冻结结果">
                {refreezeNotice}
              </p>
            ) : null}
            {artifactError ? (
              <p className="mt-2 rounded-lg border border-coral-200 bg-coral-50 px-3 py-2 text-xs text-coral-700">{artifactError}</p>
            ) : null}
            {artifactNotice ? (
              <p className="mt-2 rounded-lg border border-pine-200 bg-pine-50 px-3 py-2 text-xs text-pine-700" aria-label="产物下载结果">
                {artifactNotice}
              </p>
            ) : null}
            <div className="mt-3 flex items-center gap-2 text-xs">
              <span className="text-slate-500">排序</span>
              <button
                aria-pressed={deliverySort === "priority"}
                className={deliverySort === "priority" ? "button-primary h-7 text-xs" : "button-secondary h-7 text-xs"}
                onClick={() => setDeliverySort("priority")}
                type="button"
              >
                按就绪度
              </button>
              <button
                aria-pressed={deliverySort === "id"}
                className={deliverySort === "id" ? "button-primary h-7 text-xs" : "button-secondary h-7 text-xs"}
                onClick={() => setDeliverySort("id")}
                type="button"
              >
                按需求编号
              </button>
              <span className="text-slate-400">按就绪度时，需要动手的（有改动、无快照）排在前面</span>
            </div>
            <div className="mt-3 overflow-x-auto">
              <table className="w-full min-w-[1560px] text-left text-xs">
                <thead className="text-slate-500">
                  <tr>
                    <th className="w-8 py-1 pr-2 font-medium">选</th>
                    <th className="py-1 pr-3 font-medium">监管表</th>
                    <th className="py-1 pr-3 font-medium">需求</th>
                    <th className="py-1 pr-3 font-medium">字段</th>
                    <th className="py-1 pr-3 font-medium">脚本覆盖</th>
                    <th className="py-1 pr-3 font-medium">脚本依据</th>
                    <th className="py-1 pr-3 font-medium">冻结状态</th>
                    <th className="py-1 pr-3 font-medium">交付就绪</th>
                    <th className="py-1 pr-3 font-medium">快照</th>
                    <th className="py-1 pr-3 font-medium">待采纳</th>
                          <th className="py-1 pr-3 font-medium">打开缺口</th>
                    <th className="py-1 pr-3 font-medium">正式交付</th>
                    <th className="py-1 pr-3 font-medium">最近动作</th>
                    <th className="py-1 font-medium">最近导出</th>
                  </tr>
                </thead>
                <tbody>
                  {!visibleDeliveryItems.length ? (
                    <tr className="border-t border-line">
                      <td className="py-3 text-xs text-slate-500" colSpan={14}>
                        当前筛选没有需求（共 {delivery.items.length} 条）。换一个就绪状态，或点“全部需求”看看。
                      </td>
                    </tr>
                  ) : null}
                  {sortDeliveryItems(visibleDeliveryItems, deliverySort).map((item) => {
                    const state = deliveryState(item);
                    const readiness = deliveryReadiness(item);
                    return (
                      <tr className="border-t border-line align-top" key={item.requirement_id}>
                        <td className="py-2 pr-2 align-top">
                          <input
                            aria-label={`选择需求 ${item.name}`}
                            checked={selected.includes(item.requirement_id)}
                            className="mt-0.5"
                            onChange={() => toggleSelected(item.requirement_id)}
                            type="checkbox"
                          />
                        </td>
                        <td className="py-2 pr-3 font-medium text-ink">{item.target_table_code || "-"}</td>
                        <td className="py-2 pr-3 whitespace-nowrap text-slate-600">
                          <div>{item.name}</div>
                          <div className="text-[11px] text-slate-400">内容 v{item.content_version}</div>
                        </td>
                        <td className="py-2 pr-3 tabular-nums text-slate-600">{item.field_count}</td>
                        <td className="py-2 pr-3 whitespace-nowrap text-slate-600">
                          {item.script_binding ? (
                            <button
                              aria-label={`查看脚本未覆盖字段 ${item.target_table_code || item.name}`}
                              className="underline decoration-dotted underline-offset-2 hover:text-ink"
                              onClick={() => setScriptBindingFor(item)}
                              type="button"
                            >
                              {scriptBindingText(item)}
                            </button>
                          ) : (
                            <span className="text-[11px] text-slate-400">{scriptBindingText(item)}</span>
                          )}
                          <button
                            aria-label={`字段覆盖核对 ${item.target_table_code || item.name}`}
                            className="ml-2 text-[11px] text-slate-500 underline decoration-dotted underline-offset-2 hover:text-ink"
                            onClick={() => void openFieldCoverage(item)}
                            type="button"
                          >
                            字段覆盖
                          </button>
                        </td>
                        <td className="py-2 pr-3 text-slate-600">
                          {(() => {
                            const itemFreshness = freshness?.items.find((row) => row.requirement_id === item.requirement_id) || null;
                            const itemState = freshnessStateOf(itemFreshness);
                            if (!itemFreshness || !itemState) return <span className="text-[11px] text-slate-400">不适用（没有冻结脚本依据）</span>;
                            if (itemState === "aligned") {
                              return <span className="text-[11px] text-slate-400">{freshnessText(itemFreshness)}</span>;
                            }
                            return (
                              <button
                                aria-label={`查看脚本依据 ${item.target_table_code || item.name}`}
                                className="underline decoration-dotted underline-offset-2 hover:text-ink"
                                onClick={() => void openFreshness(itemFreshness)}
                                type="button"
                              >
                                <span className={`badge ${FRESHNESS_BADGE[itemState]}`}>{FRESHNESS_LABELS[itemState]}</span>
                                <span className="ml-1 text-[11px] text-slate-500">{freshnessText(itemFreshness)}</span>
                              </button>
                            );
                          })()}
                        </td>
                        <td className="py-2 pr-3">
                          <span className={`badge ${DELIVERY_STATE_BADGE[state]}`}>{DELIVERY_STATE_LABELS[state]}</span>
                          <div className="mt-1 text-[11px] text-slate-400">{deliveryDetail(item)}</div>
                        </td>
                        <td className="py-2 pr-3">
                          <span className={`badge ${READINESS_BADGE[readiness]}`}>{READINESS_LABELS[readiness]}</span>
                          {item.latest_attestation ? (
                            <div
                              aria-label={`人工核对登记 ${item.requirement_id}`}
                              className="mt-1 text-[11px] text-slate-500"
                              data-attestation-conclusion={item.latest_attestation.conclusion}
                              data-attestation-on-latest={item.latest_attestation.on_latest_artifact ? "1" : "0"}
                            >
                              {deliveryAttestationText(item)}
                            </div>
                          ) : null}
                        </td>
                        <td className="py-2 pr-3 tabular-nums text-slate-600">{item.snapshot_count}</td>
                        <td className="py-2 pr-3 text-slate-600">
                          {(item.pending_candidate_count ?? 0) > 0 ? (
                            <Link
                              aria-label={`去工作台采纳 ${item.target_table_code || item.name} 的候选`}
                              className="underline decoration-dotted underline-offset-2 hover:text-ink"
                              href={`/workspace?projectId=${projectId}&tableId=${item.target_table_id ?? ""}&scenarioId=${item.scenario_id ?? ""}&requirementId=${item.requirement_id}&pendingCandidate=1`}
                            >
                              {pendingCandidateText(item)}
                            </Link>
                          ) : (
                            <span className="text-[11px] text-slate-400">{pendingCandidateText(item)}</span>
                          )}
                        </td>
                        <td className="py-2 pr-3 tabular-nums text-slate-600">
                          {item.open_gap_count ? (
                            <button
                              aria-label={`查看缺口摘要 ${item.target_table_code || item.name} #${item.requirement_id}`}
                              className="underline decoration-dotted underline-offset-2 hover:text-ink"
                              onClick={() => void openGapBreakdown(item)}
                              type="button"
                            >
                              {`${item.open_gap_field_count} 个字段 / ${item.open_gap_count} 条`}
                            </button>
                          ) : "无"}
                        </td>
                        <td className="py-2 pr-3 text-slate-600">{formalDeliveryText(item)}</td>
                        <td className="py-2 pr-3 text-slate-600">
                          <div className="max-w-[190px] truncate" title={deliveryActionText(item)}>{deliveryActionText(item)}</div>
                        </td>
                        <td className="py-2 text-slate-600">
                          <div>{deliveryArtifactText(item)}</div>
                          <div className="text-[11px] text-slate-400">共 {item.artifact_count} 个产物</div>
                          {item.last_artifact ? (
                            <button
                              aria-label={`下载最近导出产物 ${item.target_table_code || item.name}`}
                              className="button-secondary mt-1 px-2 py-0.5 text-[11px]"
                              disabled={downloadingId === item.requirement_id}
                              onClick={() => void downloadArtifact(item)}
                              type="button"
                            >
                              {downloadingId === item.requirement_id ? "下载中…" : `下载产物 #${item.last_artifact.id}`}
                            </button>
                          ) : null}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              {delivery.truncated ? (
                <p className="mt-2 text-[11px] text-slate-500">需求数量超过单次聚合上限，这里只展示前 {delivery.items.length} 条。</p>
              ) : null}
            </div>
            </>
          ) : null}
          {scriptBindingFor ? (
            <div
              aria-label="脚本未覆盖字段"
              className="fixed inset-0 z-40 flex items-center justify-center bg-ink/30 p-4"
              role="dialog"
            >
              <div className="max-h-[80vh] w-full max-w-2xl overflow-auto rounded-xl bg-white p-5 shadow-xl">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <h3 className="text-sm font-semibold text-ink">
                      {scriptBindingFor.target_table_code || scriptBindingFor.name} 的脚本覆盖
                    </h3>
                    <p className="mt-1 text-xs text-slate-500">
                      共 {scriptBindingFor.script_binding?.table_field_count ?? 0} 个监管字段，脚本绑定了
                      {" "}{scriptBindingFor.script_binding?.bound_field_count ?? 0} 个，
                      未覆盖 {scriptBindingFor.script_binding?.unbound_count ?? 0} 个。未覆盖不是"不需要"：
                      它们可能是系统字段（可由平台补），也可能是脚本确实不产出的监管字段（需要补脚本或人工给口径）。
                    </p>
                  </div>
                  <button className="button-secondary h-7 text-xs" onClick={() => setScriptBindingFor(null)} type="button">
                    关闭
                  </button>
                </div>
                {scriptBindingFor.script_binding?.unbound.length ? (
                  <ul className="mt-3 space-y-1 text-xs text-slate-700">
                    {scriptBindingFor.script_binding.unbound.map((field) => (
                      <li className="border-b border-line/60 pb-1" key={field.field_id}>
                        {scriptBindingUnboundLabel(field)}
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="mt-3 text-xs text-slate-500">这张表的字段都被脚本覆盖了。</p>
                )}
                {scriptBindingFor.script_binding && scriptBindingFor.script_binding.unbound_count > scriptBindingFor.script_binding.unbound.length ? (
                  <p className="mt-2 text-[11px] text-slate-400">
                    只列出前 {scriptBindingFor.script_binding.unbound.length} 个，其余
                    {" "}{scriptBindingFor.script_binding.unbound_count - scriptBindingFor.script_binding.unbound.length} 个未展示。
                  </p>
                ) : null}
              </div>
            </div>
          ) : null}
          {fieldCoverageTarget ? (
            <div
              aria-label="字段覆盖核对"
              className="fixed inset-0 z-40 flex items-center justify-center bg-ink/30 p-4"
              role="dialog"
            >
              <div className="max-h-[80vh] w-full max-w-2xl overflow-auto rounded-xl bg-white p-5 shadow-xl">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <h3 className="text-sm font-semibold text-ink">
                      {fieldCoverageTarget.target_table_code || fieldCoverageTarget.name} 的字段覆盖
                    </h3>
                    <p className="mt-1 text-xs text-slate-500">
                      {fieldCoverageBusy
                        ? "读取中…"
                        : fieldCoveragePayload
                          ? fieldCoverageHeadline(fieldCoveragePayload)
                          : "覆盖数据读取中。"}
                    </p>
                  </div>
                  <button className="button-secondary h-7 text-xs" onClick={closeFieldCoverage} type="button">
                    关闭
                  </button>
                </div>
                {fieldCoverageError ? <p className="mt-3 text-xs text-coral-700">{fieldCoverageError}</p> : null}
                {fieldCoveragePayload ? (
                  <>
                    <div className="mt-3 space-y-3">
                      {FIELD_COVERAGE_BUCKETS.map((bucket) => {
                        const total = fieldCoveragePayload.counts.buckets[bucket] ?? 0;
                        const rows = fieldCoveragePayload.uncovered.filter((row) => row.bucket === bucket);
                        return (
                          <section
                            aria-label={`字段覆盖分类 ${bucket}`}
                            data-coverage-bucket={bucket}
                            key={bucket}
                          >
                            <p className="text-xs font-semibold text-ink">
                              {fieldCoverageBucketText(fieldCoveragePayload, bucket)}
                            </p>
                            <p className="mt-1 text-[11px] text-slate-500">
                              {fieldCoveragePayload.bucket_hints[bucket]}
                            </p>
                            <ul className="mt-1 space-y-1 text-xs text-slate-700">
                              {rows.map((row) => (
                                <li
                                  className="border-b border-line/60 pb-1"
                                  data-coverage-row={row.field_code}
                                  key={row.field_id}
                                >
                                  {fieldCoverageRowText(row)}
                                </li>
                              ))}
                              {rows.length === 0 ? (
                                <li className="text-slate-400">这一类没有。</li>
                              ) : null}
                            </ul>
                            {rows.length < total ? (
                              <p className="mt-1 text-[11px] text-slate-400">
                                {`样例里列了 ${rows.length} 个，这一类共 ${total} 个。`}
                              </p>
                            ) : null}
                          </section>
                        );
                      })}
                    </div>
                    {fieldCoverageOutsideScopeText(fieldCoveragePayload) ? (
                      <p className="mt-3 text-[11px] text-amber-700">
                        {fieldCoverageOutsideScopeText(fieldCoveragePayload)}
                      </p>
                    ) : null}
                    <p className="mt-3 text-[11px] text-slate-400">{FIELD_COVERAGE_DISCLAIMER}</p>
                    <p className="mt-1 text-[11px] text-slate-400">{fieldCoveragePayload.note}</p>
                  </>
                ) : null}
              </div>
            </div>
          ) : null}
          {freshnessFor ? (
            <div
              aria-label="脚本依据"
              className="fixed inset-0 z-40 flex items-center justify-center bg-ink/30 p-4"
              role="dialog"
            >
              <div className="max-h-[80vh] w-full max-w-2xl overflow-auto rounded-xl bg-white p-5 shadow-xl">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <h3 className="text-sm font-semibold text-ink">
                      {freshnessFor.target_table_code || freshnessFor.name} 的脚本依据
                    </h3>
                    <p className="mt-1 text-xs text-slate-500">
                      冻结了 {freshnessFor.frozen_version_count} 个脚本版本，其中
                      {" "}{freshnessFor.versions.filter((version) => version.state !== "aligned").length} 个已落后。
                    </p>
                  </div>
                  <button className="button-secondary h-7 text-xs" onClick={() => setFreshnessFor(null)} type="button">
                    关闭
                  </button>
                </div>
                <ul className="mt-3 space-y-1 text-xs text-slate-700">
                  {freshnessFor.versions.map((version) => (
                    <li className="border-b border-line/60 pb-2" key={version.version_id}>
                      <div>{freshnessVersionText(version)}</div>
                      {version.decision ? (
                        <div className="mt-1 flex flex-wrap items-center gap-2 text-[11px]">
                          <span className={`badge ${DECISION_BADGE[version.decision.decision] || "badge-neutral"}`}>
                            {version.decision.decision_label || version.decision.decision}
                          </span>
                          <span className="text-slate-600">{decisionText(version.decision)}</span>
                        </div>
                      ) : null}
                      {version.state !== "aligned" ? (
                        <div className="mt-1 space-y-1">
                          <input
                            aria-label={`处置说明 ${version.file_name || version.script_file_id}`}
                            className="w-full rounded border border-line px-2 py-1 text-[11px]"
                            onChange={(event) =>
                              setDecisionNotes((current) => ({ ...current, [version.version_id]: event.target.value }))
                            }
                            placeholder="复核依据（暂不跟随 / 需回退 必须填写）"
                            value={decisionNotes[version.version_id] || ""}
                          />
                          <div className="flex flex-wrap gap-2">
                            {SCRIPT_BASIS_DECISION_CHOICES.map((choice) => (
                              <button
                                aria-label={`${choice.label} ${version.file_name || version.script_file_id}`}
                                className="rounded border border-line px-2 py-1 text-[11px] hover:bg-slate-50 disabled:opacity-50"
                                disabled={decisionBusy}
                                key={choice.key}
                                onClick={() => void recordDecision(version, choice.key, choice.requiresNote)}
                                title={choice.hint}
                                type="button"
                              >
                                {choice.label}
                              </button>
                            ))}
                          </div>
                        </div>
                      ) : null}
                    </li>
                  ))}
                </ul>
                <div className="mt-3 rounded-lg border border-line/70 bg-slate-50/60 p-3">
                  <div className="text-[11px] font-medium text-slate-500">这次脚本更新改了哪些目标字段</div>
                  {scriptDiffBusy ? (
                    <p className="mt-1 text-xs text-slate-500">正在比较脚本版本…</p>
                  ) : null}
                  {scriptDiffError ? (
                    <p className="mt-1 text-xs text-coral-700">{scriptDiffError}</p>
                  ) : null}
                  {!scriptDiffBusy && !scriptDiffError && scriptDiff ? (
                    <div className="mt-1 space-y-2">
                      {freshnessFor.versions.map((version) => {
                        const diff = scriptDiff.items.find((item) => item.script_file_id === version.script_file_id);
                        if (!diff) return null;
                        return (
                          <div key={`diff-${version.version_id}`}>
                            <div className="text-xs text-slate-700">
                              {diff.file_name || `脚本 #${diff.script_file_id}`}：{scriptDiffText(diff)}
                            </div>
                            {diff.impact ? (
                              <div className="mt-1 flex flex-wrap items-center gap-2 text-[11px]">
                                <span className={`badge ${IMPACT_BADGE[diff.impact.recommendation] || "badge-neutral"}`}>
                                  {impactText(diff.impact)}
                                </span>
                                <span className="text-slate-600">{diff.impact.reason}</span>
                              </div>
                            ) : null}
                            {diff.impact ? (
                              <div className="mt-1 text-[11px] text-slate-500">
                                受影响绑定字段 {diff.impact.affected_field_count} / {diff.impact.bound_field_count}
                                {affectedFieldTexts(diff.impact).length
                                  ? `：${affectedFieldTexts(diff.impact).join("；")}`
                                  : "（这次更新没有触及本需求绑定的字段）"}
                              </div>
                            ) : null}
                            {(diff.changed || []).slice(0, 3).map((entry) => (
                              <div className="mt-1 text-[11px] text-slate-500" key={`${diff.script_file_id}-${entry.label}`}>
                                · {scriptDiffEntryText(entry)}
                              </div>
                            ))}
                            {(diff.changed?.length || 0) > 3 ? (
                              <div className="mt-1 text-[11px] text-slate-400">
                                …另有 {(diff.changed?.length || 0) - 3} 个字段有变更（完整差异见脚本血缘）
                              </div>
                            ) : null}
                          </div>
                        );
                      })}
                    </div>
                  ) : null}
                </div>
                {decisionError ? <p className="mt-1 text-[11px] text-coral-700">{decisionError}</p> : null}
                {decisionNotice ? (
                  <p aria-label="复核决定结果" className="mt-1 text-[11px] text-pine-700">
                    {decisionNotice}
                  </p>
                ) : null}
                <p className="mt-3 text-[11px] text-slate-500">{FRESHNESS_NOTE}</p>
              </div>
            </div>
          ) : null}
        </section>

        {manifestOpen ? (
          <div className="fixed inset-0 z-40 flex items-start justify-center overflow-auto bg-ink/40 p-4">
            <div className="panel my-8 w-full max-w-5xl p-5" aria-label="交付复核清单">
              <div className="flex flex-wrap items-baseline justify-between gap-3">
                <div>
                  <h2 className="text-sm font-semibold text-ink">交付复核清单</h2>
                  <p className="mt-1 text-xs text-slate-500">
                    按状态、渲染器版本、需求、关键字查：哪些产物还能用当前代码复核，哪些只能靠当时的渲染器或模板。
                    清单只读元数据，不做重放——真要逐份比字节，用「稳定性核对」。
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  {manifestBusy ? <span className="text-xs text-slate-500">加载中…</span> : null}
                  <button
                    aria-label="关闭复核清单"
                    className="button-secondary h-7 text-[11px]"
                    onClick={closeManifest}
                    type="button"
                  >
                    关闭
                  </button>
                </div>
              </div>
              <div className="mt-3 flex flex-wrap items-center gap-2" aria-label="复核清单筛选">
                <button
                  aria-label="复核状态全部"
                  aria-pressed={manifestState === ""}
                  className={manifestState === "" ? "button-primary h-7 text-[11px]" : "button-secondary h-7 text-[11px]"}
                  onClick={() => {
                    setManifestState("");
                    void loadManifest("", manifestKeyword);
                  }}
                  type="button"
                >
                  全部状态
                </button>
                {REPLAY_MANIFEST_STATES.map((option) => (
                  <button
                    aria-label={`复核状态 ${option.label}`}
                    aria-pressed={manifestState === option.value}
                    className={
                      manifestState === option.value ? "button-primary h-7 text-[11px]" : "button-secondary h-7 text-[11px]"
                    }
                    key={option.value}
                    onClick={() => {
                      setManifestState(option.value);
                      void loadManifest(option.value, manifestKeyword);
                    }}
                    type="button"
                  >
                    {option.label}
                    {manifestPayload ? ` ${manifestPayload.summary[option.value]}` : ""}
                  </button>
                ))}
                <input
                  aria-label="复核清单关键字"
                  className="h-7 w-56 rounded border border-slate-300 px-2 text-[11px]"
                  onChange={(event) => setManifestKeyword(event.target.value)}
                  placeholder="表码 / 需求名 / 渲染器 / 产物号"
                  value={manifestKeyword}
                />
                <button
                  aria-label="按关键字查复核清单"
                  className="button-secondary h-7 text-[11px]"
                  disabled={manifestBusy}
                  onClick={() => void loadManifest(manifestState, manifestKeyword)}
                  type="button"
                >
                  查询
                </button>
              </div>
              {manifestError ? <p className="mt-3 text-xs text-red-600">{manifestError}</p> : null}
              {manifestPayload ? (
                <div className="mt-4 space-y-3">
                  <p className="text-sm font-medium text-ink" aria-label="复核清单结论">
                    {manifestHeadline(manifestPayload)}
                  </p>
                  <p className="text-xs text-slate-600" aria-label="复核清单筛选说明">
                    {manifestFilterText(manifestPayload)}
                  </p>
                  <div className="grid gap-2 text-[11px] text-slate-600 sm:grid-cols-2">
                    <div aria-label="复核清单渲染器分布">
                      <span className="font-medium text-ink">渲染器分布：</span>
                      {manifestPayload.facets.by_renderer.length
                        ? manifestPayload.facets.by_renderer
                            .slice(0, 6)
                            .map((facet) => manifestRendererFacetText(facet))
                            .join("；")
                        : "没有产物"}
                    </div>
                    <div aria-label="复核清单按表分布">
                      <span className="font-medium text-ink">按监管表：</span>
                      {manifestPayload.facets.by_table.length
                        ? manifestPayload.facets.by_table
                            .slice(0, 8)
                            .map((facet) => manifestTableFacetText(facet))
                            .join("；")
                        : "没有登记监管表"}
                    </div>
                  </div>
                  <div className="max-h-[420px] overflow-auto rounded border border-slate-200">
                    <table className="w-full min-w-[880px] text-left text-[11px]">
                      <thead className="sticky top-0 bg-slate-50 text-slate-500">
                        <tr>
                          <th className="whitespace-nowrap px-2 py-1">产物</th>
                          <th className="whitespace-nowrap px-2 py-1">需求 / 监管表</th>
                          <th className="whitespace-nowrap px-2 py-1">渲染器</th>
                          <th className="whitespace-nowrap px-2 py-1">复核状态</th>
                          <th className="whitespace-nowrap px-2 py-1">说明</th>
                        </tr>
                      </thead>
                      <tbody>
                        {manifestPayload.items.map((item: ReplayManifestItem) => (
                          <tr
                            className="border-t border-slate-100"
                            data-artifact-id={item.artifact_id}
                            data-replay-state={item.replay_state}
                            key={item.artifact_id}
                          >
                            <td className="whitespace-nowrap px-2 py-1">#{item.artifact_id} · {item.file_name}</td>
                            <td className="whitespace-nowrap px-2 py-1">{manifestItemText(item)}</td>
                            <td className="whitespace-nowrap px-2 py-1">{item.renderer_version || "未知"}</td>
                            <td className="whitespace-nowrap px-2 py-1">
                              <span
                                className={
                                  REPLAY_MANIFEST_TONE[item.replay_state] === "ok"
                                    ? "badge-neutral"
                                    : REPLAY_MANIFEST_TONE[item.replay_state] === "danger"
                                      ? "badge-danger"
                                      : "badge-warn"
                                }
                              >
                                {item.replay_state_label}
                              </span>
                            </td>
                            <td className="whitespace-nowrap px-2 py-1 text-slate-600">
                              {item.replay_state === "replayable"
                                ? "当前代码再渲一遍就是同一份"
                                : item.replay_reason_label || item.replay_reason || "—"}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  <p className="text-[11px] text-slate-500" aria-label="复核清单免责">
                    {REPLAY_MANIFEST_DISCLAIMER}
                  </p>
                </div>
              ) : null}
            </div>
          </div>
        ) : null}

        {stabilityOpen ? (
          <div className="fixed inset-0 z-40 flex items-start justify-center overflow-auto bg-ink/40 p-4">
            <div className="panel my-8 w-full max-w-4xl p-5" aria-label="交付稳定性核对">
              <div className="flex flex-wrap items-baseline justify-between gap-3">
                <div>
                  <h2 className="text-sm font-semibold text-ink">交付稳定性核对</h2>
                  <p className="mt-1 text-xs text-slate-500">
                    把已登记产物按同一份冻结内容重放一次，比对字节：对上了说明同一输入产出同一文件；
                    对不上要分清是冻结内容变了，还是渲染器改了没升版本。
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  {stabilityBusy ? <span className="text-xs text-slate-500">核对中…</span> : null}
                  <button
                    aria-label="关闭稳定性核对"
                    className="button-secondary h-7 text-[11px]"
                    onClick={closeStability}
                    type="button"
                  >
                    关闭
                  </button>
                </div>
              </div>
              {stabilityError ? (
                <p className="mt-3 text-xs text-red-600">{stabilityError}</p>
              ) : null}
              {stabilityPayload ? (
                <div className="mt-4 space-y-3">
                  <p className="text-sm font-medium text-ink" aria-label="稳定性核对结论">
                    {stabilityHeadline(stabilityPayload)}
                  </p>
                  <p className="text-xs text-slate-600" aria-label="稳定性核对判定">
                    {stabilityVerdictText(stabilityPayload)}
                  </p>
                  <div className="max-h-[420px] overflow-auto rounded border border-slate-200">
                    <table className="w-full min-w-[720px] text-left text-[11px]">
                      <thead className="bg-slate-50 text-slate-600">
                        <tr>
                          <th className="px-2 py-1">产物</th>
                          <th className="px-2 py-1">格式</th>
                          <th className="px-2 py-1">渲染器</th>
                          <th className="px-2 py-1">结论</th>
                          <th className="px-2 py-1">说明</th>
                        </tr>
                      </thead>
                      <tbody>
                        {stabilityPayload.items.map((item) => (
                          <tr
                            key={item.artifact_id}
                            data-artifact-id={item.artifact_id}
                            data-stability-status={item.status}
                            className="border-t border-slate-100 align-top"
                          >
                            <td className="whitespace-nowrap px-2 py-1">#{item.artifact_id}</td>
                            <td className="whitespace-nowrap px-2 py-1">{item.format}</td>
                            <td className="whitespace-nowrap px-2 py-1">{item.renderer_version}</td>
                            <td className="whitespace-nowrap px-2 py-1">
                              {stabilityPayload.status_labels[item.status] ?? item.status}
                            </td>
                            <td className="px-2 py-1">
                              {item.reason || stabilityItemText(item, stabilityPayload.status_labels)}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  <p className="text-[11px] text-slate-500" aria-label="稳定性核对免责">
                    {EXPORT_STABILITY_DISCLAIMER}
                  </p>
                  <p className="text-[11px] text-slate-500">{stabilityPayload.note}</p>
                </div>
              ) : null}
            </div>
          </div>
        ) : null}

        <section className="panel p-5" aria-label="交付审计">
          <div className="flex flex-wrap items-baseline justify-between gap-3">
            <div>
              <h2 className="text-sm font-semibold text-ink">交付审计</h2>
              <p className="mt-1 text-xs text-slate-500">
                按产物列出最近一次交付前检查：导出成功不等于交付前查过。这里只汇总已落库的检查记录，
                不重算、不改变交付状态。
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              {audit ? (
                <p className="text-xs text-slate-600" aria-label="交付审计结论">
                  {auditHeadline(audit.summary)}
                </p>
              ) : null}
              {audit ? (
                <p className="mt-1 text-xs text-slate-500" aria-label="交付复核风险">
                  {auditReplayText(audit.summary)}
                </p>
              ) : null}
              <button
                aria-label="交付稳定性核对"
                className="button-secondary h-7 text-[11px]"
                disabled={stabilityBusy}
                onClick={() => void openStability()}
                type="button"
              >
                {stabilityBusy ? "核对中…" : "稳定性核对"}
              </button>
              <button
                aria-label="打开复核清单"
                className="button-secondary h-7 text-[11px]"
                disabled={manifestBusy}
                onClick={() => void openManifest()}
                type="button"
              >
                {manifestBusy ? "加载中…" : "复核清单"}
              </button>

              {audit && auditPendingSupported(audit.summary) > 0 ? (
                <button
                  aria-label="批量验收未检查的产物"
                  className="button-secondary h-7 text-[11px]"
                  disabled={acceptanceBatchBusy}
                  onClick={() => void runAcceptanceBatch()}
                  type="button"
                >
                  {acceptanceBatchBusy
                    ? "批量验收中…"
                    : `批量验收未检查的产物（${auditPendingSupported(audit.summary)}）`}
                </button>
              ) : null}
              {audit && auditPendingSupported(audit.summary) === 0 && audit.summary.unchecked > 0 ? (
                <p className="text-[11px] text-slate-500" aria-label="批量验收不适用提示">
                  还剩 {audit.summary.unchecked} 个没检查的产物不支持自动验收（内置版式 / 客户模板），
                  需要人工核对后另行登记。
                </p>
              ) : null}
              {audit && auditManualPending(audit.summary) > 0 ? (
                <p className="text-[11px] text-slate-500" aria-label="人工核对待登记提示">
                  另有 {auditManualPending(audit.summary)} 个产物只能人工核对、还没有人登记：
                  点「登记人工核对」写清看过的依据，登记不算机器检查，也不会把交付状态改成通过。
                </p>
              ) : null}
            </div>
          </div>
          {auditError ? (
            <p className="mt-3 rounded-lg border border-coral-200 bg-coral-50 px-3 py-2 text-xs text-coral-700">{auditError}</p>
          ) : null}
          {!audit && !auditError ? <div className="mt-3 h-16 animate-pulse rounded bg-slate-50" /> : null}
          {audit ? (
            (() => {
              const filtered = filterAuditItems(audit.items, auditFilter);
              const visible = filtered.slice(0, auditLimit);
              return (
                <>
                  <div className="mt-3 flex flex-wrap items-center gap-2" aria-label="交付审计筛选">
                    {DELIVERY_AUDIT_FILTERS.map((option) => (
                      <button
                        key={option.key}
                        type="button"
                        className={auditFilter === option.key ? "button-primary h-7 text-[11px]" : "button-secondary h-7 text-[11px]"}
                        aria-pressed={auditFilter === option.key}
                        onClick={() => {
                          setAuditFilter(option.key);
                          setAuditLimit(12);
                        }}
                      >
                        {option.label} {auditFilterCount(audit.summary, option.key)}
                      </button>
                    ))}
                    <span className="text-[11px] text-slate-500">当前显示 {visible.length} / {filtered.length} 个产物</span>
                  </div>
                  {visible.length ? (
                    <div className="mt-3 overflow-x-auto">
                      <table className="w-full min-w-[900px] text-left text-xs">
                        <thead className="text-slate-500">
                          <tr>
                            <th className="py-1 pr-3 font-medium">产物</th>
                            <th className="py-1 pr-3 font-medium">需求</th>
                            <th className="py-1 pr-3 font-medium">最近检查</th>
                            <th className="py-1 pr-3 font-medium">人工核对</th>
                            <th className="py-1 pr-3 font-medium">文件</th>
                            <th className="py-1 pr-3 font-medium">验收</th>
                          </tr>
                        </thead>
                        <tbody>
                          {visible.map((item) => (
                            <tr key={item.artifact_id} className="border-t border-line">
                              <td className="py-2 pr-3">
                                <div className="font-mono text-[11px] text-slate-600">#{item.artifact_id}</div>
                                <div className="mt-1">
                                  <span className={AUDIT_STATE_BADGE[auditState(item)]}>{item.state_label}</span>
                                </div>
                              </td>
                              <td className="py-2 pr-3">
                                <div className="max-w-[220px] truncate" title={item.requirement_name ?? undefined}>
                                  {item.target_table_code ? `${item.target_table_code} · ` : ""}
                                  {item.requirement_name ?? `需求 #${item.requirement_id}`}
                                </div>
                              </td>
                              <td className="py-2 pr-3 text-slate-600">
                                <div className="max-w-[330px] truncate" title={auditCheckText(item)}>{auditCheckText(item)}</div>
                                <div className="mt-1 text-[11px] text-slate-400">产物生成于 {formatAuditTime(item.created_at)}</div>
                              </td>
                              <td className="py-2 pr-3 text-slate-600">
                                <div className="max-w-[300px] truncate" title={attestationText(item)}>
                                  {attestationText(item)}
                                </div>
                              </td>
                              <td className="py-2 pr-3">
                                <div className="max-w-[240px] truncate" title={item.file_name}>{item.file_name}</div>
                                <div className="mt-1 font-mono text-[11px] text-slate-400">{item.file_sha256.slice(0, 12)}… · {item.renderer_version}</div>
                                {item.replay && item.replay.state !== "replayable" ? (
                                  <div className="mt-1" data-replay-state={item.replay.state} title={replayItemText(item)}>
                                    <span className={REPLAY_BADGE[item.replay.state]}>
                                      {item.replay.state === "historical" ? "仅旧渲染器" : "不支持重放"}
                                    </span>
                                  </div>
                                ) : null}
                              </td>
                              <td className="py-2 pr-3">
                                <button
                                  aria-label={`一键验收产物 ${item.artifact_id}`}
                                  className="whitespace-nowrap text-indigo-700 underline disabled:opacity-50"
                                  disabled={acceptanceBusy === item.artifact_id}
                                  onClick={() => void runAcceptance(item)}
                                  type="button"
                                >
                                  {acceptanceBusy === item.artifact_id ? "验收中…" : "一键验收并存档"}
                                </button>
                                {item.acceptance_applicable === false ? (
                                  <button
                                    aria-label={`登记人工核对产物 ${item.artifact_id}`}
                                    className="ml-2 whitespace-nowrap text-slate-700 underline"
                                    onClick={() => openAttestation(item)}
                                    type="button"
                                  >
                                    登记人工核对
                                  </button>
                                ) : null}
                              </td>
                            </tr>
                          ))}
                          {attestTarget ? (
                            <tr className="border-t border-line bg-slate-50">
                              <td className="py-3 pr-3 text-[11px] text-slate-500" colSpan={6}>
                                <div className="flex flex-wrap items-center gap-2" aria-label="人工核对登记表单">
                                  <span className="font-medium text-slate-700">
                                    产物 #{attestTarget.artifact_id} · {attestTarget.renderer_version} 不支持自动验收，
                                  </span>
                                  <span>写清看过什么、依据在哪，事后要能据此复核。</span>
                                  <select
                                    aria-label="人工核对结论"
                                    className="h-7 rounded border border-line px-2 text-[11px]"
                                    onChange={(event) =>
                                      setAttestConclusion(event.target.value === "rejected" ? "rejected" : "confirmed")
                                    }
                                    value={attestConclusion}
                                  >
                                    {ATTESTATION_CONCLUSIONS.map((option) => (
                                      <option key={option.key} value={option.key}>
                                        {option.label}
                                      </option>
                                    ))}
                                  </select>
                                  <input
                                    aria-label="人工核对依据"
                                    className="h-7 min-w-[260px] flex-1 rounded border border-line px-2 text-[11px]"
                                    onChange={(event) => setAttestBasis(event.target.value)}
                                    placeholder="例：按客户模板逐列核对字段名、口径、示例值，均一致"
                                    value={attestBasis}
                                  />
                                  <button
                                    aria-label="保存人工核对登记"
                                    className="button-primary h-7 text-[11px]"
                                    disabled={attestBusy || attestBasis.trim().length < 4}
                                    onClick={() => void runAttestation()}
                                    type="button"
                                  >
                                    {attestBusy ? "登记中…" : "保存登记"}
                                  </button>
                                  <button
                                    aria-label="取消人工核对登记"
                                    className="button-secondary h-7 text-[11px]"
                                    onClick={() => {
                                      setAttestTarget(null);
                                      setAttestError("");
                                    }}
                                    type="button"
                                  >
                                    取消
                                  </button>
                                </div>
                                <p className="mt-1 text-[11px] text-slate-500">
                                  登记不改交付状态、不关闭缺口、不写检查记录；依据少于 4 个字或只写「已看」会被拒绝。
                                </p>
                                {attestError ? (
                                  <p aria-label="人工核对登记失败" className="mt-1 text-[11px] text-coral-700">
                                    {attestError}
                                  </p>
                                ) : null}
                              </td>
                            </tr>
                          ) : null}
                        </tbody>
                      </table>
                    </div>
                  ) : (
                    <p className="mt-3 rounded-lg bg-slate-50 px-3 py-2 text-xs text-slate-600">
                      当前筛选没有产物（共 {filtered.length} 个）。换一个检查状态，或点「全部产物」看看。
                    </p>
                  )}
                  {acceptanceResult ? (
                    <div
                      aria-label="一键验收结果"
                      data-kind={acceptanceResult.kind}
                      className={
                        acceptanceResult.kind === "pass"
                          ? "mt-3 flex items-start justify-between gap-3 rounded-lg border border-pine-200 bg-pine-50 px-3 py-2 text-xs text-pine-800"
                          : "mt-3 flex items-start justify-between gap-3 rounded-lg border border-coral-200 bg-coral-50 px-3 py-2 text-xs text-coral-700"
                      }
                    >
                      <span>{describeAcceptanceNotice(acceptanceResult)}</span>
                      <button
                        aria-label="关闭一键验收结果"
                        className="shrink-0 underline"
                        onClick={() => clearAcceptanceNotice()}
                        type="button"
                      >
                        关闭
                      </button>
                    </div>
                  ) : null}
                  {filtered.length > visible.length ? (
                    <div className="mt-3 flex justify-end">
                      <button className="button-secondary h-6 text-[11px]" onClick={() => setAuditLimit((current) => current + 24)} type="button">
                        再显示 24 个
                      </button>
                    </div>
                  ) : null}
                </>
              );
            })()
          ) : null}
        </section>
        <section className="panel p-5" aria-label="监管表覆盖度">
          <div className="flex flex-wrap items-baseline justify-between gap-3">
            <div>
              <h2 className="text-sm font-semibold text-ink">监管表覆盖度</h2>
              <p className="mt-1 text-xs text-slate-500">
                需求维与脚本维分开陈述：有脚本但解析不出写入（例如脚本被整段注释屏蔽）不等于"需求没做"，
                需要人工确认是否已停用；输入里没有脚本的表要补资料，而不是去调解析器。
              </p>
            </div>
            {coverage ? (
              <p className="text-xs text-slate-600">{coverageHeadline(coverage.summary)}</p>
            ) : null}
          </div>
          {coverageError ? (
            <p className="mt-3 rounded-lg border border-coral-200 bg-coral-50 px-3 py-2 text-xs text-coral-700">{coverageError}</p>
          ) : null}
          {!coverage && !coverageError ? (
            <div className="mt-3 h-20 animate-pulse rounded bg-slate-50" />
          ) : null}
          {coverage ? (
            <>
              <div className="mt-3 flex flex-wrap items-center gap-2 text-xs">
                {COVERAGE_FILTERS.map((filter) => (
                  <button
                    aria-pressed={coverageFilter === filter.key}
                    className={coverageFilter === filter.key ? "button-primary h-7 text-xs" : "button-secondary h-7 text-xs"}
                    key={filter.key}
                    onClick={() => {
                      setCoverageFilter(filter.key);
                      setCoverageLimit(15);
                    }}
                    type="button"
                  >
                    {filter.label} {coverageFilterCount(coverage.summary, filter.key)}
                  </button>
                ))}
              </div>
              {(() => {
                const visible = filterCoverage(coverage.items, coverageFilter);
                const authorableVisible = visible
                  .filter((item) => item.state === "script_ready" && !item.requirement_count)
                  .map((item) => item.table_code);
                if (!authorableVisible.length) return null;
                const allSelected = authorableVisible.every((code) => authorSelected.includes(code));
                return (
                  <div className="mt-2 flex flex-wrap items-center gap-3 text-xs" aria-label="批量建需">
                    <button
                      className="button-secondary h-7 text-xs"
                      onClick={() =>
                        setAuthorSelected(allSelected ? [] : Array.from(new Set([...authorSelected, ...authorableVisible])).slice(0, 10))
                      }
                      type="button"
                    >
                      {allSelected ? "取消全选" : `全选可建需表（${authorableVisible.length}）`}
                    </button>
                    <button
                      className="button-primary h-7 text-xs"
                      disabled={!authorSelected.length || authorBatchBusy}
                      onClick={() => void authorBatch()}
                      type="button"
                    >
                      {authorBatchBusy ? "建需中…" : `批量建需（${authorSelected.length}）`}
                    </button>
                    <span className="text-[11px] text-slate-500">
                      一次最多 10 张表；只绑"脚本输出列与监管字段同名"的字段，未绑字段留作缺口。
                    </span>
                  </div>
                );
              })()}
              {authorResults ? (
                <ul className="mt-2 space-y-1 text-[11px]" aria-label="批量建需结果">
                  {authorResults.map((item) => (
                    <li className="text-slate-600" key={item.table_code}>
                      {item.table_code}：
                      {item.created
                        ? `已建需求 #${item.requirement_id}（内容 v${item.content_version}，绑定 ${item.bound_field_count ?? 0} 个字段）`
                        : `未建（${item.reason || "原因未返回"}）`}
                    </li>
                  ))}
                </ul>
              ) : null}
              {(() => {
                const visible = filterCoverage(coverage.items, coverageFilter);
                if (!visible.length) {
                  return (
                    <p className="mt-3 text-xs text-slate-500">
                      当前条件下没有监管表。换一个筛选条件，或点"全部监管表"查看 {coverage.summary.table_count} 张。
                    </p>
                  );
                }
                return (
                  <>
                    <div className="mt-3 overflow-x-auto">
                      <table className="w-full min-w-[760px] text-left text-xs">
                        <thead className="text-slate-500">
                          <tr>
                            <th className="py-1 pr-3 font-medium">选</th>
                            <th className="py-1 pr-3 font-medium">监管表</th>
                            <th className="py-1 pr-3 font-medium">名称</th>
                            <th className="py-1 pr-3 font-medium">字段 / 已绑映射</th>
                            <th className="py-1 pr-3 font-medium">写入脚本</th>
                            <th className="py-1 pr-3 font-medium">需求</th>
                            <th className="py-1 font-medium">覆盖状态</th>
                            <th className="py-1 pl-3 font-medium">操作</th>
                          </tr>
                        </thead>
                        <tbody>
                          {visible.slice(0, coverageLimit).map((item) => (
                            <tr className="border-t border-line align-top" key={item.table_id}>
                              <td className="py-2 pr-3">
                                {item.state === "script_ready" && !item.requirement_count ? (
                                  <input
                                    aria-label={`选择监管表 ${item.table_code} 批量建需`}
                                    checked={authorSelected.includes(item.table_code)}
                                    className="mt-0.5"
                                    onChange={() =>
                                      setAuthorSelected((current) =>
                                        current.includes(item.table_code)
                                          ? current.filter((code) => code !== item.table_code)
                                          : [...current, item.table_code].slice(0, 10),
                                      )
                                    }
                                    type="checkbox"
                                  />
                                ) : (
                                  <span className="text-[11px] text-slate-300">—</span>
                                )}
                              </td>
                              <td className="py-2 pr-3 font-medium text-ink">{item.table_code}</td>
                              <td className="py-2 pr-3 text-slate-600">{item.table_name}</td>
                              <td className="py-2 pr-3 tabular-nums text-slate-600">
                                {item.field_count} / {item.mapped_field_count}
                              </td>
                              <td className="py-2 pr-3 tabular-nums text-slate-600">{item.script_version_count} 个版本</td>
                              <td className="py-2 pr-3 text-slate-600">
                                {item.requirement_count ? `${item.requirement_count} 条（冻结 ${item.frozen_requirement_count}）` : "无"}
                              </td>
                              <td className="py-2">
                                <span className={`badge ${COVERAGE_BADGE[item.state]}`}>{COVERAGE_LABELS[item.state] || item.state_label}</span>
                                <div className="mt-1 text-[11px] text-slate-400">{coverageDetail(item)}</div>
                                {item.script_reason ? (
                                  <div className="mt-1 max-w-[380px] text-[11px] leading-snug text-coral-600">
                                    {item.script_reason}
                                  </div>
                                ) : null}
                              </td>
                              <td className="py-2 pl-3">
                                {item.state === "script_ready" && !item.requirement_count ? (
                                  <button
                                    type="button"
                                    className="button-secondary h-7 text-xs"
                                    disabled={Boolean(authoringCode)}
                                    aria-label={`从脚本为 ${item.table_code} 建需`}
                                    onClick={() => void authorFromScript(item)}
                                  >
                                    {authoringCode === item.table_code ? "建需中…" : "从脚本建需"}
                                  </button>
                                ) : (
                                  <span className="text-[11px] text-slate-400">—</span>
                                )}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                    {authorNotice ? (
                      <p className="mt-2 text-xs text-emerald-700" aria-label="脚本建需结果">{authorNotice}</p>
                    ) : null}
                    {authorError ? (
                      <p className="mt-2 text-xs text-coral-600" role="alert" aria-label="脚本建需失败">{authorError}</p>
                    ) : null}
                    <div className="mt-2 flex items-center gap-3 text-[11px] text-slate-500">
                      <span>
                        当前显示 {Math.min(visible.length, coverageLimit)} / {visible.length} 张
                      </span>
                      {visible.length > coverageLimit ? (
                        <button
                          className="button-secondary h-6 text-[11px]"
                          onClick={() => setCoverageLimit((current) => current + 30)}
                          type="button"
                        >
                          再显示 30 张
                        </button>
                      ) : null}
                    </div>
                  </>
                );
              })()}
            </>
          ) : null}
        </section>
        <section className="panel p-5" aria-label="标准模板列填充">
          <div className="flex flex-wrap items-baseline justify-between gap-3">
            <div>
              <h2 className="text-sm font-semibold text-ink">标准模板列填充</h2>
              <p className="mt-1 text-xs text-slate-500">
                导出文档里的空列分三种：模板本身没给数据（要找业务）、集市或脚本缺（要补资料）、
                需求侧还没写（待业务确认）。这里按列统计并把缺口归属标出来，不把"模板没给"算成平台缺陷。
              </p>
            </div>
            {templateCoverage ? (
              <p className="text-xs text-slate-600">{templateCoverageHeadline(templateCoverage)}</p>
            ) : null}
          </div>
          {templateCoverageError ? (
            <p className="mt-3 rounded-lg border border-coral-200 bg-coral-50 px-3 py-2 text-xs text-coral-700">{templateCoverageError}</p>
          ) : null}
          {!templateCoverage && !templateCoverageError ? (
            <div className="mt-3 h-16 animate-pulse rounded bg-slate-50" />
          ) : null}
          {templateCoverage ? (
            <>
              <div className="mt-3 overflow-x-auto">
                <table className="w-full min-w-[680px] text-left text-xs">
                  <thead className="text-slate-500">
                    <tr>
                      <th className="py-1 pr-3 font-medium">模板列</th>
                      <th className="py-1 pr-3 font-medium">已填 / 字段总数</th>
                      <th className="py-1 pr-3 font-medium">缺口</th>
                      <th className="py-1 pr-3 font-medium">填充率</th>
                      <th className="py-1 font-medium">缺口归属</th>
                    </tr>
                  </thead>
                  <tbody>
                    {templateCoverage.columns.map((column) => {
                      const state = templateColumnState(column);
                      return (
                        <tr className="border-t border-line align-top" key={column.key}>
                          <td className="py-2 pr-3 font-medium text-ink">
                            <button
                              aria-label={`查看缺口清单 ${column.label}`}
                              className="text-left underline decoration-dotted underline-offset-2 hover:text-pine-700"
                              onClick={() => void openGapPanel(column.key)}
                              type="button"
                            >
                              {column.label}
                            </button>
                          </td>
                          <td className="py-2 pr-3 tabular-nums text-slate-600">
                            {column.filled} / {templateCoverage.field_count}
                          </td>
                          <td className={state === "full" ? "py-2 pr-3 tabular-nums text-slate-400" : "py-2 pr-3 tabular-nums text-coral-600"}>
                            {column.missing}
                          </td>
                          <td className="py-2 pr-3 tabular-nums text-slate-600">{fillPercent(column)}</td>
                          <td className="py-2">
                            <span className={`badge ${TEMPLATE_SOURCE_BADGE[column.source]}`}>
                              {TEMPLATE_SOURCE_SHORT[column.source]}
                            </span>
                            <div className="mt-1 max-w-[340px] text-[11px] leading-snug text-slate-500">{column.source_label}</div>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
              <p className="mt-2 text-[11px] text-slate-500">{templateCoverage.note}</p>
            </>
          ) : null}
        </section>
        {gapBreakdownFor ? (
          <div className="fixed inset-0 z-40 flex items-start justify-center bg-ink/40 p-6" role="presentation">
            <div
              aria-label="缺口摘要"
              className="max-h-[86vh] w-full max-w-3xl overflow-hidden rounded-xl bg-white shadow-xl"
              role="dialog"
            >
              <div className="flex flex-wrap items-start justify-between gap-3 border-b border-line px-5 py-3">
                <div>
                  <h2 className="text-sm font-semibold text-ink">
                    缺口摘要：{gapBreakdownFor.target_table_code || gapBreakdownFor.name}
                  </h2>
                  <p className="mt-1 text-xs text-slate-500">
                    {gapBreakdown
                      ? gapBreakdownHeadline(gapBreakdown)
                      : gapBreakdownError || "正在读取缺口摘要…"}
                  </p>
                </div>
                <button
                  className="btn-ghost"
                  onClick={() => {
                    setGapBreakdownFor(null);
                    setGapBreakdown(null);
                    setGapBreakdownError("");
                  }}
                  type="button"
                >
                  关闭
                </button>
              </div>
              {gapBreakdown ? (
                <div className="max-h-[70vh] overflow-auto px-5 py-3 text-xs">
                  <table className="min-w-full text-left">
                    <thead>
                      <tr className="text-[11px] text-slate-500">
                        <th className="py-1 pr-3 font-medium">字段</th>
                        <th className="py-1 pr-3 font-medium">缺口条数</th>
                        <th className="py-1 pr-3 font-medium">处理</th>
                      </tr>
                    </thead>
                    <tbody>
                      {gapBreakdown.fields.map((field) => {
                        // 看板只能拿到 requirement_id；工作台是按 tableId + scenarioId + requirementId
                        // 还原同一条需求的，所以深链要把这三项一起带上，否则打开的是"另一条需求"。
                        const canDeepLink = Boolean(
                          field.field_id && gapBreakdown.target_table_id && gapBreakdown.scenario_id,
                        );
                        const href = canDeepLink
                          ? `/workspace?projectId=${projectId}&tableId=${gapBreakdown.target_table_id}&scenarioId=${gapBreakdown.scenario_id}&requirementId=${gapBreakdown.requirement_id}&fieldId=${field.field_id}`
                          : null;
                        return (
                          <tr className="border-t border-line" key={field.field_id}>
                            <td className="py-1 pr-3 text-slate-700">{gapFieldText(field)}</td>
                            <td className="py-1 pr-3 tabular-nums text-slate-600">{field.count}</td>
                            <td className="py-1 pr-3">
                              {href ? (
                                <Link className="text-pine-700 underline" href={href} aria-label={`在工作台处理 ${gapFieldText(field)}`}>
                                  在工作台打开
                                </Link>
                              ) : (
                                <span className="text-slate-400">无法定位</span>
                              )}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                  {gapBreakdown.truncated_fields ? (
                    <p className="mt-2 text-[11px] text-slate-400">
                      只列出缺口最多的字段，完整明细在工作台「待确认」里。
                    </p>
                  ) : null}
                  <h3 className="mt-4 text-[11px] font-semibold text-slate-500">按类别</h3>
                  <ul className="mt-1 space-y-1">
                    {gapBreakdown.categories.map((category) => (
                      <li
                        className="flex justify-between gap-3 border-t border-line pt-1 text-slate-700"
                        key={category.category}
                      >
                        <span className="truncate" title={category.category}>
                          {category.category}
                        </span>
                        <span className="tabular-nums text-slate-600">{category.count} 条</span>
                      </li>
                    ))}
                  </ul>
                  {gapBreakdown.truncated_categories ? (
                    <p className="mt-2 text-[11px] text-slate-400">只列出条数最多的几类问题。</p>
                  ) : null}
                  <p className="mt-3 text-[11px] text-slate-500">
                    这里只做归类，不改任何内容；处置与"补齐后重新冻结"仍在工作台完成。
                  </p>
                </div>
              ) : null}
            </div>
          </div>
        ) : null}
        {gapColumn ? (
          <div className="fixed inset-0 z-40 flex items-start justify-center bg-ink/40 p-6" role="presentation">
            <div
              aria-label="模板列缺口清单"
              className="max-h-[86vh] w-full max-w-5xl overflow-hidden rounded-xl bg-white shadow-xl"
              role="dialog"
            >
              <div className="flex flex-wrap items-baseline justify-between gap-3 border-b border-line px-5 py-3">
                <div>
                  <h2 className="text-sm font-semibold text-ink">
                    缺口清单{gapPanel ? `：${gapPanel.column_label}` : ""}
                  </h2>
                  <p className="mt-1 text-xs text-slate-500">
                    {gapPanel ? gapSummaryText(gapPanel) : "正在读取缺口清单…"}
                    {gapPanel ? ` · 归属：${gapPanel.source_label}` : ""}
                  </p>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <input
                    aria-label="按监管表筛选缺口"
                    className="field w-40 text-xs"
                    onChange={(event) => setGapFilter(event.target.value)}
                    placeholder="表编号完全匹配，如 T_8_1；前缀用 T_8*"
                    title="默认按表编号完全匹配；要筛一组表请以 * 结尾（如 T_8*）"
                    value={gapFilter}
                  />
                  <button
                    className="btn-ghost"
                    disabled={gapBusy}
                    onClick={() => void openGapPanel(gapColumn, 500, gapFilter)}
                    type="button"
                  >
                    筛选
                  </button>
                  {gapPanel?.table_filter ? (
                    <button
                      className="btn-ghost"
                      disabled={gapBusy}
                      onClick={() => void openGapPanel(gapColumn, 500, "")}
                      type="button"
                    >
                      清除筛选
                    </button>
                  ) : null}
                  <button className="btn-ghost" disabled={!gapPanel || gapBusy} onClick={downloadGapCsv} type="button">
                    {gapPanel ? `下载 CSV（${gapPanel.returned} 行）` : "下载 CSV"}
                  </button>
                  {gapPanel?.truncated ? (
                    <button
                      className="btn-ghost"
                      disabled={gapBusy}
                      onClick={() => void openGapPanel(gapColumn, 5000, gapFilter)}
                      type="button"
                    >
                      下载全部（最多 5000 条）
                    </button>
                  ) : null}
                  <button
                    className="btn-ghost"
                    onClick={() => {
                      setGapColumn(null);
                      setGapPanel(null);
                      setGapError("");
                      setGapFilter("");
                    }}
                    type="button"
                  >
                    关闭
                  </button>
                </div>
              </div>
              <div className="max-h-[68vh] overflow-auto px-5 py-3">
                {gapError ? (
                  <p className="rounded-lg border border-coral-200 bg-coral-50 px-3 py-2 text-xs text-coral-700">{gapError}</p>
                ) : null}
                {gapBusy ? <div className="h-16 animate-pulse rounded bg-slate-50" /> : null}
                {gapPanel ? (
                  <>
                    <p className="mb-2 text-[11px] text-slate-500">
                      只列"这一列没有值"的字段；当前值为「—」表示确实为空，不是读取失败。清单与实际导出口径同源，
                      填补之后需要重新导出才会出现在文档里。
                    </p>
                    <table className="w-full min-w-[720px] text-left text-xs">
                      <thead className="text-slate-500">
                        <tr>
                          <th className="py-1 pr-3 font-medium">监管表</th>
                          <th className="py-1 pr-3 font-medium">字段代码</th>
                          <th className="py-1 pr-3 font-medium">字段名称</th>
                          <th className="py-1 font-medium">当前值</th>
                        </tr>
                      </thead>
                      <tbody>
                        {gapPanel.items.slice(0, 200).map((item) => (
                          <tr className="border-t border-line" key={item.field_id}>
                            <td className="py-1 pr-3 text-slate-600">{item.table_code}</td>
                            <td className="py-1 pr-3 tabular-nums text-ink">{item.field_code}</td>
                            <td className="py-1 pr-3 text-slate-600">{item.field_name}</td>
                            <td className="py-1 text-slate-400">{item.value ?? "—"}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                    {gapPanel.items.length > 200 ? (
                      <p className="mt-2 text-[11px] text-slate-500">
                        表格只展示前 200 行，CSV 包含服务端返回的全部 {gapPanel.returned} 行。
                      </p>
                    ) : null}
                  </>
                ) : null}
              </div>
            </div>
          </div>
        ) : null}
        <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {data
            ? Object.entries(data.dimensions).map(([key, item]) => (
                <DimensionCard dimensionKey={key} item={item} key={key} />
              ))
            : Array.from({ length: 6 }, (_, index) => (
                <div className="panel h-40 animate-pulse bg-slate-50" key={index} />
              ))}
        </section>
      </div>
    </main>
  );
}

function DimensionCard({ dimensionKey, item }: { dimensionKey: string; item: ReadinessDimension }) {
  const Icon = item.status === "ready" ? CheckCircle2 : item.status === "blocked" ? AlertTriangle : CircleDashed;
  return (
    <article className="panel p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="font-semibold text-ink">{LABELS[dimensionKey] || dimensionKey}</h2>
          <p className="mt-1 text-xs text-slate-500">
            {item.completed_count} / {item.required_count} 项完成
          </p>
        </div>
        <span className={STATUS_BADGE[item.status] || "badge-neutral"}>
          <Icon size={12} />
          {STATUS[item.status] || "状态待同步"}
        </span>
      </div>
      <div className="mt-3 h-2 rounded-full bg-slate-100">
        <div className="h-2 rounded-full bg-pine transition-all" style={{ width: `${Math.round(item.score * 100)}%` }} />
      </div>
      {item.blocking_reasons.map((reason) => (
        <p className="mt-3 text-sm text-gold-700" key={reason.code}>
          {describeUserMessage(reason.message, "该原因说明待补充，请人工核验。")}
        </p>
      ))}
      {item.recommended_actions[0] ? (
        <p className="mt-3 text-sm text-slate-600">建议：{item.recommended_actions[0]}</p>
      ) : null}
      {item.links[0] ? (
        <Link className="mt-3 inline-block text-sm font-medium text-pine-600 hover:text-pine-700" href={item.links[0]}>
          前往处理
        </Link>
      ) : null}
    </article>
  );
}


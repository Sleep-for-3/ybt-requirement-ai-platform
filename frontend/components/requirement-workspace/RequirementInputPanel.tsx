"use client";

import { ArrowRight, Building2, Database, FileText, Layers3, Sparkles, Table2 } from "lucide-react";
import Link from "next/link";

import { AiStatus } from "@/components/requirement-workspace/AiStatus";
import type {
  BackgroundJobSummary,
  ProductScenario,
  RequirementWorkspaceAssetSummary,
  ScenarioBusinessMapping,
  ScenarioTechnicalLineage,
  TargetField,
  TargetTable
} from "@/lib/api";

export function RequirementInputPanel({
  tables,
  tableId,
  onTableChange,
  fields,
  fieldId,
  onFieldChange,
  scenarios,
  scenarioId,
  onScenarioChange,
  assetSummary,
  selectedField,
  selectedBusiness,
  selectedLineage,
  businessJob,
  technicalJob,
  generating,
  onGenerate,
  requirementMode = false
}: {
  tables: TargetTable[];
  tableId: number | null;
  onTableChange: (id: number | null) => void;
  fields: TargetField[];
  fieldId: number | null;
  onFieldChange: (id: number) => void;
  scenarios: ProductScenario[];
  scenarioId: number | null;
  onScenarioChange: (id: number | null) => void;
  assetSummary: RequirementWorkspaceAssetSummary;
  selectedField: TargetField | null;
  selectedBusiness: ScenarioBusinessMapping | null;
  selectedLineage: ScenarioTechnicalLineage | null;
  businessJob: BackgroundJobSummary | null;
  technicalJob: BackgroundJobSummary | null;
  generating: boolean;
  onGenerate: () => void;
  requirementMode?: boolean;
}) {
  const contextText = selectedBusiness?.business_definition || selectedField?.regulatory_refined_definition || selectedField?.regulatory_description || selectedField?.field_definition || "";
  const canGenerate = Boolean(selectedField && scenarioId);

  return (
    <div className="space-y-3">
      <section className="panel overflow-hidden">
        <PanelHeader title="① 报送目标" meta="真实项目范围" />
        <div className="space-y-3 p-4">
          <label className="block">
            <span className="mb-1.5 block text-xs font-semibold text-slate-600">一表通目标表</span>
            <select className="control" onChange={(event) => onTableChange(Number(event.target.value) || null)} value={tableId || ""}>
              <option value="">选择目标表</option>
              {tables.map((table) => <option key={table.id} value={table.id}>{table.table_code} {table.table_name}</option>)}
            </select>
          </label>
          <label className="block">
            <span className="mb-1.5 block text-xs font-semibold text-slate-600">业务场景</span>
            <select className="control" onChange={(event) => onScenarioChange(Number(event.target.value) || null)} value={scenarioId || ""}>
              <option value="">选择场景</option>
              {scenarios.map((scenario) => <option key={scenario.id} value={scenario.id}>{scenario.scenario_name}</option>)}
            </select>
          </label>
          <div className="rounded-lg border border-line bg-mist/60 p-3">
            <div className="flex items-center gap-2 text-xs font-semibold text-ink"><Table2 className="text-pine" size={15} />目标字段</div>
            <div className="mt-2 max-h-40 space-y-1 overflow-y-auto pr-1">
              {fields.map((field) => (
                <button
                  className={`flex w-full items-center gap-2 rounded-md px-2.5 py-2 text-left text-xs transition ${field.id === fieldId ? "bg-pine text-white" : "bg-white text-slate-600 hover:bg-pine-50 hover:text-pine-800"}`}
                  key={field.id}
                  onClick={() => onFieldChange(field.id)}
                  type="button"
                >
                  <span className="w-20 shrink-0 truncate font-mono text-[10px] opacity-75">{field.field_code}</span>
                  <span className="min-w-0 flex-1 truncate font-medium">{field.field_name}</span>
                  <ArrowRight size={13} />
                </button>
              ))}
              {!fields.length ? <p className="py-4 text-center text-xs text-slate-500">当前目标表没有字段</p> : null}
            </div>
          </div>
        </div>
      </section>

      <section className="panel overflow-hidden">
        <PanelHeader title="② 项目资料与数据" meta="已登记资产" />
        <div className="space-y-2 p-4">
          <AssetRow icon={Building2} label="业务源系统" value={assetSummary.business_system_count ? `${assetSummary.business_system_count} 个已启用` : "尚未维护"} available={assetSummary.business_system_count > 0} href="/business-systems" />
          <AssetRow icon={Database} label="只读数据源" value={assetSummary.healthy_datasource_count ? `${assetSummary.healthy_datasource_count} 个连接正常` : assetSummary.datasource_count ? "连接状态待检查" : "尚未配置"} available={assetSummary.healthy_datasource_count > 0} href="/datasources" />
          <AssetRow icon={Layers3} label="监管集市" value={assetSummary.mart_table_count ? `${assetSummary.mart_table_count} 张已登记集市表` : "尚未维护"} available={assetSummary.mart_table_count > 0} href="/mart" />
          <AssetRow icon={FileText} label="历史与知识" value="检索字段相关资料，核验依据" available href="/knowledge" />
        </div>
      </section>

      <section className="panel overflow-hidden">
        <PanelHeader title="③ 字段定义参考" meta="来自已有字段与场景口径" />
        <div className="p-4">
          <label className="block">
            <span className="mb-1.5 block text-xs font-semibold text-slate-600">当前字段定义（只读参考）</span>
            <textarea className="control min-h-28 resize-y bg-mist/50 leading-6" readOnly value={contextText} placeholder="当前字段尚无监管定义或业务口径，请进入字段场景工作台补充。" />
          </label>
          <p className="mt-1.5 text-[11px] leading-5 text-slate-500">需求背景请在上方“需求说明与生成范围”中填写并保存；字段口径在右侧编辑。</p>
          {!requirementMode ? <><div className="mt-3"><AiStatus businessJob={businessJob} technicalJob={technicalJob} /></div>
          <button className="button-primary mt-3 h-10 w-full" disabled={!canGenerate || generating} onClick={onGenerate} type="button">
            <Sparkles size={16} />
            {generating ? "正在提交草稿任务…" : "生成业务口径与技术溯源草稿"}
          </button>
          {selectedField ? (
            <Link className="button-secondary mt-2 w-full" href={`/fields/${selectedField.id}/scenarios`}>
              深度编辑、证据绑定与提交审核
            </Link>
          ) : null}
          {!selectedBusiness || !selectedLineage ? <p className="mt-2 text-[11px] leading-5 text-gold-700">首次生成将为当前字段和业务场景建立草稿，已有人工口径仍需保留和核验。</p> : null}
          </> : <p className="mt-3 text-[11px] leading-5 text-slate-500">当前为需求独立版本，批量生成、失败重试和候选采用统一在“范围生成”中处理。</p>}
        </div>
      </section>
    </div>
  );
}

function PanelHeader({ title, meta }: { title: string; meta: string }) {
  return (
    <div className="flex h-12 items-center border-b border-line px-4">
      <h2 className="text-[13px] font-semibold text-ink">{title}</h2>
      <span className="ml-2 text-[10px] text-slate-400">{meta}</span>
    </div>
  );
}

function AssetRow({ icon: Icon, label, value, available, href }: { icon: typeof Database; label: string; value: string; available: boolean; href: string }) {
  return (
    <Link className="flex items-center gap-3 rounded-lg border border-line bg-white p-3 transition hover:border-pine-200 hover:bg-pine-50/40" href={href}>
      <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-slate-100 text-slate-600"><Icon size={15} /></span>
      <span className="min-w-0 flex-1">
        <strong className="block text-xs text-ink">{label}</strong>
        <span className="block truncate text-[10px] text-slate-500">{value}</span>
      </span>
      <span className={available ? "badge-success" : "badge-neutral"}>{available ? "可用" : "待接入"}</span>
    </Link>
  );
}

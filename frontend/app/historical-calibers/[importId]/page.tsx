"use client";

import { Check, Copy, SearchX } from "lucide-react";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { WorkspaceHeader } from "@/components/WorkspaceHeader";
import { HistoricalCaliberImport, HistoricalCaliberItem, ProductScenario, TargetField, apiGet, apiPost } from "@/lib/api";
import { useProjectPermissions } from "@/lib/project-permissions";

type Preview = HistoricalCaliberImport & { items: HistoricalCaliberItem[] };

const MATCH_BADGE: Record<string, string> = {
  matched: "badge-success",
  ambiguous: "badge-warning",
  unmatched: "badge-neutral"
};

export default function Page() {
  const importId = Number(useParams().importId);
  const [preview, setPreview] = useState<Preview | null>(null);
  const permissions = useProjectPermissions(preview?.project_id);
  const [fields, setFields] = useState<TargetField[]>([]);
  const [scenarios, setScenarios] = useState<ProductScenario[]>([]);
  const [filter, setFilter] = useState("");
  const [selection, setSelection] = useState<Record<number, { fieldId: string; scenarioId: string }>>({});
  const [message, setMessage] = useState("");

  async function load() {
    try {
      const result = await apiGet<Preview>(`/historical-calibers/${importId}/preview`);
      setPreview(result);
      const [targetFields, scenarioRows] = await Promise.all([
        apiGet<TargetField[]>(`/fields?project_id=${result.project_id}`),
        apiGet<ProductScenario[]>(`/projects/${result.project_id}/scenarios`)
      ]);
      setFields(targetFields);
      setScenarios(scenarioRows);
    } catch (error) {
      setMessage(readError(error));
    }
  }

  useEffect(() => {
    void load();
  }, [importId]);

  const visible = useMemo(
    () => (preview?.items || []).filter((item) => !filter || item.match_status === filter),
    [preview, filter]
  );

  function chosen(item: HistoricalCaliberItem) {
    return (
      selection[item.id] || {
        fieldId: item.matched_target_field_id ? String(item.matched_target_field_id) : "",
        scenarioId: item.matched_scenario_id ? String(item.matched_scenario_id) : ""
      }
    );
  }

  async function resolve(item: HistoricalCaliberItem) {
    const value = chosen(item);
    if (!value.fieldId) return;
    try {
      await apiPost(`/historical-caliber-items/${item.id}/resolve-match`, {
        target_field_id: Number(value.fieldId),
        scenario_id: value.scenarioId ? Number(value.scenarioId) : null
      });
      setMessage("人工匹配已保存。");
      await load();
    } catch (error) {
      setMessage(readError(error));
    }
  }

  async function reuse(itemId: number) {
    try {
      const result = await apiPost<{ final_content_overwritten: boolean }>(`/historical-caliber-items/${itemId}/reuse`, {});
      setMessage(
        result.final_content_overwritten
          ? "复用结果异常：服务端报告覆盖最终内容。"
          : "已复用到 AI 建议区，人工 final_content 保持不变。"
      );
    } catch (error) {
      setMessage(readError(error));
    }
  }

  return (
    <main>
      <WorkspaceHeader title={preview?.import_name || "历史口径预览"} meta="人工确认目标字段与场景后复用" />
      <div className="mx-auto max-w-7xl space-y-4 p-4 lg:p-6">
        <section className="panel flex flex-wrap items-center gap-2 p-4">
          <span className="text-sm font-medium text-ink">匹配状态</span>
          <select className="control max-w-48" value={filter} onChange={(event) => setFilter(event.target.value)}>
            <option value="">全部</option>
            <option value="matched">matched</option>
            <option value="ambiguous">ambiguous</option>
            <option value="unmatched">unmatched</option>
          </select>
          <span className="ml-auto text-xs text-slate-500">复用只写建议区，不覆盖人工最终口径。</span>
        </section>

        {message ? (
          <p className="rounded-lg border border-line bg-white px-3 py-2 text-sm text-slate-600">{message}</p>
        ) : null}

        {visible.map((item) => {
          const value = chosen(item);
          return (
            <section className="panel p-4" key={item.id}>
              <div className="flex flex-wrap justify-between gap-3">
                <div>
                  <b className="text-sm font-semibold text-ink">
                    {item.target_field_code || "未识别字段"} {item.target_field_name || ""} / {item.scenario_name || "场景待确认"}
                  </b>
                  <p className="mt-1 text-xs text-slate-500">
                    来源：{item.source_sheet_name}!{item.source_cell_range}
                  </p>
                </div>
                <span className={MATCH_BADGE[item.match_status] || "badge-neutral"}>{item.match_status}</span>
              </div>
              <div className="mt-3 grid gap-3 md:grid-cols-2">
                <div className="rounded-lg bg-mist/60 p-3">
                  <div className="text-xs font-medium text-slate-500">历史业务口径</div>
                  <p className="mt-1 whitespace-pre-wrap text-sm text-ink">{item.business_content || "无"}</p>
                </div>
                <div className="rounded-lg bg-mist/60 p-3">
                  <div className="text-xs font-medium text-slate-500">历史技术溯源</div>
                  <p className="mt-1 whitespace-pre-wrap text-sm text-ink">{item.technical_content || "无"}</p>
                </div>
              </div>
              {permissions.can("historical_caliber.reuse") ? (
                <div className="mt-4 flex flex-wrap gap-2 border-t border-line pt-4">
                  <select
                    className="control max-w-xs"
                    value={value.fieldId}
                    onChange={(event) =>
                      setSelection((current) => ({ ...current, [item.id]: { ...value, fieldId: event.target.value } }))
                    }
                  >
                    <option value="">人工选择目标字段</option>
                    {fields.map((field) => (
                      <option value={field.id} key={field.id}>
                        {field.field_code} {field.field_name}
                      </option>
                    ))}
                  </select>
                  <select
                    className="control max-w-xs"
                    value={value.scenarioId}
                    onChange={(event) =>
                      setSelection((current) => ({ ...current, [item.id]: { ...value, scenarioId: event.target.value } }))
                    }
                  >
                    <option value="">人工选择业务场景</option>
                    {scenarios.map((scenario) => (
                      <option value={scenario.id} key={scenario.id}>
                        {scenario.scenario_code} {scenario.scenario_name}
                      </option>
                    ))}
                  </select>
                  <button className="button-secondary" disabled={!value.fieldId} onClick={() => resolve(item)}>
                    <Check size={14} />
                    确认匹配
                  </button>
                  <button
                    className="button-primary"
                    disabled={item.match_status !== "matched" || !item.matched_scenario_id}
                    onClick={() => reuse(item.id)}
                  >
                    <Copy size={14} />
                    复用到建议区
                  </button>
                </div>
              ) : null}
            </section>
          );
        })}

        {!visible.length ? (
          <div className="empty-state">
            <SearchX className="text-slate-300" size={28} />
            <p>没有符合筛选条件的历史记录，试试切换匹配状态筛选</p>
          </div>
        ) : null}
      </div>
    </main>
  );
}

function readError(error: unknown) {
  return error instanceof Error ? error.message : "操作失败";
}

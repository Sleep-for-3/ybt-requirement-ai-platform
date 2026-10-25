"use client";

import { useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiGet, apiPost } from "@/lib/api";

type FactPack = {
  id: number;
  pack_sha256: string;
  pack_version: string;
  level: string;
  status: string;
  execution_batch: string | null;
  business_date: string | null;
  validation?: { missing?: string[]; issues?: { code?: string; message?: string }[]; fact_statuses?: Record<string, string> };
  issues?: { code?: string; message?: string }[];
  created_at: string | null;
};

const LEVEL_LABEL: Record<string, string> = {
  full_run_validation: "全量运行验证",
  sampled_validation: "样例验证",
  static_inference: "静态推断",
};

const LEVEL_TONE: Record<string, string> = {
  full_run_validation: "text-emerald-700",
  sampled_validation: "text-amber-700",
  static_inference: "text-slate-600",
};

function levelLabel(level: string) {
  return LEVEL_LABEL[level] || level;
}

export function RequirementRuntimeFactsPanel({ projectId, requirementId }: { projectId: number; requirementId: number }) {
  const base = `/projects/${projectId}/requirements/${requirementId}/runtime-fact-packs`;
  const [message, setMessage] = useState("");
  const [raw, setRaw] = useState("");
  const [busy, setBusy] = useState(false);
  const locked = useRef(false);

  const access = useQuery({
    queryKey: ["requirement-runtime-facts-access", projectId],
    queryFn: ({ signal }) => apiGet<{ effective_project_permissions?: Record<string, string[]> }>("/auth/me", { signal }),
  });
  const permissions = access.data?.effective_project_permissions?.[String(projectId)] || [];
  const canView = permissions.includes("project.view");
  const canImport = permissions.includes("technical.edit");

  const packs = useQuery({
    queryKey: ["requirement-runtime-facts", projectId, requirementId],
    enabled: canView,
    queryFn: ({ signal }) => apiGet<{ requirement_id: number; count: number; items: FactPack[] }>(base, { signal }),
  });

  async function readFile(file: File | undefined) {
    if (!file) return;
    try {
      setRaw(await file.text());
      setMessage(`已读取 ${file.name}，确认内容后再导入。`);
    } catch {
      setMessage("读取文件失败，请确认文件是 UTF-8 编码的 JSON。");
    }
  }

  async function submit() {
    if (locked.current || !canImport) return;
    let payload: unknown;
    try {
      payload = JSON.parse(raw);
    } catch {
      setMessage("事实包不是合法 JSON，未提交。");
      return;
    }
    locked.current = true;
    setBusy(true);
    setMessage("");
    try {
      const result = await apiPost<{ created: boolean; pack: FactPack }>(base, payload);
      setMessage(
        result.created
          ? `事实包已冻结入库（级别：${levelLabel(result.pack.level)}）。重复导入不会刷新当时的校验结论。`
          : "同一内容的事实包已存在，沿用原结论，未新增记录。",
      );
      setRaw("");
      await packs.refetch();
    } catch (error) {
      const detail = (error as { message?: string })?.message;
      setMessage(detail || "导入失败。请确认权限、包体积（不超过 2MB）与 JSON 结构。");
    } finally {
      locked.current = false;
      setBusy(false);
    }
  }

  return <section className="panel mb-3 p-4" aria-label="运行事实包">
    <h2 className="text-sm font-semibold">运行事实包（脱敏）</h2>
    <p className="my-2 text-xs text-slate-500">
      平台不执行客户跑批。这里的键唯一率、空值率、join 对账等结论来自授权环境导出的脱敏事实包；导入即冻结，不随后续代码升级重算。
    </p>
    {access.isPending ? <p role="status" className="text-xs">正在核验权限…</p> : null}
    {!canView && access.isSuccess ? <p className="mt-2 text-xs">当前角色不能查看运行事实包。</p> : null}
    {canView ? (
      packs.isError ? (
        <p role="alert" className="mt-2 text-xs">无法读取事实包记录。<button onClick={() => void packs.refetch()}>重试</button></p>
      ) : packs.isPending ? (
        <p role="status" className="mt-2 text-xs">正在读取事实包…</p>
      ) : (
        <ul className="mt-3 max-h-56 space-y-2 overflow-auto text-xs">
          {packs.data?.items.length ? packs.data.items.map((item) => {
            const gaps = item.validation?.missing || [];
            const issues = item.issues || item.validation?.issues || [];
            return <li key={item.id} className="border-t pt-2">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-medium">#{item.id}</span>
                <span className={LEVEL_TONE[item.level] || "text-slate-600"}>{levelLabel(item.level)}</span>
                <span className="text-slate-500">{item.status}</span>
                <span className="text-slate-500">批次 {item.execution_batch || "未提供"}</span>
                <span className="text-slate-500">业务日期 {item.business_date || "未提供"}</span>
              </div>
              <p className="mt-1 text-slate-500">sha256 {item.pack_sha256.slice(0, 12)}… · 导入于 {item.created_at ? new Date(item.created_at).toLocaleString("zh-CN") : "未知"}</p>
              {gaps.length ? <p className="mt-1 text-amber-700">缺项：{gaps.join("、")}（这些事实只能作为静态推断）</p> : null}
              {issues.length ? <p className="mt-1 text-rose-700">校验问题：{issues.map((issue) => issue.message || issue.code || "未说明").join("；")}</p> : null}
            </li>;
          }) : <li>尚未导入运行事实包。</li>}
        </ul>
      )
    ) : null}
    {canImport ? <div className="mt-3 space-y-2 border-t pt-3">
      <p className="text-xs text-slate-500">粘贴或选择 JSON 文件后导入。导入只记账，不会自动改写需求正文或关闭缺口。</p>
      <input type="file" accept="application/json,.json" className="text-xs" onChange={(event) => void readFile(event.target.files?.[0])} />
      <textarea aria-label="事实包 JSON" className="h-28 w-full rounded border p-2 font-mono text-xs" value={raw} onChange={(event) => setRaw(event.target.value)} placeholder={'{\n  "pack_version": "runtime-fact-v1",\n  "source": {...},\n  "run": {...},\n  "quality": {...}\n}'} />
      <button className="button-secondary" disabled={busy || !raw.trim()} onClick={() => void submit()}>{busy ? "导入中…" : "导入事实包"}</button>
    </div> : null}
    {message ? <p role="status" className="mt-2 text-xs">{message}</p> : null}
  </section>;
}

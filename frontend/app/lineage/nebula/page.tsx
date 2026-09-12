"use client";

import { useEffect, useState } from "react";

import { LineageNebula } from "@/components/LineageNebula";
import { useProjectWorkspace } from "@/components/ProjectContext";
import { WorkspaceHeader } from "@/components/WorkspaceHeader";
import { LineagePathResponse, apiGet } from "@/lib/api";

const ROOT_TYPES = [
  { value: "target_field", label: "监管目标字段" },
  { value: "mart_field", label: "监管集市字段" },
  { value: "source_field", label: "源系统字段" },
  { value: "catalog_column", label: "数据目录字段" },
  { value: "lineage_node", label: "脚本血缘节点" }
];

const DIRECTIONS = [
  { value: "upstream", label: "上游（取数来源）" },
  { value: "downstream", label: "下游（影响范围）" },
  { value: "both", label: "双向" }
];

type Revision = {
  id: number;
  revision_no?: number | null;
  status?: string;
  published_at?: string | null;
  created_at?: string | null;
};

type FetchStatus = "idle" | "loading" | "error" | "ready";

export default function Page() {
  const { projectId } = useProjectWorkspace();
  const [rootType, setRootType] = useState("target_field");
  const [rootId, setRootId] = useState("");
  const [direction, setDirection] = useState("upstream");
  const [depth, setDepth] = useState(6);
  const [view, setView] = useState("business");
  const [revisionId, setRevisionId] = useState("");
  const [revisions, setRevisions] = useState<Revision[]>([]);
  const [payload, setPayload] = useState<LineagePathResponse | null>(null);
  const [status, setStatus] = useState<FetchStatus>("idle");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const nextRootType = params.get("rootType");
    if (nextRootType && ROOT_TYPES.some((item) => item.value === nextRootType)) setRootType(nextRootType);
    const nextRootId = params.get("rootId");
    if (nextRootId) setRootId(nextRootId);
    const nextDirection = params.get("direction");
    if (nextDirection && DIRECTIONS.some((item) => item.value === nextDirection)) setDirection(nextDirection);
    const nextDepth = Number(params.get("depth"));
    if (Number.isFinite(nextDepth) && nextDepth >= 1 && nextDepth <= 10) setDepth(nextDepth);
    const nextRevision = params.get("revisionId");
    if (nextRevision) setRevisionId(nextRevision);
    const nextView = params.get("view");
    if (nextView === "technical" || nextView === "business") setView(nextView);
  }, []);

  useEffect(() => {
    if (!projectId) {
      setRevisions([]);
      return;
    }
    let cancelled = false;
    void apiGet<Revision[]>(`/projects/${projectId}/lineage/revisions?status=published&limit=50`)
      .then((items) => {
        if (!cancelled) setRevisions(items);
      })
      .catch(() => {
        if (!cancelled) setRevisions([]);
      });
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  const numericRootId = Number(rootId);
  const validRoot = Number.isFinite(numericRootId) && numericRootId > 0;

  useEffect(() => {
    if (!projectId || !validRoot) {
      setPayload(null);
      setStatus("idle");
      return;
    }
    const controller = new AbortController();
    const query = new URLSearchParams({
      root_type: rootType,
      root_id: String(numericRootId),
      direction,
      depth: String(depth),
      view,
      include_unresolved: "true",
      max_paths: "60"
    });
    if (revisionId) query.set("revision_id", revisionId);
    setStatus("loading");
    setErrorMessage(null);
    apiGet<LineagePathResponse>(`/projects/${projectId}/lineage/path?${query.toString()}`, {
      signal: controller.signal
    })
      .then((result) => {
        if (controller.signal.aborted) return;
        setPayload(result);
        setStatus("ready");
      })
      .catch((cause: unknown) => {
        if (controller.signal.aborted) return;
        setPayload(null);
        setErrorMessage(cause instanceof Error ? cause.message : "加载血缘路径失败");
        setStatus("error");
      });
    return () => controller.abort();
  }, [projectId, rootType, numericRootId, validRoot, direction, depth, view, revisionId]);

  return (
    <main>
      <WorkspaceHeader
        title="数据星云"
        meta="按层级浏览 源系统 → 数仓 → 监管集市 → 一表通/EAST/1104 的端到端血缘"
      />
      <div className="mx-auto max-w-[1600px] space-y-4 p-4 lg:p-6">
        <section className="panel">
          <div className="panel-header">
            <strong className="text-ink">探索条件</strong>
          </div>
          <div className="panel-body grid gap-3 md:grid-cols-2 lg:grid-cols-4">
            <label className="text-xs text-slate-500">
              根对象类型
              <select className="control mt-1" value={rootType} onChange={(event) => setRootType(event.target.value)}>
                {ROOT_TYPES.map((item) => (
                  <option key={item.value} value={item.value}>
                    {item.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="text-xs text-slate-500">
              根对象 ID
              <input
                className="control mt-1"
                inputMode="numeric"
                min={1}
                onChange={(event) => setRootId(event.target.value)}
                placeholder="例如 1024"
                type="number"
                value={rootId}
              />
            </label>
            <label className="text-xs text-slate-500">
              方向
              <select className="control mt-1" value={direction} onChange={(event) => setDirection(event.target.value)}>
                {DIRECTIONS.map((item) => (
                  <option key={item.value} value={item.value}>
                    {item.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="text-xs text-slate-500">
              血缘版本
              <select
                className="control mt-1"
                onChange={(event) => setRevisionId(event.target.value)}
                value={revisionId}
              >
                <option value="">最近发布的正式版本</option>
                {revisions.map((item) => (
                  <option key={item.id} value={String(item.id)}>
                    版本 v{item.revision_no ?? item.id}
                  </option>
                ))}
              </select>
            </label>
            <label className="text-xs text-slate-500">
              向上深度（1-10）
              <input
                className="control mt-1"
                max={10}
                min={1}
                onChange={(event) => setDepth(Number(event.target.value) || 1)}
                type="number"
                value={depth}
              />
            </label>
            <label className="text-xs text-slate-500">
              视图
              <select className="control mt-1" value={view} onChange={(event) => setView(event.target.value)}>
                <option value="business">业务视图（中文业务名优先）</option>
                <option value="technical">技术视图</option>
              </select>
            </label>
            <div className="text-xs text-slate-500 lg:col-span-2">
              说明
              <p className="mt-1 leading-relaxed text-slate-600">
                星云按血缘版本读取同一份端到端路径响应；无法证明的关联保持“未解析”，不会自动补全。查询有层数与节点预算，
                超出时显式标记截断。
              </p>
            </div>
          </div>
        </section>

        {!projectId ? (
          <section className="panel">
            <div className="panel-body">
              <div className="empty-state">请先在顶部选择项目，再查看项目内的数据血缘。</div>
            </div>
          </section>
        ) : !validRoot && status === "idle" ? (
          <section className="panel">
            <div className="panel-body">
              <div className="empty-state">
                <p>请输入根对象 ID（例如某个监管目标字段），随后自动加载分层星云。</p>
                <p className="text-xs text-slate-400">
                  也可以从字段血缘页跳转：/lineage/nebula?rootType=target_field&amp;rootId=字段ID
                </p>
              </div>
            </div>
          </section>
        ) : null}

        <LineageNebula errorMessage={errorMessage} payload={payload} status={status} />
      </div>
    </main>
  );
}

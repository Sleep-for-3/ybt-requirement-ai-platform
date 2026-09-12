"use client";

import { useParams } from "next/navigation";
import Link from "next/link";
import { useEffect, useState } from "react";

import { LineageGraph } from "@/components/LineageGraph";
import { WorkspaceHeader } from "@/components/WorkspaceHeader";
import { LineageGraph as Graph, apiGet } from "@/lib/api";

export default function Page() {
  const { fieldId } = useParams<{ fieldId: string }>();
  const [direction, setDirection] = useState("both");
  const [depth, setDepth] = useState(5);
  const [graph, setGraph] = useState<Graph | null>(null);

  useEffect(() => {
    void apiGet<Graph>(`/target-fields/${fieldId}/lineage?direction=${direction}&depth=${depth}`).then(setGraph);
  }, [fieldId, direction, depth]);

  return (
    <main>
      <WorkspaceHeader title={`字段 #${fieldId} 血缘`} meta="上游、下游与双向字段级路径" />
      <div className="mx-auto max-w-7xl space-y-4 p-4 lg:p-6">
        <section className="panel">
          <div className="panel-body flex flex-wrap items-center gap-3">
            <select className="control max-w-48" value={direction} onChange={(e) => setDirection(e.target.value)}>
              <option value="upstream">上游</option>
              <option value="downstream">下游</option>
              <option value="both">双向</option>
            </select>
            <input
              className="control max-w-32"
              type="number"
              min={1}
              max={10}
              value={depth}
              onChange={(e) => setDepth(Number(e.target.value))}
            />
          </div>
        </section>
        <section className="panel">
          <div className="panel-body flex flex-wrap items-center justify-between gap-3">
            <p className="text-sm text-slate-600">按层级查看该字段的端到端数据星云（源系统 → 数仓 → 监管集市 → 监管输出）。</p>
            <Link
              className="button-secondary h-9 px-3 text-sm"
              href={`/lineage/nebula?rootType=target_field&rootId=${fieldId}&direction=upstream&depth=${depth}`}
            >
              打开数据星云
            </Link>
          </div>
        </section>
        <LineageGraph graph={graph} />
      </div>
    </main>
  );
}

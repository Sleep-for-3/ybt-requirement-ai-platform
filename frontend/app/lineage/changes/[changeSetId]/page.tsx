"use client";

import { FileDiff } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { WorkspaceHeader } from "@/components/WorkspaceHeader";
import { apiGet } from "@/lib/api";

type Item = {
  id: number;
  change_category: string;
  entity_type: string;
  old_value: Record<string, unknown>;
  new_value: Record<string, unknown>;
  severity: string;
};

type Detail = {
  id: number;
  script_file_id: number;
  from_version_id?: number | null;
  to_version_id?: number | null;
  from_version_no?: number | null;
  to_version_no?: number | null;
  summary: Record<string, unknown>;
  items: Item[];
  impact?: { id: number; severity: string; status: string } | null;
};

function severityBadge(severity: string) {
  if (severity === "critical") return "badge-danger";
  if (severity === "high") return "badge-warning";
  return "badge-neutral";
}

export default function Page() {
  const { changeSetId } = useParams<{ changeSetId: string }>();
  const [data, setData] = useState<Detail | null>(null);

  useEffect(() => {
    void apiGet<Detail>(`/lineage/changes/${changeSetId}`).then(setData);
  }, [changeSetId]);

  return (
    <main>
      <WorkspaceHeader
        title={`变更集 #${changeSetId}`}
        meta={`v${data?.from_version_no || "-"} → v${data?.to_version_no || "-"}`}
      />
      <div className="mx-auto max-w-6xl space-y-5 p-4 lg:p-6">
        {data?.impact ? (
          <Link className="button-primary" href={`/lineage/impacts/${data.impact.id}`}>
            查看 {data.impact.severity} 影响分析
          </Link>
        ) : null}

        <section className="panel overflow-hidden">
          {data && !data.items.length ? (
            <div className="panel-body">
              <div className="empty-state">
                <FileDiff className="text-slate-300" size={28} />
                <p>该变更集没有逐项差异记录</p>
              </div>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <div className="min-w-[720px]">
                <div className="grid-head grid grid-cols-[140px_100px_minmax(0,1fr)_minmax(0,1fr)] gap-3">
                  <span>类别</span>
                  <span>风险</span>
                  <span>旧值</span>
                  <span>新值</span>
                </div>
                {data?.items.map((i) => (
                  <div
                    className="grid-row grid grid-cols-[140px_100px_minmax(0,1fr)_minmax(0,1fr)] items-start gap-3"
                    key={i.id}
                  >
                    <span className="font-medium text-ink">{i.change_category}</span>
                    <span>
                      <span className={severityBadge(i.severity)}>{i.severity}</span>
                    </span>
                    <pre className="min-w-0 whitespace-pre-wrap break-all font-mono text-xs text-slate-600">
                      {JSON.stringify(i.old_value, null, 2)}
                    </pre>
                    <pre className="min-w-0 whitespace-pre-wrap break-all font-mono text-xs text-slate-600">
                      {JSON.stringify(i.new_value, null, 2)}
                    </pre>
                  </div>
                ))}
              </div>
            </div>
          )}
        </section>
      </div>
    </main>
  );
}

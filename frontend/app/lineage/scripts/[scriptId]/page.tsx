"use client";

import { Download, SquareTerminal } from "lucide-react";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { LineageGraph } from "@/components/LineageGraph";
import { WorkspaceHeader } from "@/components/WorkspaceHeader";
import { LineageGraph as Graph, ScriptDependency, ScriptFile, ScriptVersion, apiDownload, apiGet } from "@/lib/api";

type Detail = ScriptFile & { versions: ScriptVersion[]; dependencies: ScriptDependency[] };

function statusBadge(status: string) {
  if (["approved", "success", "completed", "enabled"].includes(status)) return "badge-success";
  if (["failed", "rejected", "error"].includes(status)) return "badge-danger";
  if (["pending", "running", "processing"].includes(status)) return "badge-warning";
  if (["parsed", "draft", "info"].includes(status)) return "badge-info";
  return "badge-neutral";
}

export default function Page() {
  const { scriptId } = useParams<{ scriptId: string }>();
  const [data, setData] = useState<Detail | null>(null);
  const [graph, setGraph] = useState<Graph | null>(null);

  useEffect(() => {
    void Promise.all([
      apiGet<Detail>(`/scripts/${scriptId}`),
      apiGet<Graph>(`/scripts/${scriptId}/lineage?direction=both&depth=5`)
    ]).then(([a, b]) => {
      setData(a);
      setGraph(b);
    });
  }, [scriptId]);

  async function download() {
    const { blob, fileName } = await apiDownload(`/scripts/${scriptId}/export/change-impact-workbook`);
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = fileName;
    link.click();
    URL.revokeObjectURL(url);
  }

  return (
    <main>
      <WorkspaceHeader
        title={data?.relative_path || "脚本详情"}
        meta={`版本、依赖、warning 与源码证据`}
        actions={
          <button className="button-primary" onClick={download}>
            <Download size={16} />
            导出影响 Excel
          </button>
        }
      />
      <div className="mx-auto max-w-7xl space-y-5 p-4 lg:p-6">
        <section className="panel overflow-hidden">
          <div className="panel-header">
            <h2 className="text-[15px] font-semibold text-ink">版本</h2>
          </div>
          {data ? (
            <>
              <div className="grid-head grid grid-cols-[90px_140px_minmax(0,1fr)]">
                <span>版本</span>
                <span>解析状态</span>
                <span className="text-right">提交 / 哈希</span>
              </div>
              {data.versions.map((v) => (
                <div className="grid-row grid grid-cols-[90px_140px_minmax(0,1fr)] items-center" key={v.id}>
                  <strong className="text-ink">v{v.version_no}</strong>
                  <span>
                    <span className={statusBadge(v.parse_status)}>{v.parse_status}</span>
                  </span>
                  <span className="justify-self-end font-mono text-xs text-slate-500">
                    {v.git_commit_sha?.slice(0, 12) || v.file_hash.slice(0, 12)}
                  </span>
                  {v.warnings.length ? (
                    <ul className="col-span-full mt-2 list-disc pl-5 text-xs text-gold-700">
                      {v.warnings.map((w) => (
                        <li key={w}>{w}</li>
                      ))}
                    </ul>
                  ) : null}
                </div>
              ))}
            </>
          ) : null}
        </section>

        <section className="panel overflow-hidden">
          <div className="panel-header">
            <h2 className="text-[15px] font-semibold text-ink">Shell 依赖</h2>
          </div>
          {data?.dependencies.length ? (
            <>
              <div className="grid-head grid grid-cols-[150px_minmax(0,1fr)_150px]">
                <span>类型</span>
                <span>调用表达式</span>
                <span className="text-right">位置与置信度</span>
              </div>
              {data.dependencies.map((d) => (
                <div className="grid-row grid grid-cols-[150px_minmax(0,1fr)_150px] items-center" key={d.id}>
                  <strong className="text-ink">{d.dependency_type}</strong>
                  <span className="font-mono text-xs">{d.call_expression}</span>
                  <span className="justify-self-end text-xs text-slate-500">
                    行 {d.source_line_start || "-"} · {d.confidence_level}
                  </span>
                </div>
              ))}
            </>
          ) : (
            <div className="panel-body">
              <div className="empty-state">
                <SquareTerminal className="text-slate-300" size={28} />
                <p>无 Shell 调用依赖，脚本未发现外部调用</p>
              </div>
            </div>
          )}
        </section>

        <LineageGraph graph={graph} />
      </div>
    </main>
  );
}

"use client";

import { Unlink } from "lucide-react";
import { useEffect, useState } from "react";

import { useProjectWorkspace } from "@/components/ProjectContext";
import { WorkspaceHeader } from "@/components/WorkspaceHeader";
import { LineageNode, apiGet, apiPost } from "@/lib/api";

type Candidate = {
  id: number;
  candidate_type: string;
  candidate_id: number;
  score: number;
  match_reason: string;
  selected_flag: boolean;
};

type Unresolved = LineageNode & { candidates: Candidate[] };

export default function Page() {
  const { projectId } = useProjectWorkspace();
  const [items, setItems] = useState<Unresolved[]>([]);

  async function load() {
    if (projectId) setItems(await apiGet(`/projects/${projectId}/lineage/unresolved`));
  }

  useEffect(() => {
    void load();
  }, [projectId]);

  async function select(node: number, candidate: number) {
    await apiPost(`/lineage/nodes/${node}/resolution-candidates/${candidate}/select`, {});
    await load();
  }

  return (
    <main>
      <WorkspaceHeader title="未解析血缘节点" meta="多候选必须人工选择；选择结果可随时解绑" />
      <div className="mx-auto max-w-6xl p-4 lg:p-6">
        <section className="panel overflow-hidden">
          {items.length ? (
            items.map((node) => (
              <div className="border-b border-line px-5 py-4 last:border-0" key={node.id}>
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <strong className="font-mono text-sm text-ink">{node.logical_name}</strong>
                    <div className="text-xs text-slate-500">
                      {node.node_type} · 节点 #{node.id}
                    </div>
                  </div>
                  <span className="badge-warning">unresolved</span>
                </div>
                {node.candidates.length ? (
                  <div className="mt-3 grid gap-2">
                    {node.candidates.map((candidate) => (
                      <div
                        className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-line bg-white p-3 text-sm transition hover:bg-mist"
                        key={candidate.id}
                      >
                        <div>
                          <strong className="text-ink">
                            {candidate.candidate_type} #{candidate.candidate_id}
                          </strong>
                          <div className="text-xs text-slate-500">
                            {candidate.match_reason} · {Math.round(candidate.score * 100)}%
                          </div>
                        </div>
                        <button className="button-primary" onClick={() => select(node.id, candidate.id)}>
                          选择绑定
                        </button>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="mt-3 text-sm text-slate-500">当前无结构化候选，需要先同步元数据目录或导入业务模型。</p>
                )}
              </div>
            ))
          ) : (
            <div className="panel-body">
              <div className="empty-state">
                <Unlink className="text-slate-300" size={28} />
                <p>暂无未解析节点，血缘图中的对象均已完成绑定</p>
              </div>
            </div>
          )}
        </section>
      </div>
    </main>
  );
}

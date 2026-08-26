"use client";

import { History, ListChecks, Package, Play, RefreshCw, Upload } from "lucide-react";
import { useEffect, useState } from "react";

import { useProjectWorkspace } from "@/components/ProjectContext";
import { StatefulLink } from "@/components/StatefulLink";
import { WorkspaceHeader } from "@/components/WorkspaceHeader";
import { UatMetric, UatStatus, readError } from "@/components/uat/UatUi";
import { UatPack, UatRun, UatSuite, apiGet, apiPost, uploadForm } from "@/lib/api";
import { useProjectPermissions } from "@/lib/project-permissions";

export default function UatPage() {
  const { projectId } = useProjectWorkspace();
  const permissions = useProjectPermissions(projectId);
  const [suites, setSuites] = useState<UatSuite[]>([]);
  const [runs, setRuns] = useState<UatRun[]>([]);
  const [packs, setPacks] = useState<UatPack[]>([]);
  const [files, setFiles] = useState<File[]>([]);
  const [packName, setPackName] = useState("脱敏 UAT 材料包");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function load() {
    if (!projectId) {
      setSuites([]); setRuns([]); setPacks([]); return;
    }
    setLoading(true); setError("");
    try {
      const [nextSuites, nextRuns, nextPacks] = await Promise.all([
        apiGet<UatSuite[]>(`/projects/${projectId}/uat-suites`),
        apiGet<UatRun[]>(`/projects/${projectId}/uat-runs`),
        apiGet<UatPack[]>(`/projects/${projectId}/uat-packs`)
      ]);
      setSuites(nextSuites); setRuns(nextRuns); setPacks(nextPacks);
    } catch (reason) {
      setError(readError(reason));
    } finally {
      setLoading(false);
    }
  }

  async function uploadPack() {
    if (!projectId || !files.length) return;
    setLoading(true); setError("");
    try {
      const form = new FormData();
      form.append("pack_name", packName);
      files.forEach(file => form.append("files", file));
      const uploaded = await uploadForm<UatPack>(`/projects/${projectId}/uat-packs/upload`, form);
      await apiPost(`/uat-packs/${uploaded.id}/validate`, {});
      setFiles([]);
      await load();
    } catch (reason) {
      setError(readError(reason));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { void load(); }, [projectId]);
  const latest = runs[0];
  const summary = latest?.summary_json || {};

  return (
    <main>
      <WorkspaceHeader
        title="UAT 验收工作台"
        meta="材料、套件、执行轮次、问题闭环与签署"
        actions={
          <button className="button-secondary" onClick={load}>
            <RefreshCw size={15} />
            刷新
          </button>
        }
      />
      <div className="mx-auto max-w-7xl space-y-5 p-4 lg:p-6">
        {!projectId ? (
          <p className="rounded-lg border border-line bg-white px-3 py-2 text-sm text-slate-600">请先选择一个项目。</p>
        ) : null}
        {error ? (
          <p className="rounded-lg border border-coral-200 bg-coral-50 px-3 py-2 text-sm text-coral-700">{error}</p>
        ) : null}
        {projectId ? (
          <>
            <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-6">
              <UatMetric label="总 Case" value={summary.total_count || 0} />
              <UatMetric label="通过" value={summary.passed_count || 0} />
              <UatMetric label="失败" value={summary.failed_count || 0} />
              <UatMetric label="阻断" value={summary.blocked_count || 0} />
              <UatMetric label="待确认" value={summary.pending_count || 0} />
              <UatMetric label="最近状态" value={latest ? <UatStatusText value={latest.status} /> : "尚未执行"} />
            </section>

            <section className="grid gap-4 lg:grid-cols-[1fr_1.5fr]">
              {permissions.can("uat.manage") ? (
                <div className="panel h-fit">
                  <div className="panel-header">
                    <h2 className="text-[15px] font-semibold text-ink">上传脱敏 UAT 材料</h2>
                  </div>
                  <div className="panel-body">
                    <p className="text-xs text-slate-500">支持受控 XLSX、SQL、Shell、Markdown、JSON 或 ZIP；服务端执行整包限额、路径穿越和可执行文件检查。</p>
                    <input className="control mt-4" value={packName} onChange={event => setPackName(event.target.value)} aria-label="材料包名称" />
                    <input className="mt-3 block w-full text-sm" type="file" multiple onChange={event => setFiles(Array.from(event.target.files || []))} />
                    <button className="button-primary mt-4" disabled={loading || !files.length} onClick={uploadPack}>
                      <Upload size={15} />
                      上传并校验
                    </button>
                  </div>
                </div>
              ) : (
                <div className="panel p-4 text-sm text-slate-500">当前角色可查看材料清单，但无权上传或校验材料。</div>
              )}
              <div>
                <h2 className="mb-3 font-semibold text-ink">材料包清单</h2>
                {packs.length ? (
                  <div className="panel divide-y divide-line overflow-hidden">
                    {packs.map(pack => (
                      <div className="p-4" key={pack.id}>
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <b>{pack.pack_name}</b>
                          <UatStatus value={pack.status} />
                        </div>
                        <p className="mt-1 text-xs text-slate-500">
                          {pack.items.length} 个文件 · {pack.manifest_json.total_bytes || 0} bytes
                        </p>
                        {pack.validation_json.missing_material_types?.length ? (
                          <p className="mt-2 text-xs text-gold-700">缺少：{pack.validation_json.missing_material_types.join("、")}</p>
                        ) : null}
                        <div className="mt-2 flex flex-wrap gap-2">
                          {pack.items.slice(0, 8).map(item => (
                            <span className="badge-neutral" key={item.id}>{item.original_file_name}</span>
                          ))}
                        </div>
                      </div>
                    ))}
                  </div>
                ) : !loading ? (
                  <div className="empty-state">
                    <Package className="text-slate-300" size={28} />
                    <p>尚未上传材料包，先在左侧上传脱敏 UAT 材料</p>
                  </div>
                ) : null}
              </div>
            </section>

            <section>
              <h2 className="mb-3 font-semibold text-ink">测试套件</h2>
              {suites.length ? (
                <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                  {suites.map(item => (
                    <StatefulLink className="panel p-4 transition hover:border-pine" href={`/uat/suites/${item.id}`} key={item.id}>
                      <div className="flex justify-between gap-3">
                        <b>{item.suite_name}</b>
                        <span className="text-xs text-slate-500">{item.cases.length} Cases</span>
                      </div>
                      <p className="mt-2 line-clamp-2 text-sm text-slate-500">{item.description || "未填写说明"}</p>
                      <span className="mt-3 inline-flex items-center gap-1 text-sm font-medium text-pine">
                        <Play size={14} />
                        进入套件
                      </span>
                    </StatefulLink>
                  ))}
                </div>
              ) : !loading ? (
                <div className="empty-state">
                  <ListChecks className="text-slate-300" size={28} />
                  <p>暂无测试套件，系统套件初始化后会显示在这里</p>
                </div>
              ) : null}
            </section>

            <section>
              <h2 className="mb-3 font-semibold text-ink">最近执行</h2>
              {runs.length ? (
                <div className="panel divide-y divide-line overflow-hidden">
                  {runs.slice(0, 20).map(item => (
                    <StatefulLink className="flex flex-wrap items-center justify-between gap-3 p-4 transition-colors hover:bg-mist" href={`/uat/runs/${item.id}`} key={item.id}>
                      <div>
                        <b>{item.run_name}</b>
                        <div className="mt-1 text-xs text-slate-500">
                          第 {item.run_no} 轮 · {item.environment_name}
                        </div>
                      </div>
                      <UatStatus value={item.status} />
                    </StatefulLink>
                  ))}
                </div>
              ) : !loading ? (
                <div className="empty-state">
                  <History className="text-slate-300" size={28} />
                  <p>尚未执行 UAT，进入套件创建第一轮执行</p>
                </div>
              ) : null}
            </section>
          </>
        ) : null}
        {loading ? <p className="text-sm text-slate-500">正在加载 UAT 状态…</p> : null}
      </div>
    </main>
  );
}

function UatStatusText({ value }: { value: string }) {
  return <span className="text-base">{({ passed: "通过", failed: "失败", blocked: "阻断", running: "执行中", queued: "排队中" } as Record<string, string>)[value] || value}</span>;
}

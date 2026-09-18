"use client";

import { Copy, ListChecks, Play } from "lucide-react";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import Link from "next/link";

import { WorkspaceHeader } from "@/components/WorkspaceHeader";
import { StructuredDetails, UatStatus, readError } from "@/components/uat/UatUi";
import { UatRun, UatSuite, apiGet, apiPost } from "@/lib/api";
import { useProjectPermissions } from "@/lib/project-permissions";

export default function SuitePage() {
  const { suiteId } = useParams<{ suiteId: string }>();
  const router = useRouter();
  const [suite, setSuite] = useState<UatSuite | null>(null);
  const [name, setName] = useState("");
  const [message, setMessage] = useState("");
  const [review,setReview]=useState<{status:string;content_version:number;content_hash:string;pending_review:boolean;issue:string|null;tasks:{id:number;step_key:string;status:string}[]}|null>(null);
  const [reviewBusy,setReviewBusy]=useState(false);
  const permissions = useProjectPermissions(suite?.project_id);

  useEffect(() => {
    apiGet<UatSuite>(`/uat-suites/${suiteId}`).then(setSuite).catch(reason => setMessage(readError(reason)));
    apiGet<typeof review>(`/uat-suites/${suiteId}/requirement-review`).then(setReview).catch(reason=>setMessage(readError(reason)));
  }, [suiteId]);

  async function submitReview(){
    setReviewBusy(true);
    try{setReview(await apiPost(`/uat-suites/${suiteId}/requirement-review`,{}));}
    catch(reason){setMessage(readError(reason));}
    finally{setReviewBusy(false);}
  }

  async function createRun() {
    if (!suite) return;
    try {
      const run = await apiPost<UatRun>(`/uat-suites/${suite.id}/runs`, {
        run_name: name.trim() || `${suite.suite_name} 验收轮次`,
        environment_name: "uat",
        application_version: null,
        git_commit_sha: null
      });
      router.push(`/uat/runs/${run.id}`);
    } catch (reason) {
      setMessage(readError(reason));
    }
  }

  async function clone() {
    if (!suite) return;
    try {
      const item = await apiPost<UatSuite>(`/uat-suites/${suite.id}/clone`, { suite_name: `${suite.suite_name} 自定义副本` });
      router.push(`/uat/suites/${item.id}`);
    } catch (reason) {
      setMessage(readError(reason));
    }
  }

  return (
    <main>
      <WorkspaceHeader
        title={suite?.suite_name || "UAT 套件"}
        meta={suite ? `${suite.cases.length} 个测试案例 · ${suite.suite_type}` : "正在加载"}
      />
      <div className="mx-auto max-w-6xl space-y-5 p-4 lg:p-6">
        {review&&<section aria-label="需求规则测试项审核" className="space-y-3 border-b border-line pb-4 text-sm">
          <h2 className="font-semibold">固定需求内容 v{review.content_version} · {{draft:"待送审",in_review:"审核中",returned:"已退回",approved:"已审核"}[review.status]??review.status}</h2>
          <p className="break-all text-xs text-slate-500">内容摘要：{review.content_hash}</p>
          {review.pending_review&&<p role="alert" className="text-amber-800">待复核：{review.issue}</p>}
          {permissions.can("uat.manage")&&review.status==="draft"&&<button className="button-secondary" disabled={reviewBusy||review.pending_review} onClick={()=>void submitReview()}>提交测试项审核</button>}
          <div className="flex flex-wrap gap-3">{review.tasks.map(task=><Link key={task.id} className="text-teal-800 underline" href={`/tasks/${task.id}`}>{task.step_key==="technical_review"?"技术审核":"终审"} · {task.status}</Link>)}</div>
        </section>}
        {message ? (
          <p className="rounded-lg border border-coral-200 bg-coral-50 px-3 py-2 text-sm text-coral-700">{message}</p>
        ) : null}
        {suite && permissions.can("uat.execute") ? (
          <section className="panel flex flex-wrap gap-3 p-4">
            <input className="control min-w-64 flex-1" value={name} onChange={event => setName(event.target.value)} placeholder="本轮 UAT 名称" />
            <button className="button-primary" disabled={suite.suite_type==="requirement_rules"&&(!review||review.status!=="approved"||review.pending_review)} onClick={createRun}>
              <Play size={15} />
              创建执行轮次
            </button>
            {permissions.can("uat.manage") && suite.suite_type!=="requirement_rules" ? (
              <button className="button-secondary" onClick={clone}>
                <Copy size={15} />
                复制为自定义套件
              </button>
            ) : null}
          </section>
        ) : null}
        {suite ? (
          suite.cases.length ? (
            <section className="panel overflow-hidden">
              <div className="grid-head grid grid-cols-[130px_1fr_130px_110px] gap-3">
                <span>编号</span>
                <span>测试案例</span>
                <span>执行状态</span>
                <span>严重级</span>
              </div>
              {suite.cases.map(item => (
                <div className="grid-row grid grid-cols-[130px_1fr_130px_110px] items-center gap-3" key={item.id}>
                  <span className="text-xs text-slate-400">{item.case_code}</span>
                  <span>
                    <b>{item.case_name}</b>
                    <span className="mt-1 block text-sm text-slate-500">{item.description || "未填写说明"}</span>
                    {review&&<details className="mt-2 text-xs"><summary>固定规则、预期结果与证据</summary><StructuredDetails value={item.expected_result_json}/></details>}
                  </span>
                  <span>
                    <UatStatus value={item.execution_mode === "automatic" ? "queued" : "pending"} />
                  </span>
                  <span>
                    <span className="badge-neutral">{item.severity}</span>
                  </span>
                </div>
              ))}
            </section>
          ) : (
            <div className="empty-state">
              <ListChecks className="text-slate-300" size={28} />
              <p>该套件还没有测试案例</p>
            </div>
          )
        ) : null}
        {!suite && !message ? (
          <p className="rounded-lg border border-line bg-white px-3 py-2 text-sm text-slate-600">正在读取套件…</p>
        ) : null}
      </div>
    </main>
  );
}

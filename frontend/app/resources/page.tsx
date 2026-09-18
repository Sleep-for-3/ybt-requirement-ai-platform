"use client";

import { ArrowRight, Clock3, Database, FileCheck2, ShieldAlert } from "lucide-react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";

import { useProjectWorkspace } from "@/components/ProjectContext";
import { WorkspaceHeader } from "@/components/WorkspaceHeader";
import { apiGet } from "@/lib/api";
import { canViewNavigationAudience, navigationAccessForProject, type NavigationAudience } from "@/lib/navigation-contract.mjs";

type ResourceRow={key:string;title:string;href:string;description:string;count:number;coverage:string;updated_at?:string|null;statuses:{label:string;count:number}[];audience:NavigationAudience|"all";group:"资料治理"|"数据资产"};
type Summary={resources:ResourceRow[];recent_changes:{kind:string;title:string;updated_at:string;href:string}[];pending_items:{type:string;label:string;count:number;href:string}[]};

function dateTime(value?:string|null){return value?new Date(value).toLocaleString("zh-CN",{hour12:false}):"暂无变更";}

export default function Page(){
  const {projectId}=useProjectWorkspace();
  const auth=useQuery({queryKey:["resource-navigation-access",projectId],queryFn:({signal})=>apiGet<{effective_project_permissions?:Record<string,string[]>;capabilities?:{can_view_admin?:boolean;can_view_institution_cockpit?:boolean}}>("/auth/me",{signal})});
  const summary=useQuery({queryKey:["resource-governance",projectId],enabled:Boolean(projectId),queryFn:({signal})=>apiGet<Summary>(`/projects/${projectId}/resources/governance-summary`,{signal})});
  const access=navigationAccessForProject(auth.data,projectId);
  const visible=(summary.data?.resources||[]).filter(item=>canViewNavigationAudience(item.audience==="all"?undefined:item.audience,access));
  return <main>
    <WorkspaceHeader title="资料与数据" meta="查依据、判权威、看版本，并集中处理资料与数据治理事项。" />
    <div className="flex gap-3 px-6 pt-4"><Link className="btn-secondary" href="/resources/architecture">数据架构与表归属</Link><Link className="btn-primary" href="/resources/import">统一批量导入</Link></div>
    <div className="mx-auto max-w-6xl space-y-6 p-4 lg:p-6">
      <div className="grid overflow-hidden rounded-xl border border-line bg-white md:grid-cols-2 md:divide-x md:divide-line">
        <section className="space-y-4 border-b border-line p-5 md:border-b-0 md:p-6"><h2 className="text-xl font-semibold">问监管与业务知识</h2><p className="text-sm leading-6 text-slate-600">只从当前生效、已审核并对本项目可见的资料中寻找依据。</p><p className="text-sm text-slate-500">例如：客户证件类型的报送范围和监管依据是什么？</p><Link className="button-primary" href="/knowledge/ask?mode=regulatory">进入监管知识问答</Link></section>
        <section className="space-y-4 p-5 md:p-6"><h2 className="text-xl font-semibold">查数据库字段与血缘</h2><p className="text-sm leading-6 text-slate-600">查来源系统、库、Schema、表、字段、关联和加工规则。</p><p className="text-sm text-slate-500">例如：CERT_TYPE 来自哪个系统和表？有哪些码值转换？</p><Link className="button-primary" href="/knowledge/ask?mode=data_field">进入数据字段与血缘问答</Link></section>
      </div>
      {!projectId?<div className="empty-state"><Database size={28}/><p>请先在顶部选择项目，再查看真实治理状态。</p></div>:null}
      {summary.isLoading?<p role="status" className="panel p-5">正在汇总资料与数据治理状态…</p>:null}
      {summary.isError?<p role="alert" className="rounded-lg border border-red-200 bg-red-50 p-4 text-red-800">治理状态加载失败。<button className="ml-2 underline" onClick={()=>void summary.refetch()}>重试</button></p>:null}
      {(["资料治理","数据资产"] as const).map(group=>{
        const rows=visible.filter(item=>item.group===group);if(!rows.length)return null;
        return <section className="panel overflow-hidden" key={group}><div className="panel-header"><div><h2 className="text-lg font-semibold">{group}</h2><p className="mt-1 text-sm text-slate-500">{group==="资料治理"?"版本、生效、审核与证据状态":"只读连接、目录、系统和集市覆盖"}</p></div></div>
          <div className="divide-y divide-line">{rows.map(item=><Link href={item.href} key={item.key} className="group grid min-w-0 gap-3 p-4 hover:bg-mist focus-visible:outline focus-visible:outline-2 focus-visible:outline-amber-500 sm:grid-cols-[minmax(0,1fr)_140px_190px_28px] sm:items-center">
            <div className="min-w-0"><h3 className="font-semibold text-ink">{item.title}</h3><p className="mt-1 break-words text-sm text-slate-600">{item.description}</p></div>
            <div><span className="text-2xl font-semibold tabular-nums">{item.count}</span><span className="ml-1 text-xs text-slate-500">条记录</span></div>
            <div className="min-w-0 text-sm"><p className="break-words font-medium text-slate-700">{item.count?item.coverage:"暂无数据"}</p><p className="mt-1 flex items-center gap-1 text-xs text-slate-500"><Clock3 size={12}/>{dateTime(item.updated_at)}</p>{item.statuses.length?<div className="mt-2 flex flex-wrap gap-1">{item.statuses.map(status=><span className="badge-warning" key={status.label}>{status.label} {status.count}</span>)}</div>:null}</div>
            <ArrowRight aria-hidden className="hidden text-slate-400 transition-transform group-hover:translate-x-1 sm:block" size={18}/>
          </Link>)}</div></section>;
      })}
      {summary.data?<div className="grid gap-6 lg:grid-cols-2">
        <section className="panel p-5"><div className="mb-4 flex items-center gap-2"><Clock3 size={18}/><h2 className="font-semibold">最近变更</h2></div>{summary.data.recent_changes.length?<ol className="space-y-3">{summary.data.recent_changes.map((item,index)=><li key={`${item.kind}-${index}`}><Link className="flex min-w-0 items-start justify-between gap-3 rounded-lg p-2 hover:bg-mist" href={item.href}><span className="min-w-0"><span className="badge-neutral">{item.kind}</span><span className="ml-2 break-words text-sm font-medium">{item.title}</span></span><time className="shrink-0 text-xs text-slate-500">{dateTime(item.updated_at)}</time></Link></li>)}</ol>:<p className="text-sm text-slate-500">暂无可展示的真实变更。</p>}</section>
        <section className="panel p-5"><div className="mb-4 flex items-center gap-2"><ShieldAlert size={18}/><h2 className="font-semibold">待处理事项</h2></div>{summary.data.pending_items.length?<ul className="space-y-3">{summary.data.pending_items.map(item=><li key={item.type}><Link className="flex items-center justify-between rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm hover:bg-amber-100" href={item.href}><span>{item.label}</span><strong>{item.count}</strong></Link></li>)}</ul>:<div className="flex items-center gap-2 text-sm text-slate-500"><FileCheck2 size={18}/><span>当前没有待审核、解析失败或待激活事项。</span></div>}</section>
      </div>:null}
    </div>
  </main>;
}

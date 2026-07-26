"use client";

import { CheckCircle2, Circle, LockKeyhole } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { WorkspaceHeader } from "@/components/WorkspaceHeader";
import { apiGet, OnboardingStep, ProjectOnboarding } from "@/lib/api";

export default function OnboardingPage(){
  const {projectId}=useParams<{projectId:string}>();
  const [data,setData]=useState<ProjectOnboarding|null>(null);
  const [error,setError]=useState("");
  useEffect(()=>{apiGet<ProjectOnboarding>(`/projects/${projectId}/onboarding`).then(setData).catch((reason)=>setError(reason instanceof Error?reason.message:"加载失败"));},[projectId]);
  const completed=data?.steps.filter(item=>item.status==="completed").length||0;
  return <main><WorkspaceHeader title="项目初始化向导" meta="状态直接来自项目数据，刷新后自动恢复" actions={<Link className="button-secondary" href={`/projects/${projectId}/readiness`}>查看完整准备度</Link>}/><div className="mx-auto max-w-4xl space-y-5 p-4 lg:p-6">{error?<div className="panel border-red-200 p-4 text-sm text-red-700">{error}</div>:null}<section className="panel p-5"><div className="flex justify-between text-sm"><span>初始化进度</span><span className="font-semibold">{completed} / 10</span></div><div className="mt-3 h-2 overflow-hidden rounded-full bg-slate-100"><div className="h-full bg-pine" style={{width:`${completed*10}%`}}/></div></section><section className="space-y-3">{data?.steps.map(item=><StepCard item={item} key={item.key}/>)||<div className="panel p-5 text-sm text-slate-500">正在读取项目状态…</div>}</section></div></main>;
}

function StepCard({item}:{item:OnboardingStep}){const Icon=item.status==="completed"?CheckCircle2:item.status==="blocked"?LockKeyhole:Circle;return <article className="panel flex gap-4 p-4"><div className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-full ${item.status==="completed"?"bg-emerald-50 text-emerald-700":item.status==="blocked"?"bg-amber-50 text-amber-700":"bg-slate-100 text-slate-500"}`}><Icon size={18}/></div><div className="min-w-0 flex-1"><div className="flex flex-wrap items-center gap-2"><h2 className="font-semibold">{item.step}. {item.title}</h2>{item.skippable?<span className="rounded bg-slate-100 px-2 py-0.5 text-xs text-slate-500">可跳过</span>:<span className="rounded bg-pine/10 px-2 py-0.5 text-xs text-pine">必填</span>}</div>{item.blocking_reasons.map(reason=><p className="mt-2 text-sm text-amber-800" key={reason.code}>{reason.message}</p>)}{item.next_action?<p className="mt-2 text-sm text-slate-600">下一步：{item.next_action}</p>:null}{item.links[0]&&item.status!=="completed"?<Link className="mt-3 inline-block text-sm font-medium text-pine hover:underline" href={item.links[0]}>开始处理</Link>:null}</div></article>}

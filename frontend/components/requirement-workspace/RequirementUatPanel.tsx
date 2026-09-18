"use client";

import Link from "next/link";
import { useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ListChecks } from "lucide-react";
import { apiGet, apiPost } from "@/lib/api";
import { useProjectPermissions } from "@/lib/project-permissions";

type LinkRecord = {id:number;suite_id:number;content_version:number;status:string;pending_review:boolean;issue:string|null};
const labels:Record<string,string>={draft:"待送审",in_review:"审核中",returned:"已退回",approved:"已审核"};

export function RequirementUatPanel({projectId,requirementId,contentVersion,dirty}:{
  projectId:number;requirementId:number;contentVersion:number;dirty:boolean;
}) {
  const permissions=useProjectPermissions(projectId);
  const base=`/projects/${projectId}/requirements/${requirementId}/uat-suites`;
  const links=useQuery({queryKey:["requirement-uat",projectId,requirementId,contentVersion],enabled:permissions.can("uat.view"),
    queryFn:({signal})=>apiGet<LinkRecord[]>(base,{signal})});
  const [busy,setBusy]=useState(false),[error,setError]=useState("");
  const flight=useRef(false);
  async function create(){
    if(flight.current||dirty)return;
    flight.current=true;setBusy(true);setError("");
    try{await apiPost(base,{expected_content_version:contentVersion});await links.refetch();}
    catch(e){setError(e instanceof Error?e.message:"测试项生成失败");}
    finally{flight.current=false;setBusy(false);}
  }
  if(!permissions.can("uat.view"))return null;
  return <section className="panel mb-3 space-y-3 p-4 text-xs" aria-label="需求规则验收">
    <h2 className="text-sm font-semibold">需求规则验收</h2>
    {permissions.can("uat.manage")&&<button className="button-secondary" disabled={busy||dirty||!contentVersion} onClick={()=>void create()}><ListChecks size={15}/>从确认规则生成待审核测试项</button>}
    {error&&<p role="alert" className="text-red-700">{error}</p>}
    {links.isError&&<p role="alert">无法读取关联测试项。<button onClick={()=>void links.refetch()}>重试</button></p>}
    {links.data?.map(link=><div key={link.id} className="space-y-1 border-t pt-2">
      <Link className="text-teal-800 underline" href={`/uat/suites/${link.suite_id}`}>内容 v{link.content_version} · {labels[link.status]??link.status}</Link>
      {link.pending_review&&<p className="text-amber-800">待复核：{link.issue}</p>}
    </div>)}
  </section>;
}

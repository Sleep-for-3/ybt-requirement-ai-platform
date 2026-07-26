"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { Activity, CheckCircle2, Cloud, Cpu, Play, Power, PowerOff, TriangleAlert } from "lucide-react";

import { useProjectWorkspace } from "@/components/ProjectContext";
import { WorkspaceHeader } from "@/components/WorkspaceHeader";
import { apiGet, apiPatch, apiPost } from "@/lib/api";

type ProviderStatus = {
  provider:string;model?:string|null;base_url_host?:string|null;is_mock:boolean;is_local?:boolean;
  api_key_env_name?:string|null;api_key_present?:boolean;configuration_status:string;last_connection_test?:{status:string;tested_at:string;error?:string|null}|null;
};
type RuntimeStatus = {
  llm:ProviderStatus;embedding:ProviderStatus;vector_store:{provider:string;is_mock:boolean;configuration_status:string};
  issues:Array<{component:string;message:string}>;
  observability:{last_success_at?:string|null;last_failure_at?:string|null;average_latency_ms:number;recent_token_usage:Record<string,unknown>};
};
type Profile = {
  id:number;profile_name:string;provider_type:string;base_url?:string|null;base_url_host?:string|null;model_name?:string|null;
  api_key_env_name?:string|null;api_key_present:boolean;local_only:boolean;enabled:boolean;
  config_json:{last_connection_test?:{status:string;tested_at:string;error?:string|null}|null};
};
type ModelCall = {id:number;prompt_key:string;provider?:string|null;model_name?:string|null;status:string;latency_ms:number;token_usage:Record<string,unknown>;error_type?:string|null;created_at:string};

const providers = ["mock", "openai", "openai_compatible", "local_vllm", "local_ollama_compatible"];

export default function Page() {
  const { projectId } = useProjectWorkspace();
  const [runtime,setRuntime] = useState<RuntimeStatus|null>(null);
  const [profiles,setProfiles] = useState<Profile[]>([]);
  const [calls,setCalls] = useState<ModelCall[]>([]);
  const [message,setMessage] = useState("");
  const [busy,setBusy] = useState<string|null>(null);
  const [editing,setEditing] = useState<Profile|null>(null);

  const reload = useCallback(async () => {
    const [status,items] = await Promise.all([apiGet<RuntimeStatus>("/ai-runtime/status"),apiGet<Profile[]>("/model-profiles")]);
    setRuntime(status);setProfiles(items);
    if(projectId) {
      const logs = await apiGet<{items:ModelCall[]}>(`/projects/${projectId}/model-calls?page_size=10`);
      setCalls(logs.items);
    } else setCalls([]);
  },[projectId]);
  useEffect(()=>{void reload().catch(error=>setMessage(readError(error)));},[reload]);

  async function save(event:FormEvent<HTMLFormElement>) {
    event.preventDefault();setBusy("save");setMessage("");
    const form = new FormData(event.currentTarget);
    const provider = String(form.get("provider_type"));
    const payload = {
      profile_name:String(form.get("profile_name")),
      provider_type:provider,
      base_url:String(form.get("base_url")||"")||null,
      model_name:String(form.get("model_name")||"")||null,
      api_key_env_name:String(form.get("api_key_env_name")||"")||null,
      local_only:provider.startsWith("local_"),
      config_json:{json_mode:true,max_output_tokens:2048,temperature:.2,timeout_seconds:60,retry_count:2},
    };
    try {
      if(editing) await apiPatch(`/model-profiles/${editing.id}`,payload);
      else await apiPost("/model-profiles",payload);
      setEditing(null);event.currentTarget.reset();setMessage(editing?"Profile 已更新":"Profile 已创建，连接测试不会自动激活");
      await reload();
    } catch(error) {setMessage(readError(error));} finally {setBusy(null);}
  }
  async function action(profile:Profile,kind:"test"|"activate"|"disable") {
    setBusy(`${kind}-${profile.id}`);setMessage("");
    try {
      const result = await apiPost<Record<string,unknown>>(`/model-profiles/${profile.id}/${kind}`,{});
      setMessage(kind==="test"?`连接成功，耗时 ${result.latency_ms ?? "-"} ms`:`Profile 已${kind==="activate"?"激活":"停用"}`);
      await reload();
    } catch(error) {setMessage(readError(error));} finally {setBusy(null);}
  }

  return <main>
    <WorkspaceHeader title="AI 运行环境" meta="聊天模型、Embedding、连接测试与调用可观测性；密钥只从 backend/.env 读取" />
    <div className="mx-auto max-w-[1400px] space-y-5 p-6">
      {message?<div className="panel border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">{message}</div>:null}
      {runtime?<section className="grid gap-4 md:grid-cols-3">
        <StatusCard title="聊天模型" status={runtime.llm} icon={<Cloud size={18}/>} />
        <StatusCard title="Embedding" status={runtime.embedding} icon={<Cpu size={18}/>} />
        <div className="panel p-4"><div className="flex items-center gap-2 font-semibold"><Activity size={18}/>向量存储</div><div className="mt-3 text-lg">{runtime.vector_store.provider}</div><Badge mock={runtime.vector_store.is_mock} configured={runtime.vector_store.configuration_status==="configured"}/>{runtime.vector_store.is_mock?<p className="mt-2 text-sm text-amber-700">当前向量语义能力为模拟模式，不代表生产向量检索。</p>:null}</div>
      </section>:null}
      {runtime?<section className="panel p-4"><h2 className="font-semibold">调用状态</h2><div className="mt-3 grid gap-3 text-sm md:grid-cols-4"><Metric label="最近成功" value={formatTime(runtime.observability.last_success_at)}/><Metric label="最近失败" value={formatTime(runtime.observability.last_failure_at)}/><Metric label="平均延迟" value={`${runtime.observability.average_latency_ms} ms`}/><Metric label="最近 Token" value={tokenText(runtime.observability.recent_token_usage)}/></div>{runtime.issues.length?<div className="mt-4 rounded-md bg-rose-50 p-3 text-sm text-rose-800"><TriangleAlert className="mr-2 inline" size={16}/>{runtime.issues.map(item=>item.message).join("；")}</div>:null}</section>:null}

      <section className="grid gap-5 lg:grid-cols-[360px_1fr]">
        <form className="panel h-fit space-y-3 p-4" onSubmit={save}>
          <h2 className="font-semibold">{editing?"编辑 Profile":"新建 Profile"}</h2>
          <input className="control" name="profile_name" placeholder="Profile 名称" defaultValue={editing?.profile_name||""} key={`name-${editing?.id||0}`} required/>
          <select className="control" name="provider_type" defaultValue={editing?.provider_type||"mock"} key={`provider-${editing?.id||0}`}>{providers.map(item=><option key={item}>{item}</option>)}</select>
          <input className="control" name="base_url" placeholder="Base URL（仅 http/https）" defaultValue={editing?.base_url||""} key={`url-${editing?.id||0}`}/>
          <input className="control" name="model_name" placeholder="模型名称" defaultValue={editing?.model_name||""} key={`model-${editing?.id||0}`}/>
          <input className="control" name="api_key_env_name" placeholder="API Key 环境变量名，如 OPENAI_API_KEY" defaultValue={editing?.api_key_env_name||""} key={`env-${editing?.id||0}`}/>
          <p className="text-xs text-slate-500">API Key 不在页面录入或保存。请在 <code>backend/.env</code> 中设置上面的环境变量。</p>
          <div className="flex gap-2"><button className="button-primary flex-1" disabled={busy==="save"}>{busy==="save"?"保存中…":editing?"保存修改":"创建"}</button>{editing?<button type="button" className="button-secondary" onClick={()=>setEditing(null)}>取消</button>:null}</div>
        </form>
        <div className="panel overflow-hidden">
          {profiles.length?profiles.map(profile=><div className="border-b border-line p-4 last:border-0" key={profile.id}><div className="flex flex-wrap items-start justify-between gap-3"><div><div className="flex items-center gap-2 font-medium">{profile.profile_name}{profile.enabled?<span className="rounded bg-emerald-100 px-2 py-0.5 text-xs text-emerald-800">当前启用</span>:null}</div><div className="mt-1 text-sm text-slate-600">{profile.provider_type} · {profile.model_name||"未配置模型"} · {profile.base_url_host||"无外部地址"}</div><div className="mt-1 text-xs text-slate-500">Key 环境变量：{profile.api_key_env_name||"不需要"} · {profile.api_key_present?"已配置":"未配置"} · {profile.local_only?"本地模型":"外部模型"}</div>{profile.config_json.last_connection_test?<div className="mt-1 text-xs text-slate-500">最近测试：{profile.config_json.last_connection_test.status} / {formatTime(profile.config_json.last_connection_test.tested_at)}</div>:null}</div><div className="flex flex-wrap gap-2"><button className="button-secondary" onClick={()=>setEditing(profile)}>编辑</button><button className="button-secondary" disabled={busy===`test-${profile.id}`} onClick={()=>void action(profile,"test")}><Play size={15}/>{busy===`test-${profile.id}`?"测试中…":"测试连接"}</button>{profile.enabled?<button className="button-danger" onClick={()=>void action(profile,"disable")}><PowerOff size={15}/>停用</button>:<button className="button-primary" onClick={()=>void action(profile,"activate")}><Power size={15}/>激活</button>}</div></div></div>):<div className="p-8 text-center text-sm text-slate-500">暂无数据库 Profile，系统使用 backend/.env 的运行配置。</div>}
        </div>
      </section>

      <section className="panel overflow-hidden"><div className="panel-header"><h2 className="font-semibold">当前项目最近模型调用</h2></div><div className="overflow-x-auto"><table className="w-full min-w-[800px] text-left text-sm"><thead className="bg-slate-50 text-slate-600"><tr>{["时间","Prompt","Provider / 模型","状态","延迟","Token / 错误"].map(item=><th className="px-4 py-3" key={item}>{item}</th>)}</tr></thead><tbody>{calls.map(call=><tr className="border-t border-line" key={call.id}><td className="px-4 py-3">{formatTime(call.created_at)}</td><td className="px-4 py-3">{call.prompt_key}</td><td className="px-4 py-3">{call.provider||"-"} / {call.model_name||"-"}</td><td className="px-4 py-3">{call.status}</td><td className="px-4 py-3">{call.latency_ms} ms</td><td className="px-4 py-3">{call.error_type||tokenText(call.token_usage)}</td></tr>)}{!calls.length?<tr><td className="px-4 py-8 text-center text-slate-500" colSpan={6}>选择项目后显示调用摘要；页面不会展示完整输入或输出。</td></tr>:null}</tbody></table></div></section>
    </div>
  </main>;
}

function StatusCard({title,status,icon}:{title:string;status:ProviderStatus;icon:React.ReactNode}) {return <div className="panel p-4"><div className="flex items-center gap-2 font-semibold">{icon}{title}</div><div className="mt-3 text-lg">{status.model||"未配置"}</div><div className="text-sm text-slate-500">{status.provider} · {status.base_url_host||"无外部地址"}</div><div className="mt-2"><Badge mock={status.is_mock} configured={status.configuration_status==="configured"}/></div><div className="mt-2 text-xs text-slate-500">{status.is_local?"本地模型":"外部模型"} · Key {status.api_key_present?"已配置":"未配置或不需要"}</div>{status.is_mock&&title==="Embedding"?<p className="mt-2 text-sm text-amber-700">Embedding 仍为 Mock，可与真实聊天模型独立组合。</p>:null}</div>}
function Badge({mock,configured}:{mock:boolean;configured:boolean}) {if(mock)return <span className="inline-flex rounded bg-amber-100 px-2 py-1 text-xs font-medium text-amber-800">Mock 模式</span>;return configured?<span className="inline-flex items-center gap-1 rounded bg-emerald-100 px-2 py-1 text-xs font-medium text-emerald-800"><CheckCircle2 size={13}/>真实模型已配置</span>:<span className="inline-flex rounded bg-rose-100 px-2 py-1 text-xs font-medium text-rose-800">配置不完整</span>}
function Metric({label,value}:{label:string;value:string}) {return <div><div className="text-slate-500">{label}</div><div className="mt-1 font-medium">{value}</div></div>}
function formatTime(value?:string|null) {return value?new Date(value).toLocaleString():"暂无";}
function tokenText(usage:Record<string,unknown>) {return usage.usage_available===false?"usage unavailable":String(usage.total_tokens??"usage unavailable");}
function readError(error:unknown) {if(!(error instanceof Error))return "操作失败";try{const body=JSON.parse(error.message);return body.detail||error.message;}catch{return error.message;}}

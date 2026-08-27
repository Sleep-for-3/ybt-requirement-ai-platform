"use client";

import { Check, ChevronLeft, ChevronRight, Database, LockKeyhole, RefreshCw, Server } from "lucide-react";
import { FormEvent, useEffect, useMemo, useState } from "react";

import { ModalDialog } from "@/components/feedback/ModalDialog";
import {
  BackgroundJobSummary,
  DataSource,
  DataSourceConnectionDiagnostic,
  DataSourceConnector,
  MetadataSyncTask,
  apiGet,
  apiPost
} from "@/lib/api";

type ConnectionForm = {
  name:string; display_name:string; description:string; host:string; port:string;
  database_name:string; service_name:string; schema_name:string; username:string; password:string;
  ssl_mode:string; oracle_identifier_type:string; odbc_driver:string;
};

const EMPTY_FORM: ConnectionForm = {
  name:"", display_name:"", description:"", host:"", port:"", database_name:"", service_name:"",
  schema_name:"", username:"", password:"", ssl_mode:"prefer", oracle_identifier_type:"service_name",
  odbc_driver:"ODBC Driver 18 for SQL Server"
};

const STEP_LABELS = ["选择类型", "连接检查", "纳管范围", "确认创建"];

export function DatasourceWizard({
  projectId, onCreated, onDirtyChange, onBusyChange, onRequestClose
}: {
  projectId:number;
  onCreated:(datasource:DataSource, outcome:{syncSubmitted:boolean; message?:string})=>void;
  onDirtyChange:(dirty:boolean)=>void;
  onBusyChange:(busy:boolean)=>void;
  onRequestClose:()=>void;
}) {
  const [connectors, setConnectors] = useState<DataSourceConnector[]>([]);
  const [loadingRegistry, setLoadingRegistry] = useState(true);
  const [registryError, setRegistryError] = useState("");
  const [connectorType, setConnectorType] = useState("");
  const [form, setForm] = useState<ConnectionForm>(EMPTY_FORM);
  const [step, setStep] = useState(0);
  const [diagnostic, setDiagnostic] = useState<DataSourceConnectionDiagnostic | null>(null);
  const [selectedSchemas, setSelectedSchemas] = useState<string[]>([]);
  const [testing, setTesting] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const connector = connectors.find((item) => item.engine_type === connectorType) || null;
  const busy = testing || saving;

  useEffect(() => {
    const controller = new AbortController();
    setLoadingRegistry(true);
    void apiGet<DataSourceConnector[]>(`/projects/${projectId}/datasource-connectors`, {signal:controller.signal})
      .then((items) => { if (!controller.signal.aborted) setConnectors(items); })
      .catch((reason) => { if (!controller.signal.aborted) setRegistryError(reason instanceof Error ? reason.message : "Connector Registry 加载失败"); })
      .finally(() => { if (!controller.signal.aborted) setLoadingRegistry(false); });
    return () => controller.abort();
  }, [projectId]);

  useEffect(() => { onBusyChange(busy); }, [busy, onBusyChange]);

  function choose(item:DataSourceConnector) {
    if (item.status !== "available") return;
    setConnectorType(item.engine_type);
    setForm({...EMPTY_FORM, port:item.default_port ? String(item.default_port) : ""});
    setDiagnostic(null); setSelectedSchemas([]); setError(""); onDirtyChange(true);
  }

  function change(key:keyof ConnectionForm, value:string) {
    setForm((current) => ({...current,[key]:value}));
    setDiagnostic(null); setSelectedSchemas([]); setError(""); onDirtyChange(true);
  }

  const payload = useMemo(() => connector ? buildPayload(connector, form, selectedSchemas) : null, [connector, form, selectedSchemas]);

  async function inspectConnection(event:FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!payload) return;
    setTesting(true); setError(""); setDiagnostic(null);
    try {
      const result = await apiPost<DataSourceConnectionDiagnostic>(`/projects/${projectId}/datasources/connection-inspect`, payload);
      setDiagnostic(result);
      if (result.status === "success") {
        setSelectedSchemas(result.schemas);
        setStep(2);
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "连接检查失败");
    } finally { setTesting(false); }
  }

  async function createAndSync() {
    if (!payload || !diagnostic || diagnostic.status !== "success") return;
    setSaving(true); setError("");
    let createdDatasource:DataSource | null = null;
    try {
      const datasource = await apiPost<DataSource>(`/projects/${projectId}/datasources`, buildPayload(connector!, form, selectedSchemas));
      createdDatasource = datasource;
      const persistedCheck = await apiPost<DataSourceConnectionDiagnostic>(`/datasources/${datasource.id}/test`, {});
      if (persistedCheck.status !== "success") throw new Error(persistedCheck.message);
      createdDatasource = {...datasource, last_test_status:persistedCheck.status, last_test_message:persistedCheck.message, last_database_version:persistedCheck.database_version, last_discovered_schemas_json:persistedCheck.schemas};
      await apiPost<MetadataSyncTask | BackgroundJobSummary>(`/datasources/${datasource.id}/metadata-sync`, {
        sync_mode:"full", schema_names:selectedSchemas, include_views:true
      });
      onDirtyChange(false);
      onCreated(createdDatasource, {syncSubmitted:true});
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : "数据源创建或首次同步失败";
      if (createdDatasource) {
        onDirtyChange(false);
        onCreated(createdDatasource, {syncSubmitted:false, message});
      } else {
        setError(message);
      }
    } finally { setSaving(false); }
  }

  return (
    <ModalDialog description="按 Connector 能力完成 Driver 检测、连接认证、只读策略、Schema 发现和首次元数据同步。" onClose={onRequestClose} open title="新建数据源">
      <ol className="mb-5 grid grid-cols-4 gap-1" aria-label="创建进度">{STEP_LABELS.map((label,index)=><li className={`rounded-lg px-2 py-2 text-center text-[11px] ${index===step?"bg-pine-600 font-semibold text-white":index<step?"bg-pine-50 text-pine-700":"bg-slate-50 text-slate-400"}`} key={label}>{index+1}. {label}</li>)}</ol>
      {error ? <p className="mb-4 rounded-lg border border-coral-200 bg-coral-50 px-3 py-2 text-sm text-coral-700" role="alert">{error}</p> : null}
      {step===0 ? <section>
        {loadingRegistry ? <p className="rounded-lg bg-slate-50 px-3 py-5 text-sm text-slate-500">正在检测服务端 Connector 与 Driver…</p> : null}
        {registryError ? <p className="rounded-lg border border-coral-200 bg-coral-50 px-3 py-3 text-sm text-coral-700" role="alert">{registryError}</p> : null}
        <div className="grid gap-2 sm:grid-cols-2">{connectors.map((item)=><button className={`rounded-xl border p-3 text-left transition ${connectorType===item.engine_type?"border-pine-500 bg-pine-50":"border-line bg-white hover:border-pine-200"} disabled:cursor-not-allowed disabled:bg-slate-50 disabled:opacity-65`} disabled={item.status!=="available"} key={item.engine_type} onClick={()=>choose(item)} type="button"><span className="flex items-center gap-2 font-medium text-ink"><Database size={16}/>{item.label}</span><span className="mt-1 block text-xs text-slate-500">{connectorStatus(item)}</span><span className="mt-2 flex flex-wrap gap-1">{item.drivers.map((driver)=><span className={driver.installed?"badge-success":"badge-neutral"} key={driver.module}>{driver.label} · {driver.installed?"可用":"未安装"}</span>)}</span></button>)}</div>
        <div className="mt-4 flex justify-end"><button className="button-primary" disabled={!connector} onClick={()=>setStep(1)} type="button">填写连接参数<ChevronRight size={16}/></button></div>
      </section> : null}
      {step===1 && connector ? <form className="space-y-4" onSubmit={inspectConnection}>
        <div className="grid gap-3 sm:grid-cols-2"><Field label="连接标识" required><input className="control" onChange={(e)=>change("name",e.target.value)} pattern="[a-z][a-z0-9_]{2,63}" placeholder="例如 ecif_readonly" required value={form.name}/></Field><Field label="显示名称"><input className="control" onChange={(e)=>change("display_name",e.target.value)} placeholder="供使用者识别" value={form.display_name}/></Field></div>
        {connector.engine_type==="sqlite" ? <Field label="SQLite 数据库路径" required><input className="control" onChange={(e)=>change("database_name",e.target.value)} placeholder="脱敏测试库的绝对路径" required value={form.database_name}/></Field> : <>
          <div className="grid gap-3 sm:grid-cols-[1fr_120px]"><Field label="主机" required><input className="control" onChange={(e)=>change("host",e.target.value)} required value={form.host}/></Field><Field label="端口" required><input className="control" min={1} max={65535} onChange={(e)=>change("port",e.target.value)} required type="number" value={form.port}/></Field></div>
          {connector.engine_type==="oracle" ? <div className="grid gap-3 sm:grid-cols-2"><Field label="Oracle 标识类型"><select className="control" onChange={(e)=>change("oracle_identifier_type",e.target.value)} value={form.oracle_identifier_type}><option value="service_name">Service Name</option><option value="sid">SID</option></select></Field><Field label="Service Name / SID" required><input className="control" onChange={(e)=>change("service_name",e.target.value)} required value={form.service_name}/></Field></div> : <Field label={connector.database_label} required><input className="control" onChange={(e)=>change("database_name",e.target.value)} required value={form.database_name}/></Field>}
          <div className="grid gap-3 sm:grid-cols-2"><Field label="只读账号" required><input autoComplete="username" className="control" onChange={(e)=>change("username",e.target.value)} required value={form.username}/></Field><Field label="密码" required><input autoComplete="new-password" className="control" onChange={(e)=>change("password",e.target.value)} required type="password" value={form.password}/></Field></div>
          {connector.ssl_tls_capability==="supported" ? <Field label="SSL/TLS"><select className="control" onChange={(e)=>change("ssl_mode",e.target.value)} value={form.ssl_mode}><option value="prefer">优先 TLS</option><option value="require">要求 TLS</option><option value="verify-full">校验证书与主机</option><option value="disable">禁用 TLS（仅限隔离测试环境）</option></select></Field> : null}
          {connector.engine_type==="sqlserver" ? <Field label="ODBC Driver"><input className="control" onChange={(e)=>change("odbc_driver",e.target.value)} value={form.odbc_driver}/></Field> : null}
        </>}
        <p className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs leading-5 text-amber-900"><LockKeyhole className="mr-1 inline" size={14}/>密码仅在本次请求中传输并由后端加密保存；连接参数 JSON 禁止包含明文凭据。平台只执行非写入连接检查。</p>
        {diagnostic?.status==="failed" ? <Diagnostic result={diagnostic}/> : null}
        <div className="flex justify-between gap-2"><button className="button-secondary" onClick={()=>setStep(0)} type="button"><ChevronLeft size={16}/>返回</button><button className="button-primary" disabled={testing} type="submit"><RefreshCw size={16}/>{testing?"检查中…":"测试并发现 Schema"}</button></div>
      </form> : null}
      {step===2 && diagnostic ? <section className="space-y-4"><Diagnostic result={diagnostic}/><div><h3 className="text-sm font-semibold text-ink">选择纳管范围</h3><p className="mt-1 text-xs text-slate-500">未选择任何项时不会自动扩大范围；后续可在数据源配置中调整。</p><div className="mt-2 max-h-44 space-y-1 overflow-y-auto rounded-xl border border-line p-2">{diagnostic.schemas.map((schema)=><label className="flex items-center gap-2 rounded-lg px-2 py-2 text-sm hover:bg-slate-50" key={schema}><input checked={selectedSchemas.includes(schema)} onChange={(e)=>{setSelectedSchemas((current)=>e.target.checked?[...current,schema]:current.filter((item)=>item!==schema));onDirtyChange(true);}} type="checkbox"/>{schema}</label>)}</div></div><div className="flex justify-between"><button className="button-secondary" onClick={()=>setStep(1)} type="button"><ChevronLeft size={16}/>修改连接</button><button className="button-primary" disabled={!selectedSchemas.length} onClick={()=>setStep(3)} type="button">确认范围<ChevronRight size={16}/></button></div></section> : null}
      {step===3 && connector && diagnostic ? <section className="space-y-4"><div className="rounded-xl border border-line bg-slate-50 p-4 text-sm"><p className="font-semibold text-ink">{form.display_name||form.name}</p><dl className="mt-3 grid gap-2 text-xs sm:grid-cols-2"><Summary label="Connector" value={`${connector.label} · ${diagnostic.driver||"Driver 未知"}`}/><Summary label="数据库版本" value={diagnostic.database_version||"未返回"}/><Summary label="连接目标" value={connector.engine_type==="sqlite"?form.database_name:`${form.host}:${form.port}/${form.service_name||form.database_name}`}/><Summary label="纳管范围" value={selectedSchemas.join("、")}/><Summary label="只读校验" value={readonlyLabel(diagnostic.readonly_validation)}/><Summary label="首次同步" value="保存后立即发起 Full Metadata Sync"/></dl></div><div className="flex justify-between"><button className="button-secondary" disabled={saving} onClick={()=>setStep(2)} type="button"><ChevronLeft size={16}/>返回</button><button className="button-primary" disabled={saving} onClick={()=>void createAndSync()} type="button"><Check size={16}/>{saving?"保存并提交同步中…":"保存并首次同步"}</button></div></section> : null}
    </ModalDialog>
  );
}

function Field({label,required,children}:{label:string;required?:boolean;children:React.ReactNode}) { return <label className="block text-sm font-medium text-ink">{label}{required?<span className="ml-1 text-coral-600">*</span>:null}<span className="mt-1.5 block">{children}</span></label>; }
function Summary({label,value}:{label:string;value:string}) { return <div><dt className="text-slate-400">{label}</dt><dd className="mt-0.5 break-all text-slate-700">{value}</dd></div>; }
function Diagnostic({result}:{result:DataSourceConnectionDiagnostic}) { return <div className={`rounded-xl border p-3 ${result.status==="success"?"border-pine-200 bg-pine-50":"border-coral-200 bg-coral-50"}`}><p className="text-sm font-semibold text-ink">{result.message}</p><div className="mt-2 grid gap-1 sm:grid-cols-2">{result.steps.map((item,index)=><p className="flex items-center gap-1.5 text-xs text-slate-600" key={`${item.code}-${index}`}><span className={`h-1.5 w-1.5 rounded-full ${item.status==="success"?"bg-pine-500":"bg-coral-500"}`}/>{item.message}</p>)}</div>{result.error_code?<p className="mt-2 text-xs font-medium text-coral-700">错误分类：{result.error_code}</p>:null}</div>; }
function connectorStatus(item:DataSourceConnector) { return item.status==="available"?"可创建 · 元数据发现与安全查询已启用":item.status==="driver_missing"?"服务端缺少 Driver":item.status==="disabled"?"部署配置未启用":"具体产品未确认，仅保留扩展位"; }
function readonlyLabel(value?:string|null) { return value==="database_verified"?"数据库只读信号已验证 + 安全守卫":value==="safe_query_guard"?"只读策略 + SQL 安全守卫":"平台安全守卫已启用；账号 GRANT 待管理员复核"; }
function buildPayload(connector:DataSourceConnector, form:ConnectionForm, schemas:string[]) {
  const params:Record<string,unknown>={schema_whitelist:schemas};
  if (connector.ssl_tls_capability==="supported") params.ssl_mode=form.ssl_mode;
  if (connector.engine_type==="oracle") params.oracle_identifier_type=form.oracle_identifier_type;
  if (connector.engine_type==="sqlserver") params.odbc_driver=form.odbc_driver;
  return {name:form.name,display_name:form.display_name||null,description:form.description||null,db_type:connector.engine_type,host:form.host||null,port:form.port?Number(form.port):null,database_name:form.database_name||null,service_name:form.service_name||null,schema_name:form.schema_name||null,username:form.username||null,password:form.password||null,connection_params_json:params,readonly_flag:true,enabled:true};
}

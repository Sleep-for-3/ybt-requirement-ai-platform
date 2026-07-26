import { AlertTriangle, CheckCircle2, CircleDashed, Clock3, XCircle } from "lucide-react";

export const UAT_STATUS_LABELS: Record<string,string> = {draft:"草稿",queued:"排队中",running:"执行中",passed:"通过",failed:"失败",blocked:"阻断",pending:"待确认",cancelled:"已取消",resolved:"已解决",verified:"已验证",open:"待处理",assigned:"已分派",approved:"已批准",rejected:"已驳回"};

export function UatStatus({value}:{value:string}) { const Icon=value==="passed"||value==="verified"||value==="approved"?CheckCircle2:value==="failed"||value==="rejected"?XCircle:value==="blocked"||value==="open"?AlertTriangle:value==="pending"||value==="queued"||value==="running"?Clock3:CircleDashed; const tone=value==="passed"||value==="verified"||value==="approved"?"bg-emerald-50 text-emerald-700":value==="failed"||value==="rejected"?"bg-red-50 text-red-700":value==="blocked"||value==="open"?"bg-amber-50 text-amber-700":"bg-slate-100 text-slate-600"; return <span className={`inline-flex items-center gap-1 rounded px-2 py-1 text-xs font-medium ${tone}`}><Icon size={14}/>{UAT_STATUS_LABELS[value]||value}</span>; }

export function UatMetric({label,value}:{label:string;value:React.ReactNode}) { return <div className="panel p-4"><div className="text-xs text-slate-500">{label}</div><div className="mt-1 text-2xl font-semibold">{value}</div></div>; }

export function StructuredDetails({value,empty="暂无记录"}:{value:Record<string,unknown>;empty?:string}) { const entries=Object.entries(value||{}); if(!entries.length)return <p className="text-sm text-slate-400">{empty}</p>; return <dl className="grid gap-2 text-sm sm:grid-cols-2">{entries.map(([key,item])=><div className="rounded bg-slate-50 p-2" key={key}><dt className="text-xs text-slate-500">{key}</dt><dd className="mt-1 break-words">{formatValue(item)}</dd></div>)}</dl>; }

function formatValue(value:unknown):string { if(value===null||value===undefined||value==="")return "-"; if(Array.isArray(value))return value.map(formatValue).join("、"); if(typeof value==="object")return Object.entries(value as Record<string,unknown>).map(([key,item])=>`${key}: ${formatValue(item)}`).join("；"); return String(value); }

export function readError(error:unknown) { if(!(error instanceof Error))return "操作失败"; try { const parsed=JSON.parse(error.message) as {detail?:string}; return parsed.detail||error.message; } catch { return error.message; } }

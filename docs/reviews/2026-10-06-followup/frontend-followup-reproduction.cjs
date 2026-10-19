/* Read-only review harness. Current product source, actual HTTP/draft/polling helpers; all boundaries in memory. */
const fs=require('fs');const path=require('path');const vm=require('vm');const{pathToFileURL}=require('url');
const repo=path.resolve(__dirname,'../../..');const front=path.join(repo,'frontend');const ts=require(path.join(front,'node_modules/typescript'));
const tick=()=>new Promise(r=>setImmediate(r));const response=(status,body)=>({status,ok:status>=200&&status<300,json:async()=>body,text:async()=>JSON.stringify(body),headers:{get:()=>null}});
async function apiHarness(fetchImpl){
 const http=await import(pathToFileURL(path.join(front,'lib/http-response.mjs')).href);
 const mem=new Map();const storage={getItem:k=>mem.get(k)||null,setItem:(k,v)=>mem.set(k,String(v)),removeItem:k=>mem.delete(k)};const redirects=[];
 const js=ts.transpileModule(fs.readFileSync(path.join(front,'lib/api.ts'),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;
 const ctx={exports:{},require:p=>p==='./http-response.mjs'?http:p==='./query-client'?{clearQueryCache:()=>{}}:p==='./request-timeout.mjs'?{DEFAULT_REQUEST_TIMEOUT_MS:10000,requestTimeoutMs:()=>10000}:{},process:{env:{NODE_ENV:'test',NEXT_PUBLIC_API_BASE_URL:'http://mock/api'}},sessionStorage:storage,window:{sessionStorage:storage,location:{replace:p=>redirects.push(p)}},AbortController,setTimeout,clearTimeout,fetch:fetchImpl};
 vm.runInNewContext(js,ctx);return{api:ctx.exports,storage,redirects};
}
async function c01(){
 const calls=[];let h;
 h=await apiHarness(async(url,init)=>{calls.push({url,authorization:init.headers?.Authorization,body:init.body});if(url.endsWith('/auth/refresh'))return response(200,{access_token:'A-new',refresh_token:'A-new-refresh'});return h.storage.getItem('ybt:access-token')==='A-new'?response(200,{ok:true}):response(401,{detail:'expired'});});
 h.api.saveSession('A-old','A-refresh');const normal=await h.api.apiGet('/guarded').then(v=>({resolved:v}),e=>({rejected_status:e.status,message:e.message}));
 const normalResult={expected:'one refresh then protected request succeeds',actual:normal,protected_calls:calls.filter(c=>c.url.endsWith('/guarded')).length,refresh_calls:calls.filter(c=>c.url.endsWith('/auth/refresh')).length,token:h.storage.getItem('ybt:access-token'),regression:normal.rejected_status===401};
 let release;const oldCalls=[];let b;
 b=await apiHarness(async(url,init)=>{oldCalls.push({url,authorization:init.headers?.Authorization,body:init.body});if(url.endsWith('/auth/refresh'))return new Promise(r=>{release=r;});return response(401,{detail:'expired'});});
 b.api.saveSession('A-old','A-refresh');const oldPending=b.api.apiGet('/old').catch(e=>({status:e.status}));await tick();b.api.clearSession();b.api.saveSession('B-access','B-refresh');release(response(200,{access_token:'A-new',refresh_token:'A-new-refresh'}));await oldPending;
 const oldRefresh={expected:'B token unchanged, no protected replay',token:b.storage.getItem('ybt:access-token'),protected_calls:oldCalls.filter(c=>c.url.endsWith('/old')).length,closed:b.storage.getItem('ybt:access-token')==='B-access'&&oldCalls.filter(c=>c.url.endsWith('/old')).length===1};
 let release401;const lateCalls=[];let late;
 late=await apiHarness(async(url,init)=>{lateCalls.push({url,authorization:init.headers?.Authorization,body:init.body});if(url.endsWith('/auth/refresh'))return response(200,{access_token:'B-new',refresh_token:'B-new-refresh'});return new Promise(r=>{release401=r;});});
 late.api.saveSession('A-old','A-refresh');const latePending=late.api.apiGet('/old-delayed').catch(e=>({status:e.status}));await tick();late.api.clearSession();late.api.saveSession('B-access','B-refresh');release401(response(401,{detail:'A expired'}));await latePending;
 const late401={expected:'old A request must not initiate B refresh',actual_refresh_bodies:lateCalls.filter(c=>c.url.endsWith('/auth/refresh')).map(c=>JSON.parse(c.body)),protected_calls:lateCalls.filter(c=>c.url.endsWith('/old-delayed')).length,token:late.storage.getItem('ybt:access-token'),remaining:lateCalls.some(c=>c.url.endsWith('/auth/refresh'))};
 const logoutCalls=[];const out=await apiHarness(async(url,init)=>{logoutCalls.push({url,body:init.body});return response(200,{status:'logged_out'});});out.api.saveSession('A-access','A-refresh');await out.api.logoutSession();
 return{normal_refresh:normalResult,old_refresh_after_login_b:oldRefresh,late_a_401_after_login_b:late401,logout:{calls:logoutCalls,local_cleared:!out.api.hasSession()}};
}
async function c02(){
 const helpers=await import(pathToFileURL(path.join(front,'lib/unsaved-changes.mjs')).href);const page=fs.readFileSync(path.join(front,'app/ai-control/skills/page.tsx'),'utf8');const start=page.indexOf('  const actorId =');const end=page.indexOf('  useEffect',start);const expression=page.slice(start,end);
 const key=actor=>{const c={capabilities:{actor_id:actor},scope:{scope_type:'project',project_id:11},skill:{skill_key:'requirement_candidate_generation'}};vm.runInNewContext(expression+';this.result={actorId,skillDraftKey};',c);return c.result;};
 const a=key(17),b=key(18),none=key(null);const mem=new Map();const storage={setItem:(k,v)=>mem.set(k,v),getItem:k=>mem.get(k)||null,removeItem:k=>mem.delete(k)};helpers.saveDraft(storage,a.skillDraftKey,{content:{prompt:'private A'}},a.actorId);
 const own=helpers.readDraft(storage,a.skillDraftKey,a.actorId);const other=helpers.readDraft(storage,b.skillDraftKey,b.actorId);const unknown=helpers.readDraft(storage,a.skillDraftKey,null);
 mem.set(helpers.draftKey(b.skillDraftKey,b.actorId),JSON.stringify({owner:'17',payload:{content:{prompt:'forged owner'}}}));const wrongOwner=helpers.readDraft(storage,b.skillDraftKey,b.actorId);
 return{actor_a_key:a.skillDraftKey,actor_b_key:b.skillDraftKey,unknown_key:none.skillDraftKey,a_reads_own:own.payload.content.prompt,b_reads_a:other,unknown_reads:unknown,wrong_owner_reads:wrongOwner,closed:own.payload.content.prompt==='private A'&&other===null&&unknown===null&&wrongOwner===null,identity_source:'frontend /ai-skills/capabilities -> backend RealPrincipal.user_id (source checked)'};
}
async function c11(){
 const actual=await import(pathToFileURL(path.join(front,'lib/job-polling.mjs')).href);let fail=true,visibility,calls=0;const queue=[];const seen=[];
 const registry=actual.createJobPollingRegistry({fetchJob:async()=>{calls++;if(fail)throw Error('offline');return{id:31,status:'running'};},setTimer:cb=>{queue.push(cb);return cb;},clearTimer:()=>{},isHidden:()=>false,subscribeVisibility:cb=>{visibility=cb;return()=>{};},subscribeOnline:()=>()=>{}});
 registry.subscribe(31,j=>seen.push(j.status));await tick();while(queue.length){queue.shift()();await tick();}fail=false;visibility();await tick();
 const visible={expected:'visibility recovery resumes continued polling for running job',calls,seen,stalled_after_success:registry.isStalled(31),scheduled_timers:queue.length,remaining:registry.isStalled(31)&&queue.length===0};
 let hookFail=true,online;const hookTimers=[];const hookJobs=[];const fakeReact={useState:v=>[typeof v==='function'?v():v,n=>hookJobs.push(n)],useRef:v=>({current:v}),useEffect:cb=>cb(),useCallback:fn=>fn};let hookCalls=0;
 const jsx=ts.transpileModule(fs.readFileSync(path.join(front,'hooks/useJobPolling.ts'),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;
 const ctx={exports:{},require:p=>p==='react'?fakeReact:p==='@/lib/api'?{apiGet:async()=>{hookCalls++;if(hookFail)throw Error('offline');return{id:41,status:'completed'};}}:p==='@/lib/job-polling.mjs'?{createJobPollingRegistry:opts=>actual.createJobPollingRegistry({...opts,setTimer:cb=>{hookTimers.push(cb);return cb;},clearTimer:()=>{},isHidden:()=>false,subscribeVisibility:()=>()=>{},subscribeOnline:cb=>{online=cb;return()=>{};}})}:{},setInterval:()=>1,clearInterval:()=>{}};
 vm.runInNewContext(jsx,ctx);ctx.exports.useJobPolling(41);await tick();while(hookTimers.length){hookTimers.shift()();await tick();}const before=ctx.exports.jobPollingUnavailable();hookFail=false;online();await tick();const after=ctx.exports.jobPollingUnavailable();const unrelated=ctx.exports.useJobPollingStatus(99).unavailable;
 return{visibility_recovery:visible,online_hook_recovery:{calls:hookCalls,delivered_statuses:hookJobs.filter(j=>j&&j.status).map(j=>j.status),unavailable_before:before,unavailable_after_completed:after,unrelated_job_99_unavailable:unrelated,online_fetch_closed:hookJobs.some(j=>j&&j.status==='completed'),sticky_global_remaining:after!==null&&unrelated!==null}};
}
(async()=>{const result={head:'3db4db6516a2c2cd495fe4109701a5a6451cb393',boundary:'Current source; real HTTP response/draft/polling helpers. All network, storage, timers and React boundary mocked. No service/database access.',c01:await c01(),c02:await c02(),c11:await c11()};fs.writeFileSync(path.join(__dirname,'frontend-followup-reproduction.json'),JSON.stringify(result,null,2)+'\n');console.log(JSON.stringify(result,null,2));})().catch(e=>{console.error(e);process.exitCode=1;});

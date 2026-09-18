import assert from "node:assert/strict";
import { spawn, spawnSync } from "node:child_process";
import { mkdir, writeFile } from "node:fs/promises";
import net from "node:net";
import { fileURLToPath } from "node:url";
import { createSemanticCatalogBrowser } from "./semantic-catalog-browser-harness.mjs";

const root=new URL("../../",import.meta.url);
const out=new URL("docs/ux/acceptance/",root);
await mkdir(out,{recursive:true});
const socket=net.createServer();
await new Promise(resolve=>socket.listen(0,"127.0.0.1",resolve));
const port=socket.address().port;
await new Promise(resolve=>socket.close(resolve));
const server=spawn(fileURLToPath(new URL("backend/.venv/Scripts/python.exe",root)),["tests/requirement_acceptance_server.py",String(port)],{
  cwd:fileURLToPath(new URL("backend/",root)),stdio:["ignore","pipe","pipe"],windowsHide:true});
let log="";
server.stdout.on("data",chunk=>log+=chunk);
server.stderr.on("data",chunk=>log+=chunk);
let browser;
let closing=false;
const failures=[];
async function api(path,options={}){
  const response=await fetch(`http://127.0.0.1:${port}/api${path}`,options);
  assert.ok(response.ok,`${path}: ${response.status} ${await response.clone().text()}`);
  return response;
}
try{
  let ready=false;
  for(let i=0;i<120;i++){
    if(server.exitCode!==null)throw new Error(log);
    try{ready=(await fetch(`http://127.0.0.1:${port}/api/projects`)).ok;}catch{}
    if(ready)break;
    await new Promise(resolve=>setTimeout(resolve,250));
  }
  assert.ok(ready,log);
  browser=await createSemanticCatalogBrowser({timeoutMs:45000});
  browser.handlePausedRequest=async params=>{
    try{
      const url=new URL(params.request.url);
      let status=204,body=Buffer.alloc(0),headers=[];
      if(params.request.method!=="OPTIONS"){
        const response=await fetch(`http://127.0.0.1:${port}${url.pathname}${url.search}`,{
          method:params.request.method,headers:{"Content-Type":"application/json"},body:params.request.postData||undefined});
        status=response.status;body=Buffer.from(await response.arrayBuffer());
        if(status>=400)failures.push({method:params.request.method,path:url.pathname,status,body:body.toString("utf8")});
        headers=[{name:"Content-Type",value:response.headers.get("Content-Type")||"application/json"}];
      }
      headers.push({name:"Access-Control-Allow-Origin",value:"*"},{name:"Access-Control-Allow-Methods",value:"GET, POST, PUT, OPTIONS"},{name:"Access-Control-Allow-Headers",value:"Content-Type, Authorization"});
      await browser.cdp.send("Fetch.fulfillRequest",{requestId:params.requestId,responseCode:status,responseHeaders:headers,body:body.toString("base64")},browser.sessionId);
    }catch(error){if(!closing&&!String(error).includes("Invalid InterceptionId"))throw error;}
  };
  const route="/workspace?projectId=1&requirementId=1&tableId=1&scenarioId=1&fieldId=1";
  await fetch(`http://127.0.0.1:${browser.server.port}${route}`);
  await browser.navigate(route);
  await browser.waitForText("建立独立内容");
  await browser.waitFor(()=>browser.evaluate(`Array.from(document.querySelectorAll('button')).some(e=>e.textContent==='建立独立内容'&&!e.disabled)`));
  await browser.clickText("建立独立内容");
  await browser.waitForText("需求专属口径 · 内容 v1");
  await browser.waitFor(()=>browser.evaluate(`Array.from(document.querySelectorAll('button')).some(e=>e.textContent==='生成候选'&&!e.disabled)`));
  await browser.clickText("生成候选");
  await browser.waitForText("总数 16");
  await browser.waitForText("待处理 16");
  assert.equal((await (await api("/projects/1/requirements/1/generation-runs")).json())[0].counts.completed,16);
  await browser.evaluate(`Array.from(document.querySelectorAll('button')).find(e=>e.textContent?.includes('客户统一标识 · 业务'))?.click()`);
  await browser.waitForText("候选差异");
  await browser.waitForText("合成验收候选定义");
  assert.equal(await browser.evaluate(`document.body.innerText.includes('Fake Provider')`),false);
  const modalShot=await browser.cdp.send("Page.captureScreenshot",{format:"png"},browser.sessionId);
  await writeFile(new URL("requirement-generation-diff.png",out),Buffer.from(modalShot.data,"base64"));
  await browser.clickText("加入采用清单");
  await browser.waitForText("应用采用清单（1）");
  await browser.evaluate(`Array.from(document.querySelectorAll('button')).find(e=>e.textContent?.includes('客户统一标识 · 技术'))?.click()`);
  await browser.waitForText("合成验收候选规则");
  await browser.clickText("加入采用清单");
  await browser.waitForText("应用采用清单（2）");
  await browser.clickText("应用采用清单（2）");
  await browser.waitForText("需求专属口径 · 内容 v2");
  const document=await (await api("/projects/1/requirements/1/document")).json();
  assert.equal(document.revision.content_version,2);
  assert.equal(document.candidate_adoptions.length,2);
  assert.ok(document.fields[0].business.final_content.includes("合成验收候选"));
  assert.ok(document.fields[0].lineage.processing_logic.includes("合成验收候选"));
  const history=await (await api("/projects/1/requirements/1/revisions/1")).json();
  assert.ok(!history.fields[0].business?.final_content?.includes("合成验收候选"));
  const other=await (await api("/projects/1/requirements/2/document")).json();
  assert.ok(!other.fields[0].business?.final_content?.includes("合成验收候选"));
  const pageShot=await browser.cdp.send("Page.captureScreenshot",{format:"png"},browser.sessionId);
  await writeFile(new URL("requirement-generation-adopted.png",out),Buffer.from(pageShot.data,"base64"));
  await writeFile(new URL("requirement-generation-live.json",out),JSON.stringify({
    backend:"full mounted FastAPI app; isolated named in-memory SQLite; real HTTP responses",
    provider:"built-in deterministic mock; protocol and recovery evidence only",
    fields:8,sections:2,totalItems:16,completedItems:16,reviewedCandidates:2,
    adoptedInSingleRevision:true,historyUnchanged:true,otherRequirementUnchanged:true,
    limitations:["No real-model quality conclusion.","Not PostgreSQL concurrency evidence.","Formal review and delivery are not covered."],
  },null,2));
  console.log("Live scoped generation and batch adoption acceptance passed");
}catch(error){
  console.error(error);console.error(JSON.stringify(failures));console.error(log.slice(-7000));
  if(browser)console.error(await browser.evaluate("document.body.innerText").catch(()=>"No page"));
  throw error;
}finally{
  closing=true;
  if(browser)await browser.close();
  if(server.exitCode===null){
    const exited=new Promise(resolve=>server.once("exit",resolve));
    if(process.platform==="win32")spawnSync("taskkill",["/PID",String(server.pid),"/T","/F"],{windowsHide:true,stdio:"ignore"});
    else server.kill();
    await exited;
  }
}

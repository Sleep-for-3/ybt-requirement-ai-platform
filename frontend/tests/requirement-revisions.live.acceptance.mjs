import assert from "node:assert/strict";
import { spawn, spawnSync } from "node:child_process";
import { mkdir,writeFile } from "node:fs/promises";
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
let log="";server.stdout.on("data",chunk=>log+=chunk);server.stderr.on("data",chunk=>log+=chunk);
let browser;
let closing=false;
const failedRequests=[];
async function api(path,options={}){const response=await fetch(`http://127.0.0.1:${port}/api${path}`,options);assert.ok(response.ok,`${path}: ${response.status} ${await response.clone().text()}`);return response;}
try{
  let ready=false;
  for(let i=0;i<120;i++){if(server.exitCode!==null)throw new Error(log);try{ready=(await fetch(`http://127.0.0.1:${port}/api/projects`)).ok;}catch{}if(ready)break;await new Promise(resolve=>setTimeout(resolve,250));}
  assert.ok(ready,log);
  browser=await createSemanticCatalogBrowser({timeoutMs:30000});
  // Transport bridge only: every response comes from the real mounted FastAPI app.
  browser.handlePausedRequest=async params=>{
    try{
      const url=new URL(params.request.url);
      let status=204,body=Buffer.alloc(0),headers=[];
      if(params.request.method!=="OPTIONS"){
        const response=await fetch(`http://127.0.0.1:${port}${url.pathname}${url.search}`,{method:params.request.method,
          headers:{"Content-Type":"application/json"},body:params.request.postData||undefined});
        status=response.status;body=Buffer.from(await response.arrayBuffer());
        if(status>=400)failedRequests.push({path:url.pathname,status,body:body.toString('utf8')});
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
  await browser.waitForSelector('[aria-label="需求业务定义"]');
  await browser.waitFor(()=>browser.evaluate(`document.querySelector('[aria-label="需求业务定义"]')?.disabled===false`));
  await browser.evaluate(`(()=>{const e=document.querySelector('[aria-label="需求业务定义"]');Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value').set.call(e,'仅属于需求A的人工定义');e.dispatchEvent(new Event('input',{bubbles:true}));})()`);
  await browser.clickText("保存本需求口径");
  await browser.waitForText("需求专属口径 · 内容 v2");
  const current=await (await api("/projects/1/requirements/1/document")).json();
  assert.equal(current.fields[0].business.business_definition,"仅属于需求A的人工定义");
  const old=await (await api("/projects/1/requirements/1/revisions/1")).json();
  assert.notEqual(old.fields[0].business?.business_definition,"仅属于需求A的人工定义");
  const other=await (await api("/projects/1/requirements/2/document")).json();
  assert.notEqual(other.fields[0].business?.business_definition,"仅属于需求A的人工定义");
  await browser.select('[aria-label="内容历史版本"]',"1");
  await browser.waitForText("历史内容只读");
  await browser.waitForSelector('[aria-label="需求业务定义"]');
  assert.equal(await browser.evaluate(`document.querySelector('[aria-label="需求业务定义"]').disabled`),true);
  await browser.select('[aria-label="内容历史版本"]',"0");
  await browser.evaluate(`Array.from(document.querySelectorAll('button[role="tab"]')).find(e=>e.textContent==='血缘').click()`);
  await browser.waitForSelector(".react-flow__edge-path");
  const graph=await (await api("/projects/1/requirements/1/revisions/2/lineage")).json();
  assert.ok(graph.graph.tables.length>=3);
  await writeFile(new URL("requirement-revision-export.xlsx",out),Buffer.from(await (await api("/projects/1/requirements/1/export")).arrayBuffer()));
  await browser.evaluate(`document.querySelector('.react-flow').scrollIntoView({block:'center'})`);
  const screenshot=await browser.cdp.send("Page.captureScreenshot",{format:"png"},browser.sessionId);
  await writeFile(new URL("requirement-revision-live.png",out),Buffer.from(screenshot.data,"base64"));
  await writeFile(new URL("requirement-revision-live.json",out),JSON.stringify({backend:"full FastAPI app with isolated in-memory database and test principal; no startup hooks",fields:8,independentEdits:true,historyReadOnly:true,realExport:true,lineageSnapshot:true,limitations:["Not a generation, formal review, PostgreSQL or real-model acceptance test."]},null,2));
  console.log("Live requirement revision acceptance passed");
}catch(error){
  console.error(error);
  console.error(JSON.stringify(failedRequests));
  console.error(log.slice(-6000));
  if(browser){console.error(await browser.evaluate("document.body.innerText").catch(()=>"No page"));}
  throw error;
}finally{
  closing=true;
  if(browser)await browser.close();
  if(server.exitCode===null){
    const exited=new Promise(resolve=>server.once("exit",resolve));
    if(process.platform==='win32')spawnSync('taskkill',['/PID',String(server.pid),'/T','/F'],{windowsHide:true,stdio:'ignore'});
    else server.kill();
    await exited;
  }
}

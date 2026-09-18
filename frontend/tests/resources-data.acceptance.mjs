import assert from "node:assert/strict";
import { mkdir, writeFile } from "node:fs/promises";
import { createSemanticCatalogBrowser } from "./semantic-catalog-browser-harness.mjs";

// Only loopback synthetic full-app server; never forward to the developer's API.
const backend="http://127.0.0.1:18765";
const output=new URL("../../docs/ux/acceptance/resources-data/",import.meta.url);
await mkdir(output,{recursive:true});
process.env.NEXT_DIST_DIR=".next-resources-browser-acceptance";
const browser=await createSemanticCatalogBrowser({timeoutMs:60000,serverTimeoutMs:120000});
await browser.cdp.send("Page.addScriptToEvaluateOnNewDocument",{source:`
  window.__resourceBlobAudit={created:[],revoked:[]};
  const create=URL.createObjectURL.bind(URL), revoke=URL.revokeObjectURL.bind(URL);
  URL.createObjectURL=blob=>{const url=create(blob);window.__resourceBlobAudit.created.push(url);return url;};
  URL.revokeObjectURL=url=>{window.__resourceBlobAudit.revoked.push(url);revoke(url);};
`},browser.sessionId);
const requests=[];const result={environment:"Synthetic in-memory full backend, fake extractive model, real Next and installed Chromium",checks:[]};
browser.handlePausedRequest=async params=>{
  const url=new URL(params.request.url);
  if(params.request.method==="OPTIONS"){
    await browser.cdp.send("Fetch.fulfillRequest",{requestId:params.requestId,responseCode:204,responseHeaders:[
      {name:"Access-Control-Allow-Origin",value:"*"},{name:"Access-Control-Allow-Headers",value:"Content-Type, Authorization"},
      {name:"Access-Control-Allow-Methods",value:"GET, POST, OPTIONS"}]},browser.sessionId).catch(()=>{});
    return;
  }
  const request={path:url.pathname,method:params.request.method};requests.push(request);
  try {
    const response=await fetch(`${backend}${url.pathname}${url.search}`,{method:params.request.method,
      headers:{"Content-Type":"application/json"},body:["GET","HEAD"].includes(params.request.method)?undefined:params.request.postData});
    request.status=response.status;
    const bytes=Buffer.from(await response.arrayBuffer());
    await browser.cdp.send("Fetch.fulfillRequest",{requestId:params.requestId,responseCode:response.status,
      responseHeaders:[{name:"Content-Type",value:response.headers.get("content-type")||"application/octet-stream"},
        {name:"Access-Control-Allow-Origin",value:"*"},{name:"Access-Control-Allow-Headers",value:"Content-Type, Authorization"},
        {name:"Cache-Control",value:"no-store"}],body:bytes.toString("base64")},browser.sessionId);
  }catch{
    await browser.cdp.send("Fetch.fulfillRequest",{requestId:params.requestId,responseCode:503,responseHeaders:[{name:"Access-Control-Allow-Origin",value:"*"}],body:Buffer.from('{"detail":"Synthetic server unavailable"}').toString("base64")},browser.sessionId).catch(()=>{});
  }
};
async function shot(name){await browser.evaluate("new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))");const image=await browser.cdp.send("Page.captureScreenshot",{format:"png"},browser.sessionId);await writeFile(new URL(name,output),Buffer.from(image.data,"base64"));}
async function navigate(path){await fetch(`http://127.0.0.1:${browser.server.port}${path}`);await browser.navigate(path);}
async function type(selector,text){
  await browser.waitFor(()=>browser.evaluate("Array.from(document.querySelectorAll('select')).some(e=>!e.closest('main')&&e.value==='1')"));
  await browser.evaluate(`(()=>{const e=document.querySelector(${JSON.stringify(selector)});e.focus();e.select();})()`);
  await browser.cdp.send("Input.insertText",{text},browser.sessionId);
  await browser.waitFor(()=>browser.evaluate(`document.querySelector(${JSON.stringify(selector)}).value===${JSON.stringify(text)}`));
}
async function submit(){await browser.waitFor(()=>browser.evaluate("Array.from(document.querySelectorAll('main button')).some(e=>e.textContent.trim()==='提交问题'&&!e.disabled)"));await browser.clickText("提交问题");}
async function escape(){await browser.cdp.send("Input.dispatchKeyEvent",{type:"keyDown",key:"Escape",code:"Escape",windowsVirtualKeyCode:27},browser.sessionId);await browser.cdp.send("Input.dispatchKeyEvent",{type:"keyUp",key:"Escape",code:"Escape",windowsVirtualKeyCode:27},browser.sessionId);}
try {
  for(const route of ["/resources","/knowledge/ask","/knowledge/documents","/knowledge/documents/1"]){await fetch(`http://127.0.0.1:${browser.server.port}${route}`);}
  await navigate("/resources?projectId=1");await browser.waitForText("进入监管知识问答");
  await browser.waitForText("隔离验收用户");await browser.waitForText("业务系统");
  await browser.waitForText("最近变更");await browser.waitForText("待处理事项");
  await browser.waitForSelector("main a[href='/business-systems']");
  assert.equal(await browser.evaluate("Array.from(document.querySelectorAll('main a')).some(a=>a.textContent.includes('返回'))"),false);
  await shot("resources-desktop.png");
  await browser.clickText("进入监管知识问答");await browser.waitForSelector("textarea");
  await type("textarea","客户证件类型报送范围");await submit();await browser.waitForText("合成验收依据");
  await browser.waitForText("可信性说明");await browser.waitForText("正式索引覆盖状态");
  await browser.clickText("查看依据");await browser.waitForSelector("dialog[open] [data-highlight='true']");
  assert.equal(await browser.evaluate("document.querySelector('dialog[open]').textContent.includes('当前项目无访问权限')"),false);
  await shot("regulatory-evidence.png");await escape();await browser.waitFor(()=>browser.evaluate("!document.querySelector('dialog[open]')"));
  result.checks.push("regulatory question / evidence / block highlight / Escape close");
  await navigate("/templates?projectId=1");await browser.waitForText("客户信息一表通模板");await browser.clickText("客户信息一表通模板");
  await browser.waitForText("内部版本 2");await browser.waitForText("2026批次");await browser.waitForText("新增字段");await browser.waitForText("修改字段");
  await browser.waitForText("待审核");await browser.waitForText("已生效");await shot("template-version-diff.png");
  await browser.clickText("人工审核通过");await browser.waitForText("版本已审核");
  await browser.waitFor(()=>browser.evaluate("Array.from(document.querySelectorAll('main button')).some(e=>e.textContent.includes('激活生效'))"));
  await browser.clickText("激活生效");await browser.waitForText("版本已激活");
  await browser.waitFor(()=>browser.evaluate("Array.from(document.querySelectorAll('main button')).some(e=>e.textContent.includes('Apply 当前版本'))"));
  await browser.clickText("Apply 当前版本");await browser.waitForText("写入审计变更集");
  result.checks.push("template row detail / two versions / diff / review / activation / apply audit");
  await navigate("/knowledge/documents/1?projectId=1");await browser.waitForText("当前生效内部版本 1");await browser.clickText("版本记录");
  await browser.waitForText("2026修订版");await browser.waitForText("待审核");await browser.clickText("审核通过");await browser.waitForText("已审核");
  await browser.waitFor(()=>browser.evaluate("Array.from(document.querySelectorAll('main button')).some(e=>e.textContent.includes('激活生效'))"));
  await browser.clickText("激活生效");await browser.waitForText("当前生效内部版本 2");await browser.waitForText("已替代");await shot("knowledge-version-activation.png");
  await navigate("/knowledge/ask?mode=regulatory&projectId=1");await browser.waitForSelector("textarea");await type("textarea","客户证件类型报送范围");await submit();
  await browser.waitForText("2026修订版");await browser.waitForText("内部版本：R2");await browser.waitForText("合成制度新口径");await shot("regulatory-new-version.png");
  result.checks.push("knowledge candidate remains inactive / review / atomic activation / current R2 citation");
  await navigate("/knowledge/ask?mode=regulatory&projectId=1");await browser.waitForSelector("textarea");await type("textarea","客户证件类型报送范围");
  await browser.clickText("数据字段与血缘问答");await browser.waitForText("目标字段（可选）");
  assert.equal(await browser.evaluate("document.querySelector('textarea').value"),"客户证件类型报送范围");
  await type("textarea","CERT_TYPE 来源和加工规则");
  await browser.waitFor(()=>browser.evaluate("Array.from(document.querySelectorAll('main select option')).some(o=>o.textContent.includes('CERT_TYPE'))"));
  await browser.select("main select",1);await submit();await browser.waitForText("客户信息系统");
  for(const text of ["CUSTOMER_DB","ECIF","CUSTOMER","CERT_TYPE","Join/关联条件"])await browser.waitForText(text);
  await browser.evaluate("Array.from(document.querySelectorAll('h3')).find(e=>e.textContent==='来源路径').scrollIntoView({block:'start'})");
  await shot("data-field-paths.png");
  await browser.clickText("CUSTOMER.CERT_TYPE");await browser.waitForSelector("dialog[open]");await browser.waitForText("实体证据详情");await escape();
  result.checks.push("data field catalog/source/mapping/lineage sections / entity detail");
  await browser.select("main select","");await type("textarea","ZXQ_999_NO_EVIDENCE");await submit();await browser.waitForText("暂无来源证据");
  result.checks.push("unknown field has gaps and no invented source");
  for(const [id,name] of [[1,"regulatory-2026-revision.xlsx"],[2,"policy.docx"],[3,"policy.pdf"]]){
    const listQuery=name.split(".")[0];
    await navigate(`/knowledge/documents?projectId=1&q=${encodeURIComponent(listQuery)}`);await browser.waitForText(name);await browser.clickText(name);
    await browser.waitForText("下载原文");await browser.waitForSelector("main [role='tab'][aria-selected='true']");
    if(id===1)await browser.waitForSelector("main table");
    if(id===3){await browser.waitForSelector("main iframe");assert.ok((await browser.attribute("main iframe","src")).startsWith("blob:"));await browser.waitForText("打开 PDF 原文");}
    await shot(`document-${id}.png`);
    await browser.evaluate("document.querySelector('main [role=tab][aria-selected=true]').focus()");
    await browser.cdp.send("Input.dispatchKeyEvent",{type:"keyDown",key:"ArrowRight",code:"ArrowRight",windowsVirtualKeyCode:39},browser.sessionId);
    await browser.waitFor(()=>browser.evaluate("document.activeElement.textContent==='解析内容'&&document.activeElement.getAttribute('aria-selected')==='true'"));
    await browser.clickText("版本记录");await browser.waitForText("阅读此版本");
    if(id===3)await browser.waitForText("存在解析失败的新版本");
    await browser.waitFor(()=>browser.evaluate("window.__resourceBlobAudit.created.length>0&&window.__resourceBlobAudit.created.every(url=>window.__resourceBlobAudit.revoked.includes(url))"));
    await browser.clickText("阅读此版本");await browser.waitForText("下载原文");
    await browser.clickText("返回知识文档");await browser.waitFor(()=>browser.evaluate(`location.pathname==='/knowledge/documents'&&new URLSearchParams(location.search).get('q')===${JSON.stringify(listQuery)}`));
    assert.equal(await browser.evaluate("new URLSearchParams(location.search).get('q')"),listQuery);
    await browser.clickText("返回资料与数据");await browser.waitFor(()=>browser.evaluate("location.pathname==='/resources'"));
  }
  result.checks.push("XLSX grid / DOCX blocks / PDF Blob and original link / keyboard tabs / version reading / Blob cleanup / list query restoration / resources parent");
  result.pdfLimitation="Native PDF pixels are not verified by headless Chromium; Blob URL, original link and parsed evidence are verified.";
  await navigate("/knowledge/documents/7?projectId=1");await browser.waitForText("当前文件需要 OCR");
  const denied=await fetch(`${backend}/api/knowledge/documents/1/content?project_id=2`);
  assert.equal(denied.status,404);assert.equal((await denied.json()).detail,"Resource not found");
  for(const path of ["knowledge/documents/1/preview?project_id=2","knowledge/documents/1/content?project_id=2","projects/2/knowledge/evidence/catalog_column/1"]){
    const response=await browser.evaluate(`fetch(${JSON.stringify(`http://localhost:8000/api/${path}`)}).then(async r=>({status:r.status,body:await r.text()}))`);
    assert.equal(response.status,404);assert.ok(!response.body.includes("CERT_TYPE"));assert.ok(!response.body.includes("storage_path"));
  }
  result.checks.push("scan OCR warning / forbidden project original returns generic 404");
  await browser.cdp.send("Emulation.setDeviceMetricsOverride",{width:390,height:844,deviceScaleFactor:1,mobile:true},browser.sessionId);
  await navigate("/knowledge/ask?mode=regulatory&projectId=1");await browser.waitForSelector("textarea");await type("textarea","客户证件类型");await submit();await browser.waitForText("合成验收依据");await browser.clickText("查看依据");await browser.waitForSelector("dialog[open] [data-highlight='true']");
  assert.equal(await browser.evaluate("document.querySelector('dialog[open]').getBoundingClientRect().width<=window.innerWidth"),true);
  await shot("evidence-narrow.png");await escape();
  result.checks.push("390px drawer bounds / keyboard close");
  result.requestCount=requests.length;result.unexpectedErrors=requests.filter(r=>r.status>=500);
  assert.deepEqual(result.unexpectedErrors,[]);
  await writeFile(new URL("results.json",output),JSON.stringify(result,null,2));
  console.log(JSON.stringify(result,null,2));
}catch(error){await shot("failure.png").catch(()=>{});console.error(JSON.stringify({checks:result.checks,failedRequests:requests.filter(r=>r.status>=400),lastRequests:requests.slice(-8)},null,2));throw error;}finally{await browser.close();}

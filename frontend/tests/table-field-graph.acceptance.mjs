import assert from "node:assert/strict";
import { mkdir, writeFile } from "node:fs/promises";
import { createSemanticCatalogBrowser } from "./semantic-catalog-browser-harness.mjs";

// Isolated browser fixtures: no API request is allowed to reach a real backend.
function sample(count = 4, fieldsPerTable = 8) {
  const tables = [], nodes = [], edges = [];
  for (let t = 0; t < count; t++) {
    const id = `table:${t}`;
    const fields = Array.from({length:fieldsPerTable}, (_, f) => `field:${t}:${f}`);
    tables.push({id, name:`合成验收表${t}`, technical_name:`SYNTH_${t}`, layer:t < 2 ? "source" : t === 2 ? "mart" : "target", fields});
    fields.forEach((field, f) => nodes.push({id:field, table_key:id, entity_type:t === count-1 ? "target_field" : "source_field", canonical_entity_id:t*fieldsPerTable+f+1, data_type:"VARCHAR", unresolved_flag:false, display:{business_name:`合成字段${t}_${f}`, technical_name:`COL_${f}`}}));
  }
  const edge = (a,b,dependency=false) => edges.push({id:`edge:${edges.length}`,source_node_id:a,target_node_id:b,edge_type:dependency?"join":"value",relation_source:"business_mapping",transformation_expression:"COALESCE(s.balance, 0)",join_condition:"c.customer_id = a.customer_id",filter_condition:"c.status = 'ACTIVE'",code_mapping_rule:"P → 个人；C → 企业",rules:{},evidence_refs:[{source_name:"隔离合成验收字典",location_text:"客户定义第2行",quoted_content:"合成测试依据，不用于生产报送"}]});
  for (let t=2;t<count;t++) for(let f=0;f<fieldsPerTable;f++) edge(`field:${t-1}:${f}`,`field:${t}:${f}`);
  edge("field:0:0","field:2:0"); edge("field:0:0","field:2:1",true);
  return {project_id:1,tables,nodes,edges,root_ids:tables.at(-1).fields,revision_id:null,truncated:false,omitted_frontier_count:0,facts_mode:"synthetic_acceptance",limits:{depth:10,max_nodes:500},warnings:[]};
}
const out = new URL("../../docs/ux/acceptance/",import.meta.url);
await mkdir(out,{recursive:true});
const browser = await createSemanticCatalogBrowser({timeoutMs:30000});
let graph=sample();
const metrics={environment:"Windows, headless Chromium, Next development build, isolated intercepted synthetic API",small:{},large:{}};
browser.handlePausedRequest=async params=>{
  const path=new URL(params.request.url).pathname;
  let body=[];
  if(path.endsWith("/auth/me"))body={username:"synthetic-reviewer",effective_project_permissions:{"1":["lineage.view"]},capabilities:{}};
  else if(path==="/api/projects")body=[{id:1,name:"隔离合成验收项目"}];
  else if(path.endsWith("/lineage/assets"))body={items:[{kind:"target",id:1,name:"合成监管客户表",technical_name:"SYNTH_CUSTOMER"}],truncated:false};
  else if(path.endsWith("/lineage/table-graph"))body=graph;
  else if(path.endsWith("/jobs/summary"))body={queued_count:0,running_count:0,active_count:0};
  await browser.respond({requestId:params.requestId,settled:false},{body,status:200});
};
async function screenshot(name){const shot=await browser.cdp.send("Page.captureScreenshot",{format:"png"},browser.sessionId);await writeFile(new URL(name,out),Buffer.from(shot.data,"base64"));}
async function paths(){return browser.evaluate(`Array.from(document.querySelectorAll('.react-flow__edge-path')).map(e=>e.getAttribute('d'))`);}
try {
  await fetch(`http://127.0.0.1:${browser.server.port}/lineage/nebula?projectId=1`);
  await browser.navigate("/lineage/nebula?projectId=1");
  await browser.waitForText("合成监管客户表");
  const started=Date.now();
  await browser.clickText("合成监管客户表");
  await browser.waitForSelector(".react-flow__edge-path");
  metrics.small.loadMs=Date.now()-started;
  assert.equal(await browser.evaluate("document.querySelectorAll('.react-flow__node').length"),4);
  assert.equal(await browser.evaluate("document.querySelectorAll('button[aria-label^=\"聚焦字段\"]').length"),32);
  await browser.click('button[aria-label="聚焦字段 合成字段0_0 COL_0"]');
  await browser.waitFor(()=>browser.evaluate("Array.from(document.querySelectorAll('.react-flow__edge-path')).some(e=>getComputedStyle(e).opacity === '0.12')"));
  await browser.evaluate("document.querySelector('.react-flow__edge-interaction').dispatchEvent(new MouseEvent('click',{bubbles:true}))");
  await browser.waitForText("c.customer_id = a.customer_id");
  await browser.waitForText("隔离合成验收字典");
  await screenshot("table-field-rules.png");
  await browser.click('[aria-label="关闭关系详情"]');
  const expanded=await paths();
  await browser.click('[aria-label="收起合成验收表2"]');
  await browser.waitFor(async()=>JSON.stringify(await paths())!==JSON.stringify(expanded));
  assert.ok((await paths()).every(d=>d&&!d.includes("NaN")));
  await browser.click('[aria-label="展开合成验收表2"]');
  await browser.clickText("适配画布");
  await screenshot("table-field-overview.png");
  metrics.small={...metrics.small,tables:4,fields:32,edges:graph.edges.length,focus:true,edgeDetails:true,collapseReanchors:true};
  graph=sample(20,10);
  const largeStart=Date.now();
  await browser.select('[aria-label="探索方向"]',"upstream");
  await browser.waitFor(()=>browser.evaluate("document.querySelectorAll('.react-flow__node').length === 20"));
  await browser.waitFor(()=>browser.evaluate(`document.querySelectorAll('.react-flow__edge-path').length === ${graph.edges.length}`));
  metrics.large.loadMs=Date.now()-largeStart;
  const interactionStart=Date.now();
  await browser.click('button[aria-label="聚焦字段 合成字段0_0 COL_0"]');
  await browser.waitFor(()=>browser.evaluate("Array.from(document.querySelectorAll('.react-flow__edge-path')).some(e=>getComputedStyle(e).opacity === '0.12')"));
  metrics.large.focusMs=Date.now()-interactionStart;
  assert.equal(await browser.evaluate("document.querySelectorAll('button[aria-label^=\"聚焦字段\"]').length"),200);
  await screenshot("table-field-large.png");
  metrics.large={...metrics.large,tables:20,fields:200,edges:graph.edges.length};
  await browser.navigate("/lineage/nebula?projectId=1&requirementId=7&tableId=3&scenarioId=9&fieldId=25");
  await browser.waitFor(async()=>{
    const href=await browser.attribute('a[href^="/workspace?"]',"href");
    return href && new URL(href,"http://local.test").searchParams.get("requirementId")==="7";
  });
  const back=new URL(await browser.attribute('a[href^="/workspace?"]',"href"),"http://local.test");
  for(const [key,value] of Object.entries({projectId:"1",requirementId:"7",tableId:"3",scenarioId:"9",fieldId:"25"}))assert.equal(back.searchParams.get(key),value);
  metrics.returnLinkContext=true;
  metrics.limitations=["Synthetic API validates rendering and interactions, not backend lineage semantics or real generation quality.","Timing includes automation polling; not a repeatable performance benchmark.","No manual visual sign-off yet; screenshots require review."];
  await writeFile(new URL("table-field-metrics.json",out),JSON.stringify(metrics,null,2));
  console.log(JSON.stringify(metrics,null,2));
} catch(error) { await screenshot("table-field-failure.png").catch(()=>{}); console.error(error); throw error; } finally {await browser.close();}

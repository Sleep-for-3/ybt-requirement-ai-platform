import assert from "node:assert/strict";
import { mkdir, writeFile } from "node:fs/promises";
import { createSemanticCatalogBrowser } from "./semantic-catalog-browser-harness.mjs";

// UI contract sample only. Backend HTTP tests separately inspect real Excel bytes.
const out = new URL("../../docs/ux/acceptance/", import.meta.url);
await mkdir(out, { recursive: true });
const browser = await createSemanticCatalogBrowser({ timeoutMs: 30000 });
const table = {id:3,project_id:1,table_code:"SYNTH_CUSTOMER",table_name:"隔离合成客户报送表"};
const scenario = {id:9,project_id:1,scenario_name:"合成活跃客户",scenario_code:"SYNTH"};
const records = Array.from({length:8}, (_, i) => ({
  field:{id:25+i,project_id:1,target_table_id:3,field_code:`CUSTOMER_${i}`,field_name:`合成客户字段${i}`},
  business:null,lineage:null,mart_mappings:[],source_mappings:{},evidence_count:0,question_count:0,readiness_status:"incomplete"
}));
const requirement = {id:7,project_id:1,version:1,name:"隔离合成需求",target_table_id:3,scenario_id:9,
  field_ids:records.map(r=>r.field.id),background:"仅用于隔离浏览器验收",objective:"核验草稿快照",inclusion:"活跃客户",exclusion:"注销客户",
  effective_date:null,document_ids:[],source_table_ids:[],mart_table_ids:[]};
const projection = {project_id:1,selected_target_table_id:3,selected_scenario_id:9,tables:[table],scenarios:[scenario],
  records,asset_summary:{business_system_count:0,datasource_count:0,healthy_datasource_count:0,mart_table_count:0},
  mart_tables:[],mart_fields:[],question_summaries:[],recent_jobs:[],readiness_summary:{field_count:8,complete_field_count:0,open_question_count:0,evidence_count:0}};
let permissions=["project.view","deliverable.view","deliverable.manage","deliverable.export"];
let saves=0, exports=0, stale=false;
let resourceSave=null;
let pendingGeneration=null, businessWrites=0, followupWrites=0;
const snapshots=[];
browser.handlePausedRequest=async params=>{
  const path=new URL(params.request.url).pathname;
  let body=[], status=200;
  if(params.request.method === "OPTIONS") {
    await browser.cdp.send("Fetch.fulfillRequest",{requestId:params.requestId,responseCode:204,responseHeaders:[
      {name:"Access-Control-Allow-Origin",value:"*"},
      {name:"Access-Control-Allow-Methods",value:"GET, POST, PUT, OPTIONS"},
      {name:"Access-Control-Allow-Headers",value:"Content-Type, Authorization"}
    ]},browser.sessionId);
    return;
  }
  else if(path.endsWith("/business-mapping")){
    businessWrites++;
    pendingGeneration={requestId:params.requestId,settled:false};
    return;
  }
  else if(path.endsWith("/technical-lineage") || path.includes("/batch/")){followupWrites++;body={id:100};}
  else if(path.endsWith("/auth/me"))body={effective_project_permissions:{"1":permissions},capabilities:{}};
  else if(path === "/api/projects")body=[{id:1,name:"隔离合成验收项目"}];
  else if(path.endsWith("/requirement-workspace"))body=projection;
  else if(path.includes("/requirement-workspace/fields/"))body=records.find(r=>path.endsWith(`/${r.field.id}`))||[];
  else if(path.endsWith("/requirements"))body=[requirement];
  else if(path.endsWith("/requirements/7") && params.request.method === "PUT"){
    resourceSave=JSON.parse(params.request.postData);
    body={...requirement,...resourceSave,version:2};
  }
  else if(path.endsWith("/requirement-resources"))body={
    document_ids:{items:[{id:41,name:"合成码值字典",code:"合成码值字典"}],truncated:false},
    source_table_ids:{items:[{id:51,name:"合成客户来源",code:"SYNTH_CUSTOMER"}],truncated:false},
    mart_table_ids:{items:[{id:61,name:"合成客户集市",code:"SYNTH_MART"}],truncated:false}
  };
  else if(path.endsWith("/document"))body={requirement,fields:records,content_hash:"a".repeat(64),assessment:"gaps",gaps:[{id:"25:source",field_id:25,origin:"analysis",status:"open",message:"合成来源缺口待确认"}]};
  else if(path.endsWith("/snapshots") && params.request.method === "POST"){
    saves++;
    assert.deepEqual(JSON.parse(params.request.postData),{expected_version:1,expected_hash:"a".repeat(64)});
    if(stale){status=409;body={detail:"字段口径已变化"};}
    else{if(!snapshots.length)snapshots.push({id:1,requirement_version:1,created_at:"2026-09-13T00:00:00Z",status:"frozen_draft"});body=snapshots[0];status=201;}
  }
  else if(path.endsWith("/snapshots"))body=snapshots;
  else if(path.endsWith("/snapshots/1/export")){exports++;body="isolated-download-contract";}
  else if(path.endsWith("/jobs/summary"))body={queued_count:0,running_count:0,active_count:0};
  try {
    await browser.respond({requestId:params.requestId,settled:false},{body,status});
  } catch(error) {
    // React Query aborts obsolete context requests during the initial restore.
    if(!String(error).includes("Invalid InterceptionId"))throw error;
  }
};
const route="/workspace?projectId=1&requirementId=7&tableId=3&scenarioId=9&fieldId=27";
const panel='[aria-label="需求草稿快照"]';
async function shot(name){const image=await browser.cdp.send("Page.captureScreenshot",{format:"png"},browser.sessionId);await writeFile(new URL(name,out),Buffer.from(image.data,"base64"));}
try{
  await fetch(`http://127.0.0.1:${browser.server.port}${route}`);
  await browser.navigate(route);
  await browser.waitForText("保存当前草稿快照");
  await browser.waitForText("发现 1 项待确认");
  assert.equal(await browser.evaluate('document.querySelector("[aria-label=选择需求]").value'),"7");
  assert.equal(await browser.evaluate('document.querySelector("[aria-label=业务背景]").value'),requirement.background);
  await browser.clickText("待确认");
  await browser.waitForSelector('[aria-label="当前需求全部缺口"]');
  assert.equal(await browser.evaluate(`document.querySelector('[aria-label="当前需求全部缺口"]').textContent.includes('合成来源缺口待确认')`),true);
  await browser.clickText("文档预览");
  await browser.waitForText("业务背景");
  assert.equal(await browser.evaluate(`document.querySelector('article').textContent.includes(${JSON.stringify(requirement.background)})`),true);
  assert.equal(await browser.evaluate(`document.querySelector('article').textContent.includes('合成来源缺口待确认')`),true);
  assert.equal(await browser.evaluate(`document.querySelector('article').textContent.includes('草稿（待审核交付）')`),true);
  await browser.clickText("保存当前草稿快照");
  await browser.waitForText("草稿快照已固定");
  assert.equal(saves,1);
  await browser.clickText("导出固定草稿");
  await browser.waitFor(()=>exports===1);
  stale=true;
  await browser.waitFor(()=>browser.evaluate(`!document.querySelector('${panel} button').disabled`));
  await browser.clickText("保存当前草稿快照");
  await browser.waitForText("未能保存快照");
  assert.equal(saves,2);
  await browser.evaluate(`document.querySelector('${panel}').scrollIntoView({block:'center'})`);
  await shot("requirement-snapshot-stale.png");
  permissions=["project.view","deliverable.view"];
  await browser.navigate(route);
  await browser.waitForText("当前角色仅可查看记录");
  assert.equal(await browser.evaluate(`document.querySelector('${panel}').textContent.includes('保存当前草稿快照')`),false);
  assert.equal(await browser.evaluate(`document.querySelector('${panel}').textContent.includes('导出固定草稿')`),false);
  await browser.evaluate(`document.querySelector('${panel}').scrollIntoView({block:'center'})`);
  await shot("requirement-snapshot-viewer.png");
  permissions=["project.view","business.edit","deliverable.view","deliverable.manage","deliverable.export"];
  await browser.navigate(route);
  await browser.waitForText("保存当前草稿快照");
  await browser.click('[aria-label="关联知识资料 合成码值字典"]');
  await browser.click('[aria-label="允许使用的来源表 合成客户来源"]');
  await browser.click('[aria-label="允许使用的集市表 合成客户集市"]');
  await browser.clickText("保存修订版本");
  await browser.waitForText("已保存需求版本 v2");
  assert.deepEqual(resourceSave.document_ids,[41]);
  assert.deepEqual(resourceSave.source_table_ids,[51]);
  assert.deepEqual(resourceSave.mart_table_ids,[61]);
  assert.equal(resourceSave.background,requirement.background);
  assert.equal(await browser.evaluate(`document.querySelector('[aria-label="关联知识资料 合成码值字典"]').checked`),true);
  await browser.evaluate(`document.querySelector('[aria-label="资料与数据范围"]').scrollIntoView({block:'center'})`);
  await shot("requirement-resources-selected.png");
  // Hold the first legacy generation request, then switch the selected field.
  // Its late response must not initialize/queue follow-up work in the new view.
  await browser.select('[aria-label="选择需求"]',"");
  await browser.clickText("生成业务口径与技术溯源草稿");
  await browser.waitFor(()=>pendingGeneration!==null);
  await browser.clickText("合成客户字段1");
  await browser.waitForText("生成业务口径与技术溯源草稿");
  await browser.clickText("合成客户字段2");
  await browser.respond(pendingGeneration,{status:200,body:{id:100,project_id:1,target_field_id:27,scenario_id:9}});
  await new Promise(resolve=>setTimeout(resolve,500));
  assert.equal(businessWrites,1);
  assert.equal(followupWrites,0);
  assert.equal(await browser.evaluate("document.body.textContent.includes('当前字段的草稿任务已提交')"),false);
  await writeFile(new URL("requirement-snapshot-browser.json",out),JSON.stringify({scopeRestored:true,backgroundRestored:true,gapVisible:true,documentAndQuestionsUseScopeGaps:true,resourceSelectionSaved:true,saveContext:true,staleRejected:true,downloadRequested:true,viewerActionsHidden:true,lateGenerationResponseDiscarded:true,limitations:["Intercepted synthetic API; not real generation or rendered Excel acceptance."]},null,2));
  console.log("Requirement snapshot browser contract passed");
}catch(error){await shot("requirement-snapshot-failure.png").catch(()=>{});throw error;}
finally{await browser.close();}

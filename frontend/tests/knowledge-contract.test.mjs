import assert from "node:assert/strict";
import test from "node:test";
import { MODES, answerMode, askPayload, pinNotice, citationLocator, locateBlock, viewerFormat, ownedBlobUrl, evidenceTarget, askErrorMessage } from "../lib/knowledge-contract.mjs";

test("explicit modes send only compatible filters",()=>{
  assert.equal(answerMode(null),"regulatory");
  assert.equal(answerMode("unknown"),"regulatory");
  assert.deepEqual(askPayload("regulatory"," q ",12,3),{query:"q",answer_mode:"regulatory",top_k:8});
  assert.equal(askPayload("data_field","q",12,3).target_field_id,12);
  assert.equal(askPayload("data_field","q").scenario_id,null);
  assert.ok(MODES.regulatory.sections.includes("适用范围"));
  assert.ok(MODES.data_field.sections.includes("来源路径"));
  assert.notEqual(MODES.regulatory.example,MODES.data_field.example);
});

test("requirement version pinning is only sent when both ids are present",()=>{
  assert.deepEqual(askPayload("regulatory","q",null,null,false,"",null),{query:"q",answer_mode:"regulatory",top_k:8});
  assert.deepEqual(askPayload("regulatory","q",null,null,false,"",{requirementId:"5",contentVersion:"9"}),
    {query:"q",answer_mode:"regulatory",top_k:8,requirement_id:5,requirement_content_version:9});
  // 只给其中一个不得猜测版本：缺 contentVersion 时不发送钉扎字段。
  assert.equal(askPayload("regulatory","q",null,null,false,"",{requirementId:5}).requirement_id,undefined);
  assert.equal(askPayload("regulatory","q",null,null,false,"",{contentVersion:9}).requirement_content_version,undefined);
  // 展示口径必须区分“已固定”与“请求了但未回显”。
  assert.deepEqual(pinNotice(null,{pinned_versions:{}}),{tone:"none",text:""});
  assert.match(pinNotice({requirementId:5,contentVersion:9},null).text,/未回显固定版本/);
  const pinned=pinNotice({requirementId:5,contentVersion:9},{pinned_versions:{"客户风险分类管理办法":"2026-v1"}});
  assert.equal(pinned.tone,"pinned");
  assert.match(pinned.text,/需求 v9/);
  assert.match(pinned.text,/客户风险分类管理办法=2026-v1/);
  assert.match(pinNotice({requirementId:5,contentVersion:9},{pinned_versions:{}}).text,/未记录具体制度版本/);
});
test("question failures distinguish permissions, network and invalid input without raw diagnostics",()=>{
  assert.match(askErrorMessage({status:403}),/无权/);
  assert.match(askErrorMessage({status:0}),/网络/);
  assert.match(askErrorMessage({status:422}),/无效/);
  // 业务规则拒绝必须把服务端中文原因交给用户；结构校验（detail 为数组）仍走通用文案。
  assert.equal(askErrorMessage({status:422,detail:"该需求版本未固定任何制度版本，无法按冻结版本判定，请先确认监管版本。"}),
    "该需求版本未固定任何制度版本，无法按冻结版本判定，请先确认监管版本。");
  assert.match(askErrorMessage({status:422,detail:[{loc:["body","query"],msg:"field required"}]}),/无效/);
  assert.match(askErrorMessage({status:400,detail:"requirement_id 与 requirement_content_version 必须同时给出"}),/同时给出/);
  assert.match(askErrorMessage({status:500,message:"private diagnostic"}),/服务暂不可用/);
  assert.equal(askErrorMessage(null),askErrorMessage({status:500}));
});
test("locator priority is block, format position, then quote",()=>{
  const blocks=[{block_id:"a",text:"first",locator:{page_no:1}},{block_id:"b",text:"second",locator:{page_no:2}}];
  assert.equal(locateBlock(blocks,{block_id:"a",page_no:2,text_quote:"second"}),"a");
  assert.equal(locateBlock(blocks,{page_no:2,text_quote:"first"}),"b");
  assert.equal(locateBlock(blocks,{text_quote:"second"}),"b");
  assert.equal(locateBlock(blocks,{block_id:"missing"}),null);
  assert.equal(citationLocator({knowledge_unit_id:7,source_page_no:2}).block_id,"knowledge-unit-7");
});
test("all formats select safe viewer and blob disposal is idempotent",()=>{
  assert.deepEqual(["pdf","xlsx","docx","txt","md","sql"].map(viewerFormat),["pdf","grid","blocks","text","text","text"]);
  const released=[];const owned=ownedBlobUrl({}, {createObjectURL:()=>"blob:fixture",revokeObjectURL:url=>released.push(url)});
  owned.dispose();owned.dispose();assert.deepEqual(released,["blob:fixture"]);
});
test("four citation kinds resolve by trusted IDs, never uploaded URLs or foreign projects",()=>{
  assert.equal(evidenceTarget({citation_type:"knowledge_document",document_id:2,document_version_id:3},1).versionId,3);
  for(const [kind,key,source] of [["catalog_column","catalog_column_id","catalog_column"],["lineage_edge","lineage_edge_id","lineage_edge"],["mapping","mapping_id","scenario_technical"],["mapping","source_field_id","source_field"]]){
    const c={project_id:1,citation_type:kind,source_type:source,[key]:7,href:"https://untrusted.invalid"};
    assert.equal(evidenceTarget(c,1).path,`/projects/1/knowledge/evidence/${source}/7`);
    assert.equal(evidenceTarget(c,2),null);
    assert.equal(evidenceTarget({...c,[key]:null},1),null);
  }
});

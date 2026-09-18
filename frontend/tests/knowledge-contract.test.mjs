import assert from "node:assert/strict";
import test from "node:test";
import { MODES, answerMode, askPayload, citationLocator, locateBlock, viewerFormat, ownedBlobUrl, evidenceTarget, askErrorMessage } from "../lib/knowledge-contract.mjs";

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

test("question failures distinguish permissions, network and invalid input without raw diagnostics",()=>{
  assert.match(askErrorMessage({status:403}),/无权/);
  assert.match(askErrorMessage({status:0}),/网络/);
  assert.match(askErrorMessage({status:422}),/无效/);
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

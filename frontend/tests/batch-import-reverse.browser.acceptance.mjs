import {chromium} from "playwright";
import {mkdir,writeFile} from "node:fs/promises";
import path from "node:path";
import assert from "node:assert/strict";

// Use reverse_requirements_acceptance_server.py with a disposable sample directory.
const origin="http://127.0.0.1:18742",samples=path.resolve(process.argv[2]),output=path.resolve(process.argv[3]);
const projectId=Number(process.argv[4]||1),multilayer=projectId===2;
await mkdir(output,{recursive:true});
const browser=await chromium.launch({headless:true,channel:"msedge"});
const context=await browser.newContext({viewport:{width:1440,height:1050}});
const page=await context.newPage(),errors=[];
page.on("pageerror",e=>errors.push(e.message));
async function postClick(suffix,locator){
  const [response]=await Promise.all([page.waitForResponse(r=>r.url().endsWith(suffix)&&r.request().method()==="POST"),locator.click()]);
  const body=await response.json();assert.ok(response.ok(),JSON.stringify(body));return body;
}
try{
  await page.goto(`${origin}/resources/architecture?projectId=${projectId}`);
  await page.getByRole("button",{name:multilayer?"使用多层数仓示例":"使用贴源报送示例"}).click();
  const saved=page.waitForResponse(r=>r.url().endsWith(`/projects/${projectId}/data-architecture`)&&r.request().method()==="PUT");
  await page.getByRole("button",{name:"保存项目架构"}).click();assert.equal((await saved).status(),200);
  await page.goto(`${origin}/resources/import?projectId=${projectId}`);
  await page.getByLabel("默认层级",{exact:true}).selectOption(multilayer?"layer_5":"layer_2");
  const files=["structures.ddl","conflict.ddl","dictionary.xlsx","scripts.zip",...(multilayer?["import-source.sql","import-mid.sql"]:[]),"import-direct.sql","import-extra.sql","invalid.ddl"];
  await page.getByLabel("导入文件").setInputFiles(files.map(name=>path.join(samples,name)));
  const preview=await postClick(`/projects/${projectId}/resource-imports`,page.getByRole("button",{name:"解析预览",exact:true}));
  const conflict=page.locator("article").filter({has:page.getByRole("heading",{name:/conflict.ddl/})});
  await conflict.getByText(/冲突：bank.ods.accounts/).waitFor();
  assert.equal(preview.preview.items.filter(i=>i.kind==="sql").length,multilayer?5:3);
  const source=preview.preview.items.find(i=>i.path==="import-direct.sql").references.find(r=>r.role==="read");
  assert.ok(!source.proposed_layer_key,"Default target layer must not classify upstream sources");
  await conflict.getByRole("combobox",{name:"冲突处理"}).first().selectOption("merge");
  const zip=page.locator("article").filter({has:page.getByRole("heading",{name:/scripts.zip\/nested\/check.sql/})});
  await zip.getByRole("checkbox",{name:"明确保留上述解析缺口后导入"}).check();
  if(multilayer){
    for(const [schema,layer] of [["dwd","layer_2"],["dws","layer_3"]]){
      const table=page.getByText(new RegExp(`新增：bank.${schema}.accounts`)).locator("..");
      await table.getByRole("combobox",{name:"accounts 层级"}).selectOption(layer);
    }
  }
  const updated=page.waitForResponse(r=>r.url().endsWith(`/resource-imports/${preview.id}/preview`)&&r.request().method()==="PUT");
  await page.getByRole("button",{name:"保存调整并更新预览"}).click();assert.equal((await updated).status(),200);
  await page.screenshot({path:path.join(output,"mixed-preview.png"),fullPage:true});
  const applied=await postClick(`/resource-imports/${preview.id}/apply`,page.getByRole("button",{name:"确认应用当前预览"}));
  assert.equal(applied.status,"partial");
  assert.equal(applied.items.filter(i=>i.status==="failed").length,1);
  const successful=applied.items.filter(i=>i.status==="completed").map(i=>({id:i.id,result:i.result}));
  const retried=await postClick(`/resource-imports/${preview.id}/retry`,page.getByRole("button",{name:"重试失败项"}));
  assert.equal(retried.status,"partial");
  assert.deepEqual(retried.items.filter(i=>i.status==="completed").map(i=>({id:i.id,result:i.result})),successful);
  await postClick(`/resource-imports/${preview.id}/reopen`,page.getByRole("button",{name:"调整失败项预览"}));
  const invalid=page.locator("article").filter({has:page.getByRole("heading",{name:/invalid.ddl/})});
  await invalid.getByRole("combobox",{name:"冲突处理"}).selectOption("skip");
  const revised=page.waitForResponse(r=>r.url().endsWith(`/resource-imports/${preview.id}/preview`)&&r.request().method()==="PUT");
  await page.getByRole("button",{name:"保存调整并更新预览"}).click();assert.equal((await revised).status(),200);
  const completed=await postClick(`/resource-imports/${preview.id}/apply`,page.getByRole("button",{name:"确认应用当前预览"}));
  assert.equal(completed.status,"completed");
  assert.equal(completed.items.find(i=>i.path==="invalid.ddl").status,"skipped");
  assert.deepEqual(completed.items.filter(i=>i.status==="completed").map(i=>({id:i.id,result:i.result})),successful);
  await page.screenshot({path:path.join(output,"partial-retry-result.png"),fullPage:true});
  await page.getByRole("link",{name:"从本批次脚本生成需求"}).click();
  await page.getByRole("checkbox",{name:/import-direct.sql/}).waitFor();
  assert.equal(await page.getByRole("checkbox",{name:/batch.sql/}).count(),0);
  await page.getByRole("checkbox",{name:/scripts.zip/}).uncheck();
  await page.getByRole("button",{name:"预览写入目标"}).click();
  await page.getByLabel("业务场景").selectOption({index:1});
  await page.getByRole("combobox",{name:"report监管表与模板版本",exact:true}).selectOption({index:1});
  const extra=page.getByRole("combobox",{name:"report_extra监管表与模板版本",exact:true});
  const value=await extra.getByRole("option",{name:/REPORT_EXTRA/}).getAttribute("value");
  await extra.selectOption(value);
  await page.getByRole("checkbox",{name:/确认以上版本、监管目标/}).check();
  const created=await postClick("/requirements/from-scripts",page.getByRole("button",{name:"分别建立需求草稿"}));
  assert.equal(created.requirements.length,2);
  await page.getByRole("region",{name:"建需批次结果"}).waitFor();
  await page.screenshot({path:path.join(output,"two-target-requirements.png"),fullPage:true});
  await page.getByRole("region",{name:"建需批次结果"}).getByRole("link").first().click();
  await page.getByRole("region",{name:"核验实际加工路径"}).waitFor();
  await page.getByRole("region",{name:"从已有跑批生成需求",exact:true}).getByText(/已固定的脚本事实/).click();
  await page.screenshot({path:path.join(output,"imported-requirement.png"),fullPage:true});
  const requirement=created.requirements[0],base=`/requirements/${requirement.requirement_id}`;
  await page.getByLabel("业务背景",{exact:true}).fill("隔离银行跑批逆向梳理，保留当前期末取数事实。");
  await page.getByLabel("业务目标",{exact:true}).fill("明确余额口径、制度依据和验收规则。");
  await page.getByRole("checkbox",{name:/路径核验隔离制度/}).check();
  const scope=page.waitForResponse(r=>r.url().endsWith(base)&&r.request().method()==="PUT");
  await page.getByRole("button",{name:"保存修订版本"}).click();assert.equal((await scope).status(),200);
  await page.getByText("需求专属口径 · 内容 v3",{exact:true}).waitFor();
  const scripts=page.getByRole("region",{name:"从已有跑批生成需求",exact:true});
  await scripts.getByRole("button",{name:"选择脚本版本",exact:true}).click();
  await scripts.getByRole("checkbox",{name:/import-direct.sql/}).check();
  if(multilayer){
    await scripts.getByRole("checkbox",{name:/import-source.sql/}).check();
    await scripts.getByRole("checkbox",{name:/import-mid.sql/}).check();
  }
  await scripts.getByRole("button",{name:"预览所选脚本事实"}).click();
  await scripts.getByLabel("实际写入目标").selectOption({label:"bank.reg.report"});
  await scripts.getByLabel("监管模板版本").selectOption({index:1});
  await scripts.getByRole("checkbox",{name:/已核对目标、模板与字段关联/}).check();
  await scripts.getByRole("button",{name:"确认并建立新内容版本"}).click();
  await page.getByText("需求专属口径 · 内容 v4",{exact:true}).waitFor();
  const paths=page.getByRole("region",{name:"核验实际加工路径"});
  await paths.getByLabel("路径核验依据").fill(multilayer?"核对 ODS → DWD → DWS → 报送表三个脚本，字段原值逐层传递，跨脚本依赖完整。":"核对导入表结构与直接取数脚本，来源 amount 原值写入报送表，无需集市。");
  await paths.getByRole("button",{name:"确认路径并建立新修订"}).click();
  await page.getByText("需求专属口径 · 内容 v5",{exact:true}).waitFor();
  const policy=page.locator('details[aria-label="制度逐条对照"]');
  await policy.locator(":scope > summary").click();await policy.locator("ul button").first().click();
  for(const box of await policy.getByRole("checkbox").all())await box.check();
  await policy.getByLabel("人工判断").selectOption("matched");
  await policy.getByRole("textbox",{name:"核验理由",exact:true}).fill("原值取数满足固定制度期末金额要求，已人工逐项核验。");
  await policy.getByRole("button",{name:"确认本条并保存新修订"}).click();
  await page.getByText("需求专属口径 · 内容 v6",{exact:true}).waitFor();
  const editor=page.getByRole("region",{name:"需求独立内容"});
  await editor.getByRole("textbox",{name:"需求业务定义",exact:true}).fill("账户期末余额，取已核验来源系统金额。");
  await editor.getByRole("textbox",{name:"需求业务口径",exact:true}).fill("人工确认：按期末账户范围取金额原值；预期结果与来源金额一致。");
  await editor.getByRole("button",{name:"保存本需求口径"}).click();
  await page.getByText("需求专属口径 · 内容 v7",{exact:true}).waitFor();
  const delivery=page.getByRole("region",{name:"审核与正式交付"});
  const submitted=await postClick(`${base}/review-submissions`,delivery.getByRole("button",{name:"提交内容 v7 审核"}));
  for(const task of submitted.tasks){
    const role={business_review:"business_reviewer",technical_review:"technical_reviewer",final_review:"final_reviewer"}[task.step_key];
    const reviewer=await browser.newContext({extraHTTPHeaders:{"x-isolated-review-role":role}});
    try{const review=await reviewer.newPage();review.on("pageerror",e=>errors.push(e.message));
      await review.goto(`${origin}/tasks/${task.id}`);
      await review.getByRole("textbox",{name:"审核意见"}).fill("隔离验收：已核对导入依据、人工口径、路径和制度，确认本阶段审核通过。");
      const response=review.waitForResponse(r=>r.url().endsWith(`/review-tasks/${task.id}/approve`)&&r.request().method()==="POST");
      await review.getByRole("button",{name:"通过",exact:true}).click();assert.equal((await response).status(),200);
    }finally{await reviewer.close();}
  }
  await page.reload();
  const formal=await postClick(`${base}/review-submissions/${submitted.id}/finalize`,delivery.getByRole("button",{name:/固定正式交付/}));
  await page.screenshot({path:path.join(output,"formal-approved.png"),fullPage:true});
  const hashes=[];
  for(const [label,ext] of [["下载 Excel","xlsx"],["Word 正文","docx"]]){
    const download=page.waitForEvent("download");
    const response=page.waitForResponse(r=>r.url().includes("/formal-deliveries/")&&r.url().includes("/export"));
    await delivery.getByRole("button",{name:label}).click();
    await(await download).saveAs(path.join(output,`formal-v7.${ext}`));
    hashes.push((await response).headers()["x-requirement-snapshot-hash"]);
  }
  assert.ok(hashes[0]);assert.equal(hashes[0],hashes[1]);
  await page.goto(`${origin}/lineage/scripts?projectId=${projectId}`);
  await page.getByText("import-direct.sql",{exact:true}).waitFor();
  await page.locator('input[type="file"]').setInputFiles({name:"import-direct.sql",mimeType:"text/plain",
    buffer:Buffer.from(`INSERT INTO bank.reg.report (amount) SELECT amount * 2 FROM bank.${multilayer?"dws":"ods"}.accounts;`)});
  await page.getByPlaceholder("相对路径（ZIP 可留空）").fill("import-direct.sql");
  const changed=await postClick(`/projects/${projectId}/scripts/upload`,page.getByRole("button",{name:"安全摄取"}));
  assert.equal(changed.version_no,2);
  await page.goto(`${origin}/work?projectId=${projectId}`);
  const impacts=page.getByRole("region",{name:"需求依据变化影响"});
  await impacts.getByRole("link",{name:new RegExp(`${requirement.name}.*待复核`)}).waitFor();
  await page.screenshot({path:path.join(output,"after-delivery-script-change.png"),fullPage:true});
  await impacts.getByRole("link",{name:new RegExp(`${requirement.name}.*待复核`)}).click();
  await page.getByText("需求专属口径 · 内容 v7",{exact:true}).waitFor();
  const historical=page.waitForResponse(r=>r.url().includes("/formal-deliveries/")&&r.url().includes("/export"));
  const historicalDownload=page.waitForEvent("download");
  await delivery.getByRole("button",{name:"下载 Excel"}).click();
  await(await historicalDownload).saveAs(path.join(output,"formal-v7-after-script-change.xlsx"));
  assert.equal((await historical).headers()["x-requirement-snapshot-hash"],hashes[0]);
  assert.deepEqual(errors,[]);
  const result={projectId,multilayer,actualApi:true,model:"not_called",importBatch:preview.id,successfulItems:successful.length,
    partialFailure:true,retryPreservesSuccess:true,explicitSkip:true,createdRequirements:created.requirements,
    formalDelivery:formal,exportContentHash:hashes[0],reviewSteps:submitted.tasks.length,
    changedScriptTriggersRecheck:true,historicalDeliveryUnchanged:true,pageErrors:errors};
  await writeFile(path.join(output,"results.json"),JSON.stringify(result,null,2));console.log(JSON.stringify(result));
}finally{await context.close();await browser.close();}

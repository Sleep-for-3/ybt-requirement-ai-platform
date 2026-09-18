import {chromium} from "playwright";
import {mkdir,writeFile} from "node:fs/promises";
import path from "node:path";
import assert from "node:assert/strict";

// Isolated fixture: --exception-cases; never changes existing accounts or data.
const output=path.resolve(process.argv[2]),origin="http://127.0.0.1:18742";
await mkdir(output,{recursive:true});
const browser=await chromium.launch({headless:true,channel:"msedge"});
const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];
page.on("pageerror",e=>errors.push(e.message));
try{
  await page.goto(`${origin}/workspace?projectId=1&tableId=1&scenarioId=1&requirementId=1`);
  const policy=page.locator('details[aria-label="制度逐条对照"]');
  await policy.locator(":scope > summary").click();
  await policy.locator("ul button").first().click();
  await policy.getByText("期末余额必须按金额乘二报送，不能直接取原值。",{exact:true}).waitFor();
  for(const box of await policy.getByRole("checkbox").all())await box.check();
  await policy.getByLabel("人工判断").selectOption("conflict");
  await policy.getByRole("textbox",{name:"核验理由",exact:true}).fill("脚本直接取 amount，制度要求乘二，两者不一致。");
  await policy.getByRole("textbox",{name:"差异或缺失说明",exact:true}).fill("缺少金额乘二加工，必须由业务和技术确认变更，不能按已匹配处理。");
  const response=page.waitForResponse(r=>r.url().endsWith("/requirements/1/policy-comparison")&&r.request().method()==="POST");
  await policy.getByRole("button",{name:"确认本条并保存新修订"}).click();
  assert.equal((await response).status(),201);
  await page.getByText("需求专属口径 · 内容 v4",{exact:true}).waitFor();
  const delivery=page.getByRole("region",{name:"审核与正式交付"});
  await delivery.getByText("正式交付暂不可用",{exact:true}).waitFor();
  const readiness=await page.request.get("http://127.0.0.1:18741/api/projects/1/requirements/1/review-readiness?content_version=4");
  assert.equal(readiness.status(),200);
  const readinessBody=await readiness.json();
  assert.equal(readinessBody.eligible,false);
  assert.ok(readinessBody.reasons.some(reason=>/与脚本存在差异/.test(reason.message)));
  assert.equal(await delivery.getByRole("button",{name:/提交内容.*审核/}).count(),0);
  await policy.locator(":scope > summary").click();
  await policy.getByRole("button",{name:/存在冲突/}).click();
  assert.match(await policy.getByLabel("差异或缺失说明").inputValue(),/缺少金额乘二/);
  await policy.screenshot({path:path.join(output,"policy-conflict-blocks-review.png")});

  await page.goto(`${origin}/workspace?projectId=2&tableId=2&scenarioId=2&requirementId=2`);
  const paths=page.getByRole("region",{name:"核验实际加工路径"});
  await paths.locator("summary").click();
  await paths.getByText(/缺少|缺失|未解析/).first().waitFor();
  await paths.getByLabel("路径核验依据").fill("上游未登记，不能确认完整。");
  assert.equal(await paths.getByRole("button",{name:"确认路径并建立新修订"}).isDisabled(),true);
  const scripts=page.getByRole("region",{name:"从已有跑批生成需求",exact:true});
  await scripts.getByText("待复核：固定依据发生变化",{exact:true}).waitFor();
  await paths.screenshot({path:path.join(output,"missing-upstream-blocks-path.png")});
  await scripts.getByRole("button",{name:"选择脚本版本",exact:true}).click();
  for(const name of [/batch.sql/,/layer-0.sql/,/layer-1.sql/])await scripts.getByRole("checkbox",{name}).check();
  await scripts.getByRole("button",{name:"预览所选脚本事实"}).click();
  await scripts.getByLabel("实际写入目标").selectOption({label:"bank.reg.report"});
  await scripts.getByLabel("监管模板版本").selectOption({index:1});
  await scripts.getByRole("checkbox",{name:/已核对目标、模板与字段关联/}).check();
  const fixed=page.waitForResponse(r=>r.url().endsWith("/requirements/2/script-basis")&&r.request().method()==="POST");
  await scripts.getByRole("button",{name:"确认并建立新内容版本"}).click();
  assert.equal((await fixed).status(),201);
  await page.getByText("需求专属口径 · 内容 v3",{exact:true}).waitFor();
  await policy.locator(":scope > summary").click();
  await policy.getByText("缺少制度依据，请修订资料范围并重新固定依据。",{exact:true}).waitFor();
  assert.equal(await policy.locator("ul button").count(),0);
  assert.equal(await delivery.getByRole("button",{name:/提交内容.*审核/}).count(),0);
  await policy.screenshot({path:path.join(output,"expired-policy-excluded.png")});
  assert.deepEqual(errors,[]);
  const result={actualApi:true,model:"not_called",conflictPersisted:true,conflictBlocksReview:true,
    missingUpstreamBlocksConfirmation:true,expiredPolicyTriggersRecheck:true,expiredPolicyExcludedOnRefreeze:true,
    missingBasisVisible:true,pageErrors:errors};
  await writeFile(path.join(output,"results.json"),JSON.stringify(result,null,2));console.log(JSON.stringify(result));
}finally{await browser.close();}

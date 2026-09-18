import {chromium} from "playwright";
import {mkdir,writeFile} from "node:fs/promises";
import path from "node:path";
import assert from "node:assert/strict";

// Run after requirement-paths.browser.acceptance against the same isolated fixture.
const origin="http://127.0.0.1:18742";
const output=path.resolve(process.argv[2]);
await mkdir(output,{recursive:true});
const browser=await chromium.launch({headless:true,channel:"msedge"});
const context=await browser.newContext({viewport:{width:1440,height:1050}});
const page=await context.newPage();
const errors=[];
page.on("pageerror",e=>errors.push(e.message));
try{
  await page.goto(`${origin}/workspace?projectId=2&tableId=2&scenarioId=2&requirementId=2`);
  const panel=page.getByRole("region",{name:"需求规则验收"});
  await panel.waitFor({timeout:30000});
  const [created]=await Promise.all([
    page.waitForResponse(r=>r.url().endsWith("/requirements/2/uat-suites")&&r.request().method()==="POST"),
    panel.getByRole("button",{name:"从确认规则生成待审核测试项"}).click()]);
  assert.equal(created.status(),201);
  const link=await created.json();
  await panel.getByRole("link",{name:/待送审/}).click();
  await page.getByRole("region",{name:"需求规则测试项审核"}).waitFor();
  assert.equal(await page.getByRole("button",{name:"创建执行轮次"}).isDisabled(),true);
  const [submitted]=await Promise.all([
    page.waitForResponse(r=>r.url().endsWith(`/uat-suites/${link.suite_id}/requirement-review`)&&r.request().method()==="POST"),
    page.getByRole("button",{name:"提交测试项审核"}).click()]);
  assert.equal(submitted.status(),201);
  const review=await submitted.json();
  await page.screenshot({path:path.join(output,"suite-in-review.png"),fullPage:true});
  for(const task of review.tasks){
    const role=task.step_key==="technical_review"?"technical_reviewer":"final_reviewer";
    const reviewer=await browser.newContext({viewport:{width:1440,height:1000},extraHTTPHeaders:{"x-isolated-review-role":role}});
    try{
      const reviewPage=await reviewer.newPage();
      reviewPage.on("pageerror",e=>errors.push(e.message));
      await reviewPage.goto(`${origin}/tasks/${task.id}`);
      await reviewPage.getByRole("textbox",{name:"审核意见"}).fill("隔离验收：已逐项审阅固定需求规则、制度对照与人工测试预期结果。");
      const [approved]=await Promise.all([
        reviewPage.waitForResponse(r=>r.url().endsWith(`/review-tasks/${task.id}/approve`)&&r.request().method()==="POST"),
        reviewPage.getByRole("button",{name:"通过",exact:true}).click()]);
      assert.equal(approved.status(),200);
    }finally{await reviewer.close();}
  }
  await page.reload();
  const [runResponse]=await Promise.all([
    page.waitForResponse(r=>r.url().endsWith(`/uat-suites/${link.suite_id}/runs`)&&r.request().method()==="POST"),
    page.getByRole("button",{name:"创建执行轮次"}).click()]);
  assert.equal(runResponse.status(),201);
  const run=await runResponse.json();
  await page.getByRole("button",{name:"执行",exact:true}).click();
  const dialog=page.getByRole("dialog");
  const [executed]=await Promise.all([
    page.waitForResponse(r=>r.url().endsWith(`/uat-runs/${run.id}/execute`)&&r.request().method()==="POST"),
    dialog.getByRole("button",{name:"确认",exact:true}).click()]);
  assert.equal(executed.status(),200);
  const cards=page.locator("article");
  await cards.first().getByRole("textbox",{name:"样本预期值",exact:true}).waitFor({timeout:30000});
  assert.equal(await cards.count(),3);
  for(let index=0;index<3;index++){
    const card=cards.nth(index);
    await card.getByRole("textbox",{name:"样本预期值",exact:true}).fill("120.00");
    await card.getByRole("textbox",{name:"样本实际值",exact:true}).fill("120.00");
    await card.getByRole("textbox",{name:"验证证据",exact:true}).fill("脱敏样本 A；人工核对来源值与输出值一致；未连接银行数据源。");
    await card.getByPlaceholder("填写实际结果或 Finding 摘要").fill("人工核验原值规则一致");
    const [completed]=await Promise.all([
      page.waitForResponse(r=>r.url().includes("/uat-case-results/")&&r.url().endsWith("/complete-manual")&&r.request().method()==="POST"),
      card.getByRole("button",{name:"确认通过",exact:true}).click()]);
    assert.equal(completed.status(),200);
    const result=await completed.json();
    assert.equal(result.evidence_json.requirement_evidence.content_hash,link.content_hash);
    await card.getByRole("button",{name:"确认通过",exact:true}).waitFor({state:"detached"});
  }
  await page.screenshot({path:path.join(output,"manual-rule-results.png"),fullPage:true});
  assert.deepEqual(errors,[]);
  const result={actualApi:true,model:"not_called",suiteId:link.suite_id,runId:run.id,
    caseCount:3,reviewSteps:2,manualResults:true,immutableRuleEvidence:true,pageErrors:errors};
  await writeFile(path.join(output,"results.json"),JSON.stringify(result,null,2));
  console.log(JSON.stringify(result));
}finally{await context.close();await browser.close();}

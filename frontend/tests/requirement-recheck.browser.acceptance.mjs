import {chromium} from "playwright";
import {mkdir, writeFile} from "node:fs/promises";
import path from "node:path";
import assert from "node:assert/strict";

// Run after path acceptance using only the disposable loopback fixture.
const origin="http://127.0.0.1:18742";
const output=path.resolve(process.argv[2]);
await mkdir(output,{recursive:true});
const browser=await chromium.launch({headless:true,channel:"msedge"});
const context=await browser.newContext({viewport:{width:1440,height:1050}});
const page=await context.newPage();
const errors=[];
page.on("pageerror",error=>errors.push(error.message));
try {
  await page.goto(`${origin}/lineage/scripts?projectId=1`);
  await page.getByText("batch.sql",{exact:true}).waitFor();
  await page.locator('input[type="file"]').setInputFiles({name:"batch.sql",mimeType:"text/plain",
    buffer:Buffer.from("INSERT INTO bank.reg.report (amount) SELECT amount * 1 FROM bank.ods.accounts;")});
  await page.getByPlaceholder("相对路径（ZIP 可留空）").fill("batch.sql");
  const [uploaded]=await Promise.all([
    page.waitForResponse(r=>r.url().endsWith("/projects/1/scripts/upload")&&r.request().method()==="POST"),
    page.getByRole("button",{name:"安全摄取"}).click()]);
  assert.equal(uploaded.status(),200);
  const script=await uploaded.json();
  assert.equal(script.version_no,2);
  await page.goto(`${origin}/work?projectId=1`);
  const queue=page.getByRole("region",{name:"需求依据变化影响"});
  await queue.getByText(/脚本.*已变化/).first().waitFor();
  const [created]=await Promise.all([
    page.waitForResponse(r=>r.url().endsWith("/requirements/1/rechecks")&&r.request().method()==="POST"),
    queue.getByRole("button",{name:"建立复核任务"}).click()]);
  assert.equal(created.status(),201);
  const recheck=await created.json();
  await queue.getByText(/已建立复核记录/).waitFor();
  await page.screenshot({path:path.join(output,"impact-queue.png"),fullPage:true});
  await queue.getByRole("link",{name:/待复核/}).click();
  const panel=page.getByRole("region",{name:"需求变更复核"});
  await panel.getByLabel("修订或处理依据").fill("脚本金额表达式改为乘一，显式重新核验原值规则；原固定快照保留。");
  const [revised]=await Promise.all([
    page.waitForResponse(r=>r.url().endsWith(`/rechecks/${recheck.id}/revise`)&&r.request().method()==="POST"),
    panel.getByRole("button",{name:"明确建立新修订"}).click()]);
  assert.equal(revised.status(),201);
  await page.getByText("需求专属口径 · 内容 v5",{exact:true}).waitFor();
  const [unresolved]=await Promise.all([
    page.waitForResponse(r=>r.url().endsWith(`/rechecks/${recheck.id}/resolution`)&&r.request().method()==="POST"),
    panel.getByRole("button",{name:"关联已核验当前修订"}).click()]);
  assert.equal(unresolved.status(),409);
  await panel.getByRole("alert").waitFor();
  await page.screenshot({path:path.join(output,"explicit-revision.png"),fullPage:true});
  await page.setViewportSize({width:390,height:844});
  await panel.screenshot({path:path.join(output,"mobile-recheck.png")});
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth),true);
  await page.setViewportSize({width:1440,height:1050});
  const scripts=page.getByRole("region",{name:"从已有跑批生成需求",exact:true});
  await scripts.getByRole("button",{name:"选择脚本版本",exact:true}).click();
  await scripts.getByRole("checkbox",{name:/batch.sql · v2/}).check();
  await scripts.getByRole("button",{name:"预览所选脚本事实"}).click();
  await scripts.getByLabel("实际写入目标").selectOption({label:"bank.reg.report"});
  await scripts.getByLabel("监管模板版本").selectOption({index:1});
  await scripts.getByRole("checkbox",{name:/已核对目标、模板与字段关联/}).check();
  await scripts.getByRole("button",{name:"确认并建立新内容版本"}).click();
  await page.getByText("需求专属口径 · 内容 v6",{exact:true}).waitFor();
  const paths=page.getByRole("region",{name:"核验实际加工路径"});
  await paths.getByLabel("路径核验依据").fill("重新核验脚本 v2：来源与目标一致，金额乘一，路径完整。");
  await paths.getByRole("button",{name:"确认路径并建立新修订"}).click();
  await page.getByText("需求专属口径 · 内容 v7",{exact:true}).waitFor();
  const policy=page.locator('details[aria-label="制度逐条对照"]');
  await policy.locator(":scope > summary").click();
  await policy.locator("ul button").first().click();
  for(const box of await policy.getByRole("checkbox").all())await box.check();
  await policy.getByLabel("人工判断").selectOption("matched");
  await policy.getByRole("textbox",{name:"核验理由",exact:true}).fill("金额乘一仍为期末原值；已人工核对新表达式与制度要求一致。");
  await policy.getByRole("button",{name:"确认本条并保存新修订"}).click();
  await page.getByText("需求专属口径 · 内容 v8",{exact:true}).waitFor();
  await panel.getByLabel("修订或处理依据").fill("v8 已重新固定脚本 v2、确认路径与制度；保留 v4 快照。");
  const [resolved]=await Promise.all([
    page.waitForResponse(r=>r.url().endsWith(`/rechecks/${recheck.id}/resolution`)&&r.request().method()==="POST"),
    panel.getByRole("button",{name:"关联已核验当前修订"}).click()]);
  assert.equal(resolved.status(),200);
  const reviewer=await browser.newContext({extraHTTPHeaders:{"x-isolated-review-role":"technical_reviewer"}});
  try{
    const review=await reviewer.newPage();
    review.on("pageerror",error=>errors.push(error.message));
    await review.goto(`${origin}/tasks/${recheck.tasks[0].id}`);
    await review.getByRole("textbox",{name:"审核意见"}).fill("已核对 v8 与固定原版本差异，表达式乘一符合原值要求，关闭依据变更复核。");
    const [approved]=await Promise.all([
      review.waitForResponse(r=>r.url().endsWith(`/review-tasks/${recheck.tasks[0].id}/approve`)&&r.request().method()==="POST"),
      review.getByRole("button",{name:"通过",exact:true}).click()]);
    assert.equal(approved.status(),200);
  }finally{await reviewer.close();}
  await page.reload();
  await panel.getByText(/复核已关闭/).waitFor();
  await page.screenshot({path:path.join(output,"review-closed.png"),fullPage:true});
  assert.deepEqual(errors,[]);
  const result={actualApi:true,model:"not_called",uploadedVersion:script.version_no,recheckId:recheck.id,
    explicitRevision:5,resolvedVersion:8,independentReviewClosed:true,unverifiedResolutionRejected:true,
    mobileNoHorizontalOverflow:true,pageErrors:errors};
  await writeFile(path.join(output,"results.json"),JSON.stringify(result,null,2));
  console.log(JSON.stringify(result));
} finally {await context.close();await browser.close();}

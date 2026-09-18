import {chromium} from "playwright";
import {mkdir,writeFile} from "node:fs/promises";
import path from "node:path";
import assert from "node:assert/strict";

// Fixture uses the real worker and MockLLMService, with one injected provider failure.
const origin="http://127.0.0.1:18742",output=path.resolve(process.argv[2]);
await mkdir(output,{recursive:true});
const browser=await chromium.launch({headless:true,channel:"msedge"});
const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];
page.on("pageerror",e=>errors.push(e.message));
try{
  await page.goto(`${origin}/workspace?projectId=1&tableId=1&scenarioId=1&requirementId=1`);
  const editor=page.getByRole("region",{name:"需求独立内容"});
  await editor.getByRole("textbox",{name:"需求业务定义",exact:true}).fill("人工定义：仅限隔离样本的期末金额，不得被模型覆盖。");
  await editor.getByRole("button",{name:"保存本需求口径"}).click();
  await page.getByText("需求专属口径 · 内容 v3",{exact:true}).waitFor();
  const generation=page.getByRole("region",{name:"需求范围生成"});
  await generation.getByRole("checkbox",{name:"技术溯源"}).uncheck();
  const posted=page.waitForResponse(r=>r.url().endsWith("/requirements/1/generation-runs")&&r.request().method()==="POST");
  await generation.getByRole("button",{name:"生成候选"}).click();
  assert.equal((await posted).status(),201);
  await generation.getByText("失败 1",{exact:true}).waitFor();
  assert.equal(await editor.getByRole("textbox",{name:"需求业务定义",exact:true}).inputValue(),"人工定义：仅限隔离样本的期末金额，不得被模型覆盖。");
  await page.screenshot({path:path.join(output,"provider-failed-facts-retained.png"),fullPage:true});
  const retried=page.waitForResponse(r=>r.url().includes("/generation-runs/")&&r.url().endsWith("/retry")&&r.request().method()==="POST");
  await generation.getByRole("button",{name:"重试失败项"}).click();
  assert.equal((await retried).status(),200);
  await generation.getByText("已生成 1",{exact:true}).waitFor();
  await generation.getByRole("button",{name:"期末金额 · 业务"}).click();
  const dialog=page.getByRole("dialog",{name:"候选差异"});
  const manual=dialog.getByRole("checkbox",{name:/业务定义.*人工内容/});
  await manual.waitFor();assert.equal(await manual.isChecked(),false);
  const bodyChoice=dialog.getByRole("checkbox",{name:/章节正文.*人工内容/});
  assert.equal(await bodyChoice.isChecked(),false);
  await bodyChoice.check();
  await dialog.getByRole("checkbox",{name:"我确认用候选替换这项人工内容"}).check();
  await page.screenshot({path:path.join(output,"mock-candidate-manual-protected.png"),fullPage:true});
  await dialog.getByRole("button",{name:"加入采用清单"}).click();
  const adopted=page.waitForResponse(r=>r.url().endsWith("/generation-candidates/adopt")&&r.request().method()==="POST");
  await generation.getByRole("button",{name:"应用采用清单（1）"}).click();
  assert.equal((await adopted).status(),200);
  await page.getByText("需求专属口径 · 内容 v4",{exact:true}).waitFor();
  assert.equal(await editor.getByRole("textbox",{name:"需求业务定义",exact:true}).inputValue(),"人工定义：仅限隔离样本的期末金额，不得被模型覆盖。");
  assert.match(await editor.getByRole("textbox",{name:"需求业务口径",exact:true}).inputValue(),/合成验收候选/);
  await editor.getByRole("combobox",{name:"内容历史版本"}).selectOption("3");
  await page.waitForFunction(()=>document.querySelector('[aria-label="需求业务口径"]')?.value==="");
  await page.screenshot({path:path.join(output,"previous-version-unchanged.png"),fullPage:true});
  assert.deepEqual(errors,[]);
  const result={actualApi:true,model:"MockLLMService",failureInjection:"fixture-only-once",failedRetry:true,
    manualDefinitionPreserved:true,explicitAdoptionVersion:4,previousVersionUnchanged:true,pageErrors:errors};
  await writeFile(path.join(output,"results.json"),JSON.stringify(result,null,2));console.log(JSON.stringify(result));
}finally{await browser.close();}

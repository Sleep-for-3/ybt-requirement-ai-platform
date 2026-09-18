import {chromium} from "playwright";
import {mkdir, writeFile} from "node:fs/promises";
import path from "node:path";
import assert from "node:assert/strict";

// Servers are started separately from an isolated build and disposable database.
const origin = "http://127.0.0.1:18742";
const output = path.resolve(process.argv[2]);
await mkdir(output, {recursive:true});
const browser = await chromium.launch({headless:true, channel:"msedge"});
const context = await browser.newContext({viewport:{width:1440,height:1000}, acceptDownloads:true});
const results = [];
try {
  for (const id of [1, 2]) {
    const page = await context.newPage();
    const errors = [];
    page.on("pageerror", error=>errors.push(error.message));
    await page.goto(`${origin}/workspace?projectId=${id}&tableId=${id}&scenarioId=${id}&requirementId=${id}`, {waitUntil:"domcontentloaded"});
    const paths = page.getByRole("region", {name:"核验实际加工路径"});
    await paths.waitFor({state:"visible",timeout:30000});
    await paths.getByLabel("路径核验依据").fill("隔离浏览器核验：来源字段、跨脚本依赖和目标输出逐项确认。");
    const [confirmed] = await Promise.all([
      page.waitForResponse(r=>r.url().endsWith(`/requirements/${id}/paths`)&&r.request().method()==="POST"),
      paths.getByRole("button", {name:"确认路径并建立新修订"}).click()]);
    assert.equal(confirmed.status(), 201);
    const confirmedVersion=(await confirmed.json()).revision.content_version;
    await page.getByText(`需求专属口径 · 内容 v${confirmedVersion}`,{exact:true}).waitFor({timeout:15000});
    await page.getByRole("button", {name:"刷新",exact:true}).waitFor({timeout:15000});
    await paths.getByText(/amount.*已确认/).waitFor({timeout:15000});
    await paths.locator("summary").click();
    await page.screenshot({path:path.join(output, `project-${id}-path.png`),fullPage:true});

    const policy = page.locator('details[aria-label="制度逐条对照"]');
    await policy.locator(":scope > summary").click();
    await policy.locator("ul button").first().click();
    for (const box of await policy.getByRole("checkbox").all()) await box.check();
    await policy.getByLabel("人工判断").selectOption("matched");
    await policy.getByRole("textbox", {name:"核验理由",exact:true}).fill("隔离制度要求期末原值，已逐项核对固定规则。");
    const [compared]=await Promise.all([
      page.waitForResponse(r=>r.url().endsWith(`/requirements/${id}/policy-comparison`)&&r.request().method()==="POST"),
      policy.getByRole("button",{name:"确认本条并保存新修订"}).click()]);
    assert.equal(compared.status(),201);
    const comparedVersion=(await compared.json()).revision.content_version;
    await page.getByText(`需求专属口径 · 内容 v${comparedVersion}`,{exact:true}).waitFor({timeout:15000});

    const [frozen]=await Promise.all([
      page.waitForResponse(r=>r.url().endsWith(`/requirements/${id}/snapshots`)&&r.request().method()==="POST"),
      page.getByRole("button",{name:"保存当前草稿快照"}).click()]);
    assert.equal(frozen.status(),201);
    const snapshots=page.getByRole("region",{name:"需求草稿快照"});
    for (const [label,ext] of [["导出固定草稿","xlsx"],["Word 正文","docx"]]) {
      const download=page.waitForEvent("download");
      await snapshots.getByRole("button",{name:label,exact:true}).first().click();
      await (await download).saveAs(path.join(output,`project-${id}-fixed.${ext}`));
    }
    await page.getByRole("tab",{name:"血缘",exact:true}).click();
    await page.locator(".react-flow__node").first().waitFor({timeout:15000});
    const graph=page.getByRole("region",{name:"需求字段血缘"});
    await graph.screenshot({path:path.join(output,`project-${id}-graph.png`)});
    assert.equal(await graph.locator(".react-flow__node").count(), id===1?2:4);
    assert.deepEqual(errors, []);
    results.push({project:id,actualApi:true,model:"not_called",path:true,comparison:true,
      frozenDownloads:["xlsx","docx"],graphTables:id===1?2:4,pageErrors:errors});
    await page.close();
  }
  await writeFile(path.join(output,"results.json"),JSON.stringify(results,null,2));
  console.log(JSON.stringify(results));
} finally {
  await context.close();
  await browser.close();
}

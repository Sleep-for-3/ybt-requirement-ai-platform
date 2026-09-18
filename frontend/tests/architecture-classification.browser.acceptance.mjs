import {chromium} from "playwright";
import {mkdir,writeFile} from "node:fs/promises";
import path from "node:path";
import assert from "node:assert/strict";

const origin="http://127.0.0.1:18742",output=path.resolve(process.argv[2]);
await mkdir(output,{recursive:true});
const browser=await chromium.launch({headless:true,channel:"msedge"});
const context=await browser.newContext({viewport:{width:1440,height:1000}});
const page=await context.newPage(),errors=[],results=[];
page.on("pageerror",e=>errors.push(e.message));
try{
  for(const id of [1,2]){
    await page.goto(`${origin}/resources/architecture?projectId=${id}`);
    assert.notEqual(await page.locator("body").evaluate(e=>getComputedStyle(e).fontFamily),'"Times New Roman"');
    for(const href of await page.locator('link[rel="stylesheet"]').evaluateAll(items=>items.map(item=>item.href))){
      const css=await context.request.get(href);
      assert.equal(css.status(),200);
      assert.doesNotMatch(await css.text(),/@tailwind|@apply/);
    }
    await page.getByRole("button",{name:id===1?"使用贴源报送示例":"使用多层数仓示例"}).waitFor();
    await page.getByRole("button",{name:id===1?"使用贴源报送示例":"使用多层数仓示例"}).click();
    const [saved]=await Promise.all([
      page.waitForResponse(r=>r.url().endsWith(`/projects/${id}/data-architecture`)&&r.request().method()==="PUT"),
      page.getByRole("button",{name:"保存项目架构",exact:true}).click()]);
    assert.equal(saved.status(),200);
    assert.equal((await saved.json()).definition.layers.length,id===1?3:6);
    const table=page.locator('[id^="table-assignment-"]').first();
    await table.getByRole("combobox",{name:"accounts 层级"}).waitFor();
    assert.equal(await table.getByRole("combobox",{name:"accounts 层级"}).inputValue(),"");
    await page.getByText("分类建议",{exact:true}).click();
    const suggestion=page.locator("details").filter({has:page.getByText("分类建议",{exact:true})});
    await suggestion.getByLabel("Schema",{exact:true}).fill("ods");
    await suggestion.getByLabel("建议层级").selectOption("layer_1");
    await suggestion.getByRole("button",{name:"预览分类建议"}).click();
    await suggestion.getByRole("button",{name:/选择 .*（待确认）/}).click();
    await page.waitForFunction(()=>document.querySelector('[aria-label="accounts 层级"]')?.value==="layer_1");
    assert.equal(await table.getByRole("combobox",{name:"accounts 层级"}).inputValue(),"layer_1");
    const systems=table.getByRole("combobox",{name:"accounts 业务系统"});
    await systems.selectOption({label:`隔离银行${id}核心系统 (CORE)`});
    assert.equal(await systems.getByRole("option").count(),2);
    await table.getByRole("combobox",{name:"accounts 监管模板版本"}).selectOption({index:1});
    await table.getByRole("combobox",{name:"accounts 监管标准表"}).selectOption({index:1});
    const [classified]=await Promise.all([
      page.waitForResponse(r=>r.url().endsWith("/classification")&&r.request().method()==="PUT"),
      table.getByRole("button",{name:"确认归属"}).click()]);
    assert.equal(classified.status(),200);
    const assignment=(await classified.json()).assignment;
    assert.equal(assignment.layer_key,"layer_1");
    assert.equal(assignment.business_system_name,`隔离银行${id}核心系统`);
    assert.equal(assignment.target_table_code,"REPORT");
    assert.equal(assignment.template_version_no,1);
    await page.reload();
    await page.getByRole("combobox",{name:"accounts 业务系统"}).waitFor();
    assert.equal(await page.getByRole("combobox",{name:"accounts 层级"}).inputValue(),"layer_1");
    await page.screenshot({path:path.join(output,`bank-${id}-assignment.png`),fullPage:true});
    await page.goto(`${origin}/catalog?projectId=${id}`);
    await page.getByText(new RegExp(`隔离银行${id}核心系统.*REPORT.*v1`)).waitFor();
    await page.screenshot({path:path.join(output,`bank-${id}-catalog.png`),fullPage:true});
    await page.goto(`${origin}/datasources/${id}/catalog?projectId=${id}`);
    const source=page.getByRole("region",{name:"数据源物理表归属"});
    await source.getByText(new RegExp(`隔离银行${id}核心系统.*REPORT.*v1`)).waitFor();
    await source.screenshot({path:path.join(output,`bank-${id}-datasource.png`)});
    await page.goto(`${origin}/lineage/nebula?projectId=${id}`);
    await page.getByRole("button",{name:/accounts.*数据目录/}).click();
    const card=page.locator(".react-flow__node").first();
    await card.getByText(new RegExp(`隔离银行${id}核心系统.*REPORT.*v1`)).waitFor();
    await card.screenshot({path:path.join(output,`bank-${id}-live-lineage.png`)});
    await page.goto(`${origin}/resources/architecture?projectId=${id}`);
    const layerName=page.getByRole("textbox",{name:"层级名称 2",exact:true});
    await layerName.fill(`银行${id}已更名层级`);
    await layerName.locator("..").getByRole("checkbox").uncheck();
    const [renamed]=await Promise.all([
      page.waitForResponse(r=>r.url().endsWith(`/projects/${id}/data-architecture`)&&r.request().method()==="PUT"),
      page.getByRole("button",{name:"保存项目架构",exact:true}).click()]);
    assert.equal(renamed.status(),200);
    await page.goto(`${origin}/catalog?projectId=${id}`);
    await page.getByText(new RegExp(`银行${id}已更名层级.*已停用.*隔离银行${id}核心系统`)).waitFor();
    await page.screenshot({path:path.join(output,`bank-${id}-renamed-disabled.png`),fullPage:true});
    results.push({bank:id,layers:id===1?3:6,threeIndependentAssignments:true,optionsProjectScoped:true,
      catalogLabels:true,datasourceLabels:true,liveLineageLabels:true,renamedAndDisabledLayerVisible:true});
  }
  await page.goto(`${origin}/resources/architecture?projectId=2`);
  await page.getByRole("combobox",{name:"accounts 层级"}).waitFor();
  await page.setViewportSize({width:390,height:844});
  await page.screenshot({path:path.join(output,"mobile-architecture.png"),fullPage:true});
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth),true);
  assert.deepEqual(errors,[]);
  await writeFile(path.join(output,"results.json"),JSON.stringify({results,mobileNoOverflow:true,pageErrors:errors,model:"not_called"},null,2));
  console.log(JSON.stringify(results));
}finally{await context.close();await browser.close();}

import assert from "node:assert/strict";
import test from "node:test";

import { createSemanticCatalogBrowser } from "./semantic-catalog-browser-harness.mjs";

test("production browser catalog drives the real route through a project switch", async () => {
  const browser = await createSemanticCatalogBrowser();
  try {
    await browser.navigate("/semantics?projectId=1");
    await browser.waitForText("项目 A 唯一概念");
    assert.equal(await browser.text("main"), "项目 A 唯一概念");
  } finally {
    await browser.close();
  }
});

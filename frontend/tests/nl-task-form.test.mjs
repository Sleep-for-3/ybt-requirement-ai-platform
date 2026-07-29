import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const pageSource = await readFile(
  new URL("../app/tasks/page.tsx", import.meta.url),
  "utf8"
);

test("natural-language task creation keeps the form element across async work", () => {
  assert.match(pageSource, /const formElement = event\.currentTarget;/);
  assert.match(pageSource, /new FormData\(formElement\)/);
  assert.match(pageSource, /formElement\.reset\(\)/);

  const firstAwait = pageSource.indexOf("await apiPost", pageSource.indexOf("async function create"));
  assert.notEqual(firstAwait, -1);
  assert.equal(
    pageSource.slice(firstAwait).includes("event.currentTarget"),
    false,
    "event.currentTarget must not be read after the async boundary"
  );
});

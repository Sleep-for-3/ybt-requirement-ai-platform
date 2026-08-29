import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const workspace = readFileSync(new URL("../components/requirement-workspace/RequirementWorkspace.tsx", import.meta.url), "utf8");
const editor = readFileSync(new URL("../components/requirement-workspace/SelectedFieldEditor.tsx", import.meta.url), "utf8");
const preview = readFileSync(new URL("../components/requirement-workspace/DocumentPreview.tsx", import.meta.url), "utf8");

test("high-frequency editor text lives below RequirementWorkspace", () => {
  assert.doesNotMatch(workspace, /setBusinessFinal|setTechnicalFinal/);
  assert.match(editor, /useState\(initialBusinessFinal\)/);
  assert.match(editor, /useState\(initialTechnicalFinal\)/);
  assert.match(editor, /beforeunload/);
  assert.match(editor, /nextBusinessFinal !== initialBusinessFinal/);
  assert.match(editor, /nextTechnicalFinal !== initialTechnicalFinal/);
});

test("document preview indexes repeated entity lookups", () => {
  assert.match(preview, /martFieldsById/);
  assert.match(preview, /martTablesById/);
  assert.doesNotMatch(preview, /martFields\.find/);
  assert.doesNotMatch(preview, /martTables\.find/);
});

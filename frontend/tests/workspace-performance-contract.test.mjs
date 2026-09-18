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

test("requirement sibling panels have distinct React keys during refresh", () => {
  const keys = ["RequirementGenerationPanel", "RequirementSnapshotsPanel", "RequirementDeliveryPanel"].map(name => {
    const match = workspace.match(new RegExp('<' + name + ' key=\\{`([^`]+)`\\}'));
    assert.ok(match, `${name} must have a stable key`);
    return match[1];
  });
  assert.equal(new Set(keys).size, keys.length);
});

test("script repository forms submit and keep their element across async requests", () => {
  const scripts = readFileSync(new URL("../app/lineage/scripts/page.tsx", import.meta.url), "utf8");
  assert.match(scripts, /AsyncActionButton type="submit" actionStatus=\{ingestAction.status\}/);
  assert.match(scripts, /AsyncActionButton type="submit" actionStatus=\{repoAction.status\}/);
  assert.doesNotMatch(scripts, /event.currentTarget.reset\(/);
});

test("architecture separates layer, business system and confirmed regulatory version", () => {
  const architecture = readFileSync(new URL("../app/resources/architecture/page.tsx", import.meta.url), "utf8");
  assert.match(architecture, /classification-options/);
  assert.match(architecture, /business_system_id/);
  assert.match(architecture, /template_version_id/);
  assert.match(architecture, /target_table_id/);
  assert.match(architecture, /预览分类建议/);
  assert.match(architecture, /确认归属/);
  assert.doesNotMatch(architecture, /className="(?:input|btn-primary|btn-secondary)"/);
});

test("script and policy review expose deterministic aggregation and code conversion facts", () => {
  const script = readFileSync(new URL("../components/requirement-workspace/RequirementScriptPanel.tsx", import.meta.url), "utf8");
  const policy = readFileSync(new URL("../components/requirement-workspace/RequirementPolicyPanel.tsx", import.meta.url), "utf8");
  for (const source of [script, policy]) {
    assert.match(source, /aggregation_rule/);
    assert.match(source, /code_mapping_rule/);
    assert.match(source, /聚合：/);
    assert.match(source, /码值转换：/);
  }
});

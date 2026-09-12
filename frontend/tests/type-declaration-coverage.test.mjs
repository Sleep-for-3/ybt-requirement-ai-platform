/**
 * Guards the contract that broke the first production image build.
 *
 * ``tsconfig.json`` runs with ``allowJs: false`` and ``strict: true``, so any
 * ``import ... from "@/lib/<name>.mjs"`` inside a ``.ts``/``.tsx`` file fails
 * ``next build`` unless a sibling ``<name>.d.mts`` declaration exists (or the
 * author deliberately marked the import with ``@ts-expect-error``).
 *
 * ``npm test`` runs on the host without a TypeScript pass, which is exactly why
 * the defect only surfaced inside ``docker compose build``.  This test keeps the
 * runtime ``.mjs`` modules and their declarations in sync.
 */

import assert from "node:assert/strict";
import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const frontendRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const SOURCE_ROOTS = ["app", "components", "hooks", "lib"];
const IMPORT_PATTERN = /import\s+(?:type\s+)?[^"']*from\s+"(@\/lib\/[^"']+\.mjs)"/;

function walkTypeScriptFiles(directory) {
  const found = [];
  for (const entry of readdirSync(directory)) {
    const absolute = path.join(directory, entry);
    if (statSync(absolute).isDirectory()) {
      if (entry === "node_modules" || entry.startsWith(".next")) continue;
      found.push(...walkTypeScriptFiles(absolute));
      continue;
    }
    if (entry.endsWith(".ts") || entry.endsWith(".tsx")) found.push(absolute);
  }
  return found;
}

test("every @/lib/*.mjs import from TypeScript has a declaration or an explicit suppression", () => {
  const missing = [];
  for (const file of SOURCE_ROOTS.flatMap((name) => walkTypeScriptFiles(path.join(frontendRoot, name)))) {
    const lines = readFileSync(file, "utf8").split(/\r?\n/);
    lines.forEach((line, index) => {
      const match = IMPORT_PATTERN.exec(line);
      if (!match) return;
      const specifier = match[1];
      const modulePath = path.join(frontendRoot, specifier.slice("@/".length));
      if (existsSync(modulePath.replace(/\.mjs$/, ".d.mts"))) return;
      if ((lines[index - 1] || "").includes("@ts-expect-error")) return;
      missing.push(`${path.relative(frontendRoot, file).replace(/\\/g, "/")}:${index + 1} -> ${specifier}`);
    });
  }
  assert.deepEqual(
    missing,
    [],
    `这些 .mjs 模块缺少 .d.mts 声明，生产构建会在 next build 的 type-check 阶段失败：\n${missing.join("\n")}`
  );
});

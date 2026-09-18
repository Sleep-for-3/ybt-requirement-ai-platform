import assert from "node:assert/strict";
import { readFileSync, readdirSync, statSync } from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { createClientId } from "../lib/client-id.mjs";

test("client ids use randomUUID when the secure-context API is available", () => {
  const calls = [];
  const id = createClientId("layer_", {
    randomUUID() {
      calls.push("randomUUID");
      return "12345678-1234-1234-1234-123456789abc";
    }
  });
  assert.equal(id, "layer_12345678123412341234123456789abc");
  assert.deepEqual(calls, ["randomUUID"]);
});

test("client ids fall back to getRandomValues behind plain HTTP", () => {
  const id = createClientId("upload-", {
    getRandomValues(bytes) {
      bytes.set(Array.from({ length: 16 }, (_, index) => index));
    }
  });
  assert.equal(id, "upload-000102030405060708090a0b0c0d0e0f");
});

test("client ids remain usable when the Web Crypto object is unavailable", () => {
  const id = createClientId("fallback-", {});
  assert.match(id, /^fallback-[a-z0-9]+$/);
  assert.ok(id.length >= 24);
});

test("application code does not call crypto.randomUUID without a fallback", () => {
  const frontendRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
  const sourceRoots = ["app", "components"];
  const offenders = [];
  function walk(directory) {
    for (const entry of readdirSync(directory)) {
      const absolute = path.join(directory, entry);
      if (statSync(absolute).isDirectory()) {
        if (entry === "node_modules" || entry.startsWith(".next")) continue;
        walk(absolute);
        continue;
      }
      if (!entry.endsWith(".ts") && !entry.endsWith(".tsx")) continue;
      const source = readFileSync(absolute, "utf8");
      if (/crypto\.randomUUID\s*\(/.test(source)) offenders.push(path.relative(frontendRoot, absolute));
    }
  }
  for (const root of sourceRoots) walk(path.join(frontendRoot, root));
  assert.deepEqual(offenders, []);
});

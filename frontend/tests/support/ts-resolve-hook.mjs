/**
 * 测试专用 ESM 解析钩子。
 *
 * 产品源码（Next.js 打包）允许省略扩展名导入，例如 `lib/api.ts` 里的 `./query-client`
 * 与 `@/lib/...`。Node 原生 ESM 不做这种解析，因此**直接**在 node:test 里 import api.ts 会
 * ERR_MODULE_NOT_FOUND。这个钩子只补上解析规则，让回归能驱动**真实**的 API 客户端
 * （而不是把逻辑抽成只为测试存在的替身）。
 *
 * 只影响测试进程的模块解析，不修改任何产品源码，也不改变打包行为。
 */
import { existsSync } from "node:fs";
import { fileURLToPath, pathToFileURL } from "node:url";
import path from "node:path";

const CANDIDATE_SUFFIXES = [".ts", ".tsx", ".mts", ".mjs", ".js", "/index.ts", "/index.mjs"];

// 钩子位于 frontend/tests/support/，因此 frontend 根目录要上溯两级（曾误写为一级，
// 导致 `@/lib/x` 被映射到 frontend/tests/lib/x 而解析失败）。
const FRONTEND_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");

/** 把 `@/x` 映射到 frontend/x，并给无扩展名说明符尝试补全。 */
export async function resolve(specifier, context, nextResolve) {
  let candidate = specifier;
  if (specifier.startsWith("@/")) {
    candidate = pathToFileURL(path.join(FRONTEND_ROOT, specifier.slice(2))).href;
  }
  const hasExtension = /\.(?:[cm]?[jt]sx?|json|mjs|cjs)$/.test(candidate);
  if (candidate.startsWith("file:") && !hasExtension) {
    const base = fileURLToPath(candidate);
    for (const suffix of CANDIDATE_SUFFIXES) {
      const probe = base + suffix;
      if (existsSync(probe)) return { shortCircuit: true, url: pathToFileURL(probe).href };
    }
  }
  // 相对说明符（./query-client）先按父模块 URL 定位，再补扩展名；
  // Node 原生 ESM 不会自己尝试 .ts，所以必须在这里展开。
  const bases = [];
  if (candidate.startsWith(".")) {
    if (context.parentURL) bases.push(new URL(candidate, context.parentURL));
  } else if (candidate.startsWith("file:")) {
    bases.push(new URL(candidate));
  }
  for (const baseUrl of bases) {
    const base = fileURLToPath(baseUrl);
    for (const suffix of CANDIDATE_SUFFIXES) {
      const probe = base + suffix;
      if (existsSync(probe)) return { shortCircuit: true, url: pathToFileURL(probe).href };
    }
  }
  return nextResolve(candidate, context);
}

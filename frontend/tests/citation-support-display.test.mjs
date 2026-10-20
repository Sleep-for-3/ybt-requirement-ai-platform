/**
 * B 包前端契约：引用支撑校验结果必须用清楚中文展示
 * 「哪些结论有依据 / 哪些无法验证 / 为何降级」，且不得把底层错误串摆给用户。
 *
 * 所有断言都走 `lib/knowledge-contract.mjs` 里的纯函数——页面只做渲染，
 * 所以这里测的就是页面实际用的那份逻辑（不存在“测试一套、页面另一套”）。
 */

import assert from "node:assert/strict";
import test from "node:test";

import {
  answerStatusNotice,
  coverageText,
  supportCounts,
  supportVerificationNotice,
} from "../lib/knowledge-contract.mjs";

const CJK = /[\u4e00-\u9fff]/;
const ASCII_LETTER = /[A-Za-z]/;

test("关闭开关时不得声称已验证，也不得凭空降级", () => {
  // 生产默认 citation_support_check="off"：后端不返回 citation_support。
  const notice = answerStatusNotice({ answer_status: "grounded" });
  assert.equal(notice.verification, null);
  assert.equal(notice.tone, "neutral");
  assert.match(notice.text, /已找到依据/);
  assert.doesNotMatch(notice.text, /验证通过/);
  assert.doesNotMatch(notice.text, /语义验证/);
  assert.doesNotMatch(notice.text, /引用支撑校验通过/);

  // 明确 enabled=false 的返回同样不得出现“已验证”字样。
  const disabled = answerStatusNotice({
    answer_status: "grounded",
    citation_support: { enabled: false, verification: null },
  });
  assert.equal(disabled.verification, null);
  assert.doesNotMatch(disabled.text, /验证通过/);
});

test("三种基础回答状态保留原有中文口径", () => {
  assert.match(
    answerStatusNotice({ answer_status: "degraded" }).text,
    /回答服务暂不可用/
  );
  assert.match(
    answerStatusNotice({ answer_status: "needs_confirmation" }).text,
    /证据不足或尚未确认/
  );
  assert.match(answerStatusNotice({ answer_status: "grounded" }).text, /已找到依据/);
  assert.equal(answerStatusNotice({ answer_status: "degraded" }).tone, "danger");
});

test("unsupported / 未验证 / 降级都用中文说明为何不可信", () => {
  const unsupported = answerStatusNotice({
    answer_status: "needs_confirmation",
    citation_support: { enabled: true, verification: "unsupported", claims_total: 2, claims_judged: 2, claims_unsupported: 2 },
  });
  assert.match(unsupported.text, /缺少引用支撑/);
  assert.doesNotMatch(unsupported.text, /验证通过/);

  const unknown = answerStatusNotice({
    answer_status: "needs_confirmation",
    citation_support: { enabled: true, verification: "unknown", claims_total: 2, claims_judged: 0, claims_unjudged: 2 },
  });
  assert.match(unknown.text, /无法验证/);
  assert.match(unknown.text, /另有 2 条结论未能判定/);
  assert.equal(unknown.tone, "warning");

  const degraded = answerStatusNotice({
    answer_status: "needs_confirmation",
    citation_support: { enabled: true, verification: "degraded", degraded_reason: "timeout" },
  });
  assert.match(degraded.text, /校验失败/);
  // 底层错误串绝不能上页面。
  assert.doesNotMatch(degraded.text, /timeout/);
  assert.doesNotMatch(degraded.text, ASCII_LETTER);
});

test("已验证与部分支撑的措辞不会互相冒用", () => {
  const verified = answerStatusNotice({
    answer_status: "grounded",
    citation_support: { enabled: true, verification: "verified", claims_total: 1, claims_judged: 1, claim_coverage: 1 },
  });
  assert.equal(verified.verification, "verified");
  assert.equal(verified.tone, "neutral");
  assert.match(verified.text, /校验通过/);
  assert.match(verified.text, /结论与引用一致/);

  const partial = answerStatusNotice({
    answer_status: "needs_confirmation",
    citation_support: { enabled: true, verification: "partially_supported", claims_total: 2, claims_judged: 2, claims_supported: 1, claims_unsupported: 1 },
  });
  assert.match(partial.text, /部分结论有引用支撑/);
  assert.doesNotMatch(partial.text, /校验通过：结论与引用一致/);
});

test("未知 verdict 一律收敛为中文，绝不回显原始英文值", () => {
  for (const raw of ["something_new", "PARTIAL", "RuntimeError", undefined]) {
    const text = supportVerificationNotice({ verification: raw, claims_total: 1, claims_judged: 1 });
    assert.match(text, CJK, `verdict ${raw} 必须给出中文说明`);
    assert.doesNotMatch(text, /RuntimeError/);
    assert.doesNotMatch(text, /something_new/);
    assert.doesNotMatch(text, /PARTIAL/);
  }
});

test("计数与覆盖率必须带分母，且截断要显式暴露", () => {
  const full = supportCounts({ claims_total: 25, claims_judged: 25, claims_unjudged: 0, claims_supported: 25 });
  assert.equal(full.total, 25);
  assert.equal(full.judged, 25);
  assert.equal(full.unjudged, 0);
  assert.equal(coverageText(full.coverage), "—");

  const truncated = supportCounts({
    claims_total: 70,
    claims_judged: 60,
    claims_unjudged: 10,
    claim_coverage: 0.8571,
    coverage_truncated: true,
  });
  assert.equal(truncated.truncated, true);
  assert.equal(truncated.unjudged, 10);
  assert.equal(coverageText(truncated.coverage), "86%");

  // 分母为 0 时展示 “—”，不得伪装成 100%。
  assert.equal(coverageText(null), "—");
  assert.equal(coverageText(undefined), "—");
  assert.equal(coverageText(1), "100%");
});

test("缺字段与脏数据不得抛异常", () => {
  for (const value of [null, undefined, {}, { citation_support: null }]) {
    const notice = answerStatusNotice(value);
    assert.ok(typeof notice.text === "string" && notice.text.length > 0);
    assert.ok(["neutral", "warning", "danger"].includes(notice.tone));
  }
  for (const value of [null, undefined, {}, { claims_total: "x" }]) {
    assert.doesNotThrow(() => supportCounts(value));
    assert.doesNotThrow(() => supportVerificationNotice(value));
  }
});

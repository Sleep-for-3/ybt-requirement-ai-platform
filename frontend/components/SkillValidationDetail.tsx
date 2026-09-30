"use client";

const GATES: Record<string, string> = {
  tests_passed: "所需测试已通过", test_cases_required: "请先添加固定测试用例",
  release_gate_failed: "缺少当前版本的有效测试，或测试未通过。请重新运行确定性及对应模型测试。",
  test_project_required: "请选择测试项目", skill_dependency_changed: "依赖已变化，请恢复为新草稿重新测试。",
};
const ASSERTIONS: Record<string, string> = {
  schema: "输入结构", scope: "项目范围", budget: "上下文预算", unknown_reference_rejected: "拒绝未知引用",
  native_unknown_reference_rejected: "拒绝未知业务引用", native_unknown_physical_source_rejected: "拒绝未知物理来源",
  model_output_valid: "模型输出校验", minimum_claims: "最少声明数量", required_gaps: "必要缺口说明",
};
type Detail = { gate?: string; release_ready?: boolean; mode?: string; status?: string;
  metrics?: { total: number; passed: number }; from_version?: number; to_version?: number;
  changes?: { field: string; before: unknown; after: unknown }[];
  results?: { case_id: number; passed: boolean | null; error_code: string | null; assertions: Record<string, boolean> }[] };
function text(value: unknown) { return typeof value === "string" ? value : JSON.stringify(value, null, 2) ?? "未设置"; }

export function SkillValidationDetail({ value }: { value: unknown }) {
  if (!value || typeof value !== "object") return null;
  const detail = value as Detail;
  return <section aria-label="验证与对比摘要" className="space-y-3 rounded border bg-slate-50 p-3 text-sm">
    {detail.gate && <><h3 className="font-semibold">发布条件</h3><p>{GATES[detail.gate] || detail.gate}</p><p>{detail.release_ready ? "已具备提交给独立审批人的发布条件。" : "当前尚不能发布；请完成测试并提交独立审批。"}</p></>}
    {detail.metrics && <><h3 className="font-semibold">测试结果</h3><p>{detail.metrics.passed} / {detail.metrics.total} 个用例通过{detail.status === "pending_review" ? "，等待独立人工评审" : ""}。</p></>}
    {detail.results?.map(result => <div key={result.case_id} className="rounded border bg-white p-2"><p className={result.passed === null ? "text-amber-800" : result.passed ? "text-emerald-800" : "text-red-800"}>用例 #{result.case_id} · {result.passed === null ? "待人工评审" : result.passed ? "通过" : "未通过"}</p>
      {result.error_code && <p>错误：{result.error_code}</p>}
      <ul className="mt-1 flex flex-wrap gap-x-4 gap-y-1">{Object.entries(result.assertions).map(([key, passed]) => <li key={key}>{ASSERTIONS[key] || key}：{passed ? "通过" : "未通过"}</li>)}</ul></div>)}
    {detail.changes && <><h3 className="font-semibold">版本对比：v{detail.from_version} → v{detail.to_version}</h3>
      {!detail.changes.length && <p>两个版本的配置内容相同。</p>}
      {detail.changes.map(change => <div key={change.field} className="space-y-1"><h4 className="font-medium">{change.field}</h4><div className="grid gap-2 md:grid-cols-2"><div><p>v{detail.from_version}</p><pre className="overflow-auto whitespace-pre-wrap break-all rounded bg-white p-2 text-xs">{text(change.before)}</pre></div><div><p>v{detail.to_version}</p><pre className="overflow-auto whitespace-pre-wrap break-all rounded bg-white p-2 text-xs">{text(change.after)}</pre></div></div></div>)}</>}
  </section>;
}

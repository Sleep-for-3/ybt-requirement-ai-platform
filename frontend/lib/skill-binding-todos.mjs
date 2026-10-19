function versionText(item) {
  const latest = item && item.latest_published;
  if (!latest || !Number.isFinite(Number(latest.version_no))) return "尚无已发布版本";
  return `可固定 v${Number(latest.version_no)}`;
}

/**
 * Turn `GET /ai-skills/binding-todos` into the sentence the configuration centre shows.
 *
 * A published version is never adopted on its own, so the only thing this view may do is
 * tell the operator what is still un-pinned and which version they would pin by acting.
 * Nothing here binds anything: the caller still posts to `/bindings` on a human click.
 */
export function bindingTodoView(todos) {
  const list = Array.isArray(todos) ? todos.filter((item) => item && typeof item === "object") : [];
  if (!list.length) return null;
  const items = list.map((item) => ({
    skill_key: String(item.skill_key ?? ""),
    display_name: String(item.display_name ?? item.skill_key ?? ""),
    reason: item.reason === "no_binding" ? "no_binding" : "no_published_version",
    available: item.available === true,
    version_no: Number.isFinite(Number(item.latest_published?.version_no)) ? Number(item.latest_published.version_no) : null,
    detail: versionText(item),
  }));
  const actionable = items.filter((item) => item.available);
  const waiting = items.filter((item) => !item.available);
  const parts = [];
  if (actionable.length) parts.push(`${actionable.length} 个已发布待固定：${actionable.map((item) => `${item.display_name} ${item.detail}`).join("；")}`);
  if (waiting.length) parts.push(`${waiting.length} 个尚无已发布版本：${waiting.map((item) => item.display_name).join("；")}`);
  return {
    count: items.length,
    actionable: actionable.length,
    items,
    message: `本范围还有 ${items.length} 个技能未固定采用版本。${parts.join("。")}。`,
  };
}

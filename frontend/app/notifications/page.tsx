"use client";

import { Bell } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { WorkspaceHeader } from "@/components/WorkspaceHeader";
import { apiGet, apiPost } from "@/lib/api";
import { entityLabel, severityLabel } from "@/lib/product-language";

type Notice = {
  id: number;
  notification_type: string;
  title: string;
  content: string;
  resource_type?: string | null;
  resource_id?: string | null;
  read_at?: string | null;
  created_at: string;
};

export default function Page() {
  const [items, setItems] = useState<Notice[]>([]);
  const [filter, setFilter] = useState<"all" | "unread" | "review" | "risk" | "system">("all");
  const router = useRouter();

  async function reload() {
    setItems(await apiGet("/me/notifications"));
  }

  useEffect(() => {
    void reload();
  }, []);

  const visibleItems = items.filter((item) => {
    if (filter === "unread") return !item.read_at;
    if (filter === "review") return /review|task|approval|confirm/i.test(item.notification_type);
    if (filter === "risk") return /risk|impact|drift|failed|error|due/i.test(item.notification_type);
    if (filter === "system") return !/review|task|approval|confirm|risk|impact|drift|failed|error|due/i.test(item.notification_type);
    return true;
  });

  function notificationHref(item: Notice): string | null {
    if (!item.resource_type || !item.resource_id) return null;
    const id = encodeURIComponent(item.resource_id);
    const routes: Record<string, string> = {
      review_task: `/tasks/${id}`,
      deliverable: `/deliverables/${id}`,
      target_field: `/fields/${id}`,
      datasource: `/datasources/${id}/catalog`,
      impact: `/lineage/impacts/${id}`
    };
    return routes[item.resource_type] || null;
  }

  return (
    <main>
      <WorkspaceHeader title="通知中心" meta={`${items.filter((item) => !item.read_at).length} 条未读`} />
      <div className="mx-auto max-w-4xl p-4 lg:p-6">
        <div className="mb-4 flex flex-wrap gap-2" role="tablist" aria-label="通知筛选">
          {(["all", "unread", "review", "risk", "system"] as const).map((value) => {
            const labels = { all: "全部", unread: "未读", review: "审核", risk: "风险", system: "系统" };
            return <button aria-selected={filter === value} className={filter === value ? "button-primary" : "button-secondary"} key={value} onClick={() => setFilter(value)} role="tab" type="button">{labels[value]}</button>;
          })}
        </div>
        {visibleItems.length ? (
          <section className="panel divide-y divide-line overflow-hidden">
            {visibleItems.map((item) => {
              const href = notificationHref(item);
              const category = /review|task|approval|confirm/i.test(item.notification_type) ? "审核" : /risk|impact|drift|failed|error|due/i.test(item.notification_type) ? "风险" : "系统";
              const severity = category === "风险" ? "high" : category === "审核" ? "medium" : "info";
              return (
              <button
                className={`block w-full p-4 text-left transition-colors hover:bg-mist ${
                  item.read_at ? "bg-white" : "border-l-2 border-l-pine bg-pine-50/40"
                }`}
                key={item.id}
                onClick={async () => {
                  await apiPost(`/notifications/${item.id}/read`, {});
                  if (href) router.push(href);
                  else await reload();
                }}
              >
                <div className="flex items-center gap-2">
                  <b className="text-sm text-ink">{item.title}</b>
                  {!item.read_at ? <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-pine" /> : null}
                </div>
                <div className="mt-1 text-sm text-slate-600">{item.content}</div>
                <div className="mt-2 flex items-center gap-2 text-xs text-slate-400">
                  <span className={category === "风险" ? "badge-danger" : category === "审核" ? "badge-warning" : "badge-neutral"}>{category}</span>
                  <span>{entityLabel(item.resource_type)}</span>
                  <span>{severityLabel(severity)}</span>
                  <span>{item.created_at}</span>
                </div>
              </button>
              );
            })}
          </section>
        ) : (
          <div className="empty-state">
            <Bell className="text-slate-300" size={28} />
            <p>{items.length ? "当前筛选下暂无通知" : "暂无通知，任务分派与评审进展会第一时间推送到这里"}</p>
          </div>
        )}
      </div>
    </main>
  );
}

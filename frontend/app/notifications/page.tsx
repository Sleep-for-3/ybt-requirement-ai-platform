"use client";

import { Bell } from "lucide-react";
import { useEffect, useState } from "react";

import { WorkspaceHeader } from "@/components/WorkspaceHeader";
import { apiGet, apiPost } from "@/lib/api";

type Notice = {
  id: number;
  notification_type: string;
  title: string;
  content: string;
  read_at?: string | null;
  created_at: string;
};

export default function Page() {
  const [items, setItems] = useState<Notice[]>([]);

  async function reload() {
    setItems(await apiGet("/me/notifications"));
  }

  useEffect(() => {
    void reload();
  }, []);

  return (
    <main>
      <WorkspaceHeader title="通知中心" meta={`${items.filter((item) => !item.read_at).length} 条未读`} />
      <div className="mx-auto max-w-4xl p-4 lg:p-6">
        {items.length ? (
          <section className="panel divide-y divide-line overflow-hidden">
            {items.map((item) => (
              <button
                className={`block w-full p-4 text-left transition-colors hover:bg-mist ${
                  item.read_at ? "bg-white" : "border-l-2 border-l-pine bg-pine-50/40"
                }`}
                key={item.id}
                onClick={async () => {
                  await apiPost(`/notifications/${item.id}/read`, {});
                  await reload();
                }}
              >
                <div className="flex items-center gap-2">
                  <b className="text-sm text-ink">{item.title}</b>
                  {!item.read_at ? <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-pine" /> : null}
                </div>
                <div className="mt-1 text-sm text-slate-600">{item.content}</div>
                <div className="mt-2 flex items-center gap-2 text-xs text-slate-400">
                  <span className="badge-neutral">{item.notification_type}</span>
                  <span>{item.created_at}</span>
                </div>
              </button>
            ))}
          </section>
        ) : (
          <div className="empty-state">
            <Bell className="text-slate-300" size={28} />
            <p>暂无通知，任务分派与评审进展会第一时间推送到这里</p>
          </div>
        )}
      </div>
    </main>
  );
}

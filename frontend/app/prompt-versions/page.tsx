"use client";

import { useEffect, useState } from "react";
import { ScrollText } from "lucide-react";

import { WorkspaceHeader } from "@/components/WorkspaceHeader";
import { apiGet } from "@/lib/api";

export default function Page() {
  const [items, setItems] = useState<Record<string, unknown>[]>([]);

  useEffect(() => {
    void apiGet<Record<string, unknown>[]>("/prompt-versions").then(setItems);
  }, []);

  return (
    <main>
      <WorkspaceHeader title="Prompt 版本" meta="普通顾问只读" />
      <div className="mx-auto max-w-5xl p-4 lg:p-6">
        {items.length ? (
          <section className="panel overflow-hidden">
            <div className="panel-header">
              <h2 className="text-[15px] font-semibold text-ink">版本记录</h2>
            </div>
            <pre className="overflow-auto p-4 text-xs leading-relaxed text-slate-600">{JSON.stringify(items, null, 2)}</pre>
          </section>
        ) : (
          <div className="empty-state">
            <ScrollText className="text-slate-300" size={28} />
            <p>暂无 Prompt 版本记录，提示词发布新版本后会在这里展示</p>
          </div>
        )}
      </div>
    </main>
  );
}

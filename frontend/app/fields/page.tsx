"use client";

import { ArrowRight } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { useProjectWorkspace } from "@/components/ProjectContext";
import { WorkspaceHeader } from "@/components/WorkspaceHeader";
import { ProductScenario, TargetField, apiGet } from "@/lib/api";

export default function FieldsPage() {
  const { projectId } = useProjectWorkspace();
  const [fields, setFields] = useState<TargetField[]>([]);
  const [scenarios, setScenarios] = useState<ProductScenario[]>([]);

  useEffect(() => {
    if (!projectId) return;
    void Promise.all([
      apiGet<TargetField[]>(`/fields?project_id=${projectId}`),
      apiGet<ProductScenario[]>(`/projects/${projectId}/scenarios`),
    ]).then(([fieldItems, scenarioItems]) => { setFields(fieldItems); setScenarios(scenarioItems); });
  }, [projectId]);

  return (
    <main>
      <WorkspaceHeader title="字段场景" meta={`${fields.length} 个字段 / ${scenarios.length} 个产品场景`} />
      <div className="mx-auto max-w-[1500px] p-4 lg:p-6">
        <div className="panel overflow-hidden">
          <div className="grid grid-cols-[180px_1fr_150px_100px] border-b border-line bg-slate-50 px-4 py-2 text-xs font-semibold text-slate-500">
            <span>数据项编码</span><span>数据项名称 / 监管口径</span><span>数据格式</span><span>操作</span>
          </div>
          {fields.map((field) => (
            <div className="grid grid-cols-[180px_1fr_150px_100px] items-center border-b border-line px-4 py-3 text-sm last:border-0" key={field.id}>
              <span className="font-mono text-xs">{field.field_code}</span>
              <div><div className="font-medium">{field.field_name}</div><div className="mt-1 line-clamp-2 text-xs text-slate-500">{field.regulatory_refined_definition || field.regulatory_description || field.field_definition || "-"}</div></div>
              <span>{field.data_format || field.field_type || "-"}</span>
              <Link className="button-secondary" href={`/fields/${field.id}/scenarios`} title="进入场景工作台"><ArrowRight size={16} /></Link>
            </div>
          ))}
        </div>
      </div>
    </main>
  );
}

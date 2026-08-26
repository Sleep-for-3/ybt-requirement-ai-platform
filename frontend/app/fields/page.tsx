"use client";

import { ArrowRight, Table2 } from "lucide-react";
import { useEffect, useState } from "react";

import { useProjectWorkspace } from "@/components/ProjectContext";
import { StatefulLink } from "@/components/StatefulLink";
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
        {fields.length ? (
          <div className="panel overflow-hidden">
            <div className="grid-head grid grid-cols-[180px_1fr_150px_100px]">
              <span>数据项编码</span>
              <span>数据项名称 / 监管口径</span>
              <span>数据格式</span>
              <span>操作</span>
            </div>
            {fields.map((field) => (
              <div className="grid-row grid grid-cols-[180px_1fr_150px_100px] items-center" key={field.id}>
                <span className="font-mono text-xs">{field.field_code}</span>
                <div>
                  <div className="font-medium text-ink">{field.field_name}</div>
                  <div className="mt-1 line-clamp-2 text-xs text-slate-500">
                    {field.regulatory_refined_definition || field.regulatory_description || field.field_definition || "-"}
                  </div>
                </div>
                <span>{field.data_format || field.field_type || "-"}</span>
                <StatefulLink className="button-secondary" href={`/fields/${field.id}/scenarios`} title="进入场景工作台">
                  <ArrowRight size={16} />
                </StatefulLink>
              </div>
            ))}
          </div>
        ) : (
          <div className="empty-state">
            <Table2 className="text-slate-300" size={28} />
            <p>还没有字段，请先在项目初始化中导入监管需求模板并完成字段解析</p>
          </div>
        )}
      </div>
    </main>
  );
}

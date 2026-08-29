"use client";

import { Check, Save, ShieldAlert } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import type { FieldWorkspaceRecord, SaveState } from "@/components/requirement-workspace/types";
import { apiPut } from "@/lib/api";
import { isMappingLocked, mappingStatusLabel, mappingStatusTone } from "@/lib/workspace-view-model.mjs";

export function SelectedFieldEditor({
  record,
  detailReady,
  onAdoptBusiness,
  onAdoptTechnical,
  onDirtyChange,
  onError,
  onNotice,
  onSaved
}: {
  record: FieldWorkspaceRecord;
  detailReady: boolean;
  onAdoptBusiness: () => void;
  onAdoptTechnical: () => void;
  onDirtyChange: (dirty: boolean) => void;
  onError: (message: string) => void;
  onNotice: (message: string) => void;
  onSaved: () => void;
}) {
  const initialBusinessFinal = record.business?.final_content || "";
  const initialTechnicalFinal = record.lineage?.final_content || "";
  const [businessFinal, setBusinessFinal] = useState(initialBusinessFinal);
  const [technicalFinal, setTechnicalFinal] = useState(initialTechnicalFinal);
  const [saveState, setSaveState] = useState<SaveState>("idle");
  const saveStateRef = useRef(saveState);
  saveStateRef.current = saveState;
  const businessLocked = isMappingLocked(record.business?.business_confirm_status);
  const technicalLocked = isMappingLocked(record.lineage?.tech_confirm_status);

  useEffect(() => {
    if (saveStateRef.current === "dirty" || saveStateRef.current === "saving") return;
    setBusinessFinal(initialBusinessFinal);
    setTechnicalFinal(initialTechnicalFinal);
  }, [initialBusinessFinal, initialTechnicalFinal]);

  useEffect(() => {
    const beforeUnload = (event: BeforeUnloadEvent) => {
      if (saveState !== "dirty") return;
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", beforeUnload);
    return () => window.removeEventListener("beforeunload", beforeUnload);
  }, [saveState]);

  function updateDirtyState(nextBusinessFinal: string, nextTechnicalFinal: string) {
    const dirty = nextBusinessFinal !== initialBusinessFinal || nextTechnicalFinal !== initialTechnicalFinal;
    setSaveState(dirty ? "dirty" : "idle");
    onDirtyChange(dirty);
  }

  async function save() {
    if (!detailReady) {
      onError("当前字段完整口径仍在加载，请稍后再保存。");
      return;
    }
    setSaveState("saving");
    onError("");
    try {
      const actions: Promise<unknown>[] = [];
      if (record.business && !businessLocked) {
        actions.push(apiPut(`/scenario-business-mappings/${record.business.id}`, { final_content: businessFinal }));
      }
      if (record.lineage && !technicalLocked) {
        actions.push(apiPut(`/scenario-technical-lineages/${record.lineage.id}`, { final_content: technicalFinal }));
      }
      if (!actions.length) {
        throw new Error("当前内容已进入确认或审核流程，不能在工作台直接修改。请进入字段场景审核任务处理。");
      }
      await Promise.all(actions);
      setSaveState("saved");
      onDirtyChange(false);
      onNotice("人工最终内容已保存。AI 草稿仍独立保留。");
      onSaved();
    } catch (cause) {
      setSaveState("error");
      onError(cause instanceof Error ? cause.message : "保存失败，当前输入仍保留在页面中");
    }
  }

  return (
    <section aria-label="当前字段编辑器" className="rounded-lg border border-line bg-slate-50/70 p-3">
      <div className="mb-3 flex items-center justify-between gap-3">
        <div><h3 className="text-xs font-semibold text-ink">AI 草稿与人工最终口径</h3><p className="mt-1 text-[10px] text-slate-500">编辑状态下沉到当前字段，不触发字段列表和文档表格逐字重渲染。</p></div>
        <SaveStateText state={saveState} />
      </div>
      <div className="grid gap-3 lg:grid-cols-2">
        <MappingEditor
          aiDraft={record.business?.ai_generated_content || ""}
          finalContent={businessFinal}
          label="业务口径"
          locked={businessLocked}
          onAdopt={onAdoptBusiness}
          onChange={(value) => {
            setBusinessFinal(value);
            updateDirtyState(value, technicalFinal);
          }}
          status={record.business?.business_confirm_status || "未维护"}
        />
        <MappingEditor
          aiDraft={record.lineage?.ai_generated_content || ""}
          finalContent={technicalFinal}
          label="技术溯源"
          locked={technicalLocked}
          onAdopt={onAdoptTechnical}
          onChange={(value) => {
            setTechnicalFinal(value);
            updateDirtyState(businessFinal, value);
          }}
          status={record.lineage?.tech_confirm_status || "未维护"}
        />
      </div>
      <div className="mt-3 flex justify-end">
        <button className="button-primary" disabled={saveState === "saving" || (businessLocked && technicalLocked) || (!record.business && !record.lineage)} onClick={() => void save()} type="button"><Save size={15} />保存人工最终内容</button>
      </div>
    </section>
  );
}

function MappingEditor({ label, status, aiDraft, finalContent, locked, onAdopt, onChange }: { label: string; status: string; aiDraft: string; finalContent: string; locked: boolean; onAdopt: () => void; onChange: (value: string) => void }) {
  return <div className="rounded-lg border border-line bg-white p-3"><div className="flex items-center gap-2"><strong className="text-xs text-ink">{label}</strong><StatusBadge tone={mappingStatusTone(status)} value={mappingStatusLabel(status)} />{locked ? <span className="ml-auto flex items-center gap-1 text-[10px] text-gold-700"><ShieldAlert size={13} />治理态保护</span> : null}</div><label className="mt-3 block text-[10px] font-semibold text-slate-500">AI 建议（只读）</label><textarea className="control mt-1 min-h-24 resize-y bg-pine-50/40 text-xs leading-5" readOnly value={aiDraft} placeholder="尚未生成 AI 草稿" /><button className="button-secondary mt-2 h-8 text-xs" disabled={!aiDraft || locked} onClick={onAdopt} type="button"><Check size={14} />采用 AI 草稿</button><label className="mt-3 block text-[10px] font-semibold text-slate-500">人工最终内容</label><textarea className="control mt-1 min-h-28 resize-y text-xs leading-5" disabled={locked} onChange={(event) => onChange(event.target.value)} value={finalContent} placeholder="输入经人工校核的最终内容" /></div>;
}

function StatusBadge({ tone, value }: { tone: string; value: string }) {
  const className = tone === "success" ? "badge-success" : tone === "danger" ? "badge-danger" : tone === "warning" ? "badge-warning" : tone === "info" ? "badge-info" : "badge-neutral";
  return <span className={`${className} whitespace-normal text-center text-[9px]`}>{value}</span>;
}

function SaveStateText({ state }: { state: SaveState }) {
  const copy = state === "saving" ? "保存中…" : state === "dirty" ? "有未保存修改" : state === "saved" ? "已保存" : state === "error" ? "保存失败，人工内容未丢失" : "当前内容与服务器一致";
  const tone = state === "error" ? "text-coral-700" : state === "dirty" ? "text-gold-700" : state === "saved" ? "text-pine-700" : "text-slate-500";
  return <span className={`flex items-center gap-1.5 text-xs ${tone}`}>{state === "saved" ? <Check size={14} /> : state === "error" ? <ShieldAlert size={14} /> : <Save size={14} />}{copy}</span>;
}

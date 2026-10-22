"use client";

import { Check, Loader2 } from "lucide-react";
import { useState } from "react";

import { apiPost } from "@/lib/api";
import { describeError, describeUserMessage } from "@/lib/user-message.mjs";

export type ResolvableGap = {
  id: string;
  field_id?: number | null;
  origin?: string;
  status?: string;
  message: string;
  resolution_basis?: { note?: string | null } | null;
};

/**
 * 分析发现的缺口（AI 候选带来的待确认条目）必须有人工解决依据才能关闭，
 * 关闭后生成新的内容版本；字段派生缺口只能通过补齐字段内容解决，不能在此盖章。
 * 人工问题（origin=manual）走 /questions 的受理-答复-结案流程，这里只给出指向。
 */
export function RequirementGapResolver({
  projectId,
  requirementId,
  contentVersion,
  gap,
  onChanged,
}: {
  projectId: number | null;
  requirementId: number;
  contentVersion?: number;
  gap: ResolvableGap;
  onChanged: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [basis, setBasis] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  if (gap.status === "resolved" || gap.status === "closed") {
    const note = (gap.resolution_basis?.note || "").trim();
    return (
      <p className="mt-1 text-[11px] text-slate-500">
        该缺口已关闭{note ? `，依据：${note}` : "，历史版本未记录文字依据。"}
      </p>
    );
  }
  if (gap.origin === "manual") {
    return <p className="mt-1 text-[11px] text-slate-500">人工问题需在「人工问题」中受理、答复并结案；仅受理不等于已解决。</p>;
  }
  if (/^\d+:/.test(gap.id)) {
    return <p className="mt-1 text-[11px] text-slate-500">该缺口来自字段内容缺项，请在「需求独立内容」中补齐对应字段后重新评估，不能用说明直接关闭。</p>;
  }

  const submit = async () => {
    if (!projectId || !contentVersion) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await apiPost(
        `/projects/${projectId}/requirements/${requirementId}/gaps/${encodeURIComponent(gap.id)}/resolve`,
        { expected_content_version: contentVersion, resolution_text: basis.trim() },
      );
      setNotice("已关闭并生成新的内容版本。");
      setBasis("");
      setOpen(false);
      onChanged();
    } catch (cause) {
      setError(describeError(cause, "未能关闭缺口，请核对版本与权限后重试。"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mt-1">
      {!open ? (
        <button className="text-[11px] text-pine-700 underline" onClick={() => setOpen(true)} type="button">
          关闭缺口（填写解决依据）
        </button>
      ) : (
        <div className="mt-1 space-y-1">
          <textarea
            aria-label="缺口解决依据"
            className="control min-h-16 text-xs"
            disabled={busy}
            onChange={(event) => setBasis(event.target.value)}
            placeholder="写明依据来源与结论，例如制度条款、人工确认记录编号"
            value={basis}
          />
          <div className="flex flex-wrap items-center gap-2">
            <button className="button-primary h-7 px-2 text-xs" disabled={busy || !basis.trim()} onClick={() => void submit()} type="button">
              {busy ? <Loader2 className="animate-spin" size={13} /> : <Check size={13} />}确认关闭
            </button>
            <button className="text-[11px] underline" disabled={busy} onClick={() => setOpen(false)} type="button">取消</button>
            {!contentVersion ? <span className="text-[11px] text-amber-700">请先建立需求独立内容。</span> : null}
          </div>
        </div>
      )}
      {notice ? <p className="mt-1 text-[11px] text-pine-700" role="status">{notice}</p> : null}
      {error ? <p className="mt-1 text-[11px] text-coral-700" role="alert">{describeUserMessage(error, error)}</p> : null}
    </div>
  );
}

"use client";

import { useState } from "react";

import { boundedDisclosureModel } from "@/lib/semantic-detail-contract.mjs";

export function EvidenceDisclosure({
  disclosureType,
  itemId,
  text,
  lines = 6,
  scope = "evidence",
  className = "text-slate-700"
}: {
  disclosureType:string;
  itemId:string|number;
  text?:string|null;
  lines?:3|6;
  scope?:string;
  className?:string;
}) {
  const [expanded, setExpanded] = useState(false);
  const model = boundedDisclosureModel({ scope, type:disclosureType, id:itemId, text:text || "", lines, expanded });
  if (!model.hasText) return null;
  const clamp = model.lines === 3 ? "line-clamp-3" : "line-clamp-6";
  return (
    <div className="min-w-0">
      <div aria-label={model.isLong ? "可展开完整文本" : undefined} id={model.panelId} role={model.isLong ? "region" : undefined}>
        <p className={`whitespace-pre-wrap break-words ${className} ${model.isLong && !model.ariaExpanded ? clamp : ""}`}>{model.visibleText}</p>
      </div>
      {model.isLong ? (
        <button
          aria-controls={model.panelId}
          aria-expanded={model.ariaExpanded}
          className="mt-2 min-h-11 rounded-lg text-sm text-pine-700 underline-offset-2 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-pine-500/25"
          id={model.controlId}
          onClick={() => setExpanded((value) => !value)}
          type="button"
        >
          {model.ariaExpanded ? "收起" : "展开全文"}
        </button>
      ) : null}
    </div>
  );
}

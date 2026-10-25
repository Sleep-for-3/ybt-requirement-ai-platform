// 冻结快照与当前内容的字段级差异。
//
// 为什么需要它：评审拿到上一份导出文件后，最常问的是"这版和上版差在哪"。
// 快照是不可变审计对象，当前内容随时会变，两者对比只能按字段口径逐项比，
// 不能靠"版本号 +1"或"文件 hash 不同"来搪塞。

export type SnapshotFieldLike = {
  field?: { field_code?: string | null; field_name?: string | null } | null;
  business?: { business_definition?: string | null; final_content?: string | null } | null;
  lineage?: { processing_logic?: string | null; final_content?: string | null } | null;
};

export type RequirementContentLike = { fields?: SnapshotFieldLike[] | null };

export type SnapshotFieldChange = {
  fieldCode: string;
  fieldName: string;
  sections: string[];
};

export type SnapshotDiff = {
  previousSnapshotId: number | null;
  identical: boolean;
  added: { fieldCode: string; fieldName: string }[];
  removed: { fieldCode: string; fieldName: string }[];
  changed: SnapshotFieldChange[];
  previousFieldCount: number;
  currentFieldCount: number;
  // 字段口径没变不代表整份内容没变（缺口、资料范围、脚本依据都可能变）。
  // 是否复用快照只能按 content_hash 判断，不能按"差异为空"判断。
  sameContentHash: boolean;
};

const SECTION_SOURCES: { label: string; read: (record: SnapshotFieldLike) => string }[] = [
  { label: "业务定义", read: (record) => text(record.business?.business_definition) },
  { label: "业务正文", read: (record) => text(record.business?.final_content) },
  { label: "技术加工", read: (record) => text(record.lineage?.processing_logic) },
  { label: "技术正文", read: (record) => text(record.lineage?.final_content) },
];

function text(value: unknown): string {
  // 空值、纯空白、undefined 一律视为"没有内容"，避免把"没填"当成"改成了空"。
  if (value === null || value === undefined) return "";
  return String(value).replace(/\s+/g, " ").trim();
}

function fieldCodeOf(record: SnapshotFieldLike): string {
  return text(record.field?.field_code);
}

function fieldNameOf(record: SnapshotFieldLike): string {
  return text(record.field?.field_name) || fieldCodeOf(record) || "未命名字段";
}

function indexByCode(content: RequirementContentLike | null | undefined): Map<string, SnapshotFieldLike> {
  const index = new Map<string, SnapshotFieldLike>();
  for (const record of content?.fields || []) {
    const code = fieldCodeOf(record);
    if (!code) continue;
    index.set(code, record);
  }
  return index;
}

export function diffRequirementContent(
  previous: RequirementContentLike | null | undefined,
  current: RequirementContentLike | null | undefined,
  previousSnapshotId: number | null = null,
  sameContentHash = false,
): SnapshotDiff {
  const beforeIndexed = indexByCode(previous);
  const afterIndexed = indexByCode(current);
  const added: { fieldCode: string; fieldName: string }[] = [];
  const removed: { fieldCode: string; fieldName: string }[] = [];
  const changed: SnapshotFieldChange[] = [];

  for (const [code, record] of Array.from(afterIndexed)) {
    if (!beforeIndexed.has(code)) added.push({ fieldCode: code, fieldName: fieldNameOf(record) });
  }
  for (const [code, record] of Array.from(beforeIndexed)) {
    const next = afterIndexed.get(code);
    if (!next) {
      removed.push({ fieldCode: code, fieldName: fieldNameOf(record) });
      continue;
    }
    const sections = SECTION_SOURCES.filter((source) => source.read(record) !== source.read(next)).map((source) => source.label);
    if (sections.length > 0) changed.push({ fieldCode: code, fieldName: fieldNameOf(next), sections });
  }

  return {
    previousSnapshotId,
    identical: added.length === 0 && removed.length === 0 && changed.length === 0,
    added,
    removed,
    changed,
    previousFieldCount: beforeIndexed.size,
    currentFieldCount: afterIndexed.size,
    sameContentHash,
  };
}

export type SnapshotSide = {
  id: number;
  content_hash?: string | null;
  content: RequirementContentLike | null;
};

/**
 * 两份历史快照之间的字段级差异。
 *
 * sameContentHash 只由两份快照的 content_hash 决定：口径没变不等于内容没变
 * （缺口、资料范围、脚本依据都会改变 hash），所以不能拿"差异为空"当"完全一致"。
 */
export function diffSnapshotPair(base: SnapshotSide, target: SnapshotSide): SnapshotDiff {
  const baseHash = (base.content_hash || "").trim();
  const targetHash = (target.content_hash || "").trim();
  const sameContentHash = baseHash !== "" && baseHash === targetHash;
  return diffRequirementContent(base.content, target.content, base.id, sameContentHash);
}

/** 快照对比结论的三态文案：hash 相同 / 口径相同但 hash 不同 / 口径有变化。 */
export function snapshotPairSummary(diff: SnapshotDiff, baseId: number, targetId: number): string {
  const base = `快照 #${baseId}`;
  const target = `快照 #${targetId}`;
  const count = `${diff.currentFieldCount} 个字段`;
  if (diff.sameContentHash) {
    return `${base} 与 ${target} 内容完全一致（${count}，内容 hash 相同）——不存在需要复核的口径变化。`;
  }
  if (diff.identical) {
    return `${base} 与 ${target} 的字段口径相同（${count}），但内容 hash 不同：缺口、资料范围或脚本依据发生了变化，请按需求说明复核。`;
  }
  return `相对 ${base}，${target} 字段口径变化 ${diff.changed.length} 个 · 新增 ${diff.added.length} 个 · 删除 ${diff.removed.length} 个（${diff.previousFieldCount} → ${diff.currentFieldCount} 个字段）。`;
}

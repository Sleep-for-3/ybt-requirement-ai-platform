export function WorkspaceHeader({ title, meta, actions }: { title: string; meta?: string; actions?: React.ReactNode }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line bg-white px-4 py-4 lg:px-6">
      <div>
        <h1 className="text-xl font-semibold text-ink">{title}</h1>
        {meta ? <p className="mt-1 text-sm text-slate-500">{meta}</p> : null}
      </div>
      {actions}
    </div>
  );
}

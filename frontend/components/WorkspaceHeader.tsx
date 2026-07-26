export function WorkspaceHeader({ title, meta, actions }: { title: string; meta?: string; actions?: React.ReactNode }) {
  return (
    <div className="border-b border-line bg-white">
      <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-5 lg:px-6">
        <div className="min-w-0">
          <h1 className="text-xl font-semibold tracking-tight text-ink">{title}</h1>
          {meta ? <p className="mt-1 text-sm text-slate-500">{meta}</p> : null}
        </div>
        {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
      </div>
    </div>
  );
}

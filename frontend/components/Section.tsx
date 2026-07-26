export function Section({
  title,
  children,
  right
}: {
  title: string;
  children: React.ReactNode;
  right?: React.ReactNode;
}) {
  return (
    <section className="panel">
      <div className="panel-header flex items-center justify-between gap-3">
        <h2 className="text-[15px] font-semibold text-ink">{title}</h2>
        {right}
      </div>
      <div className="panel-body">{children}</div>
    </section>
  );
}

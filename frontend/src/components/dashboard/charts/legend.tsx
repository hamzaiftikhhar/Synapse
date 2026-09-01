export function AnalyticsLegend({
  items,
}: {
  items: { label: string; color: string }[];
}) {
  return (
    <ul className="flex flex-wrap items-start gap-x-3 gap-y-1.5 sm:items-center sm:justify-end sm:gap-x-4">
      {items.map((item) => (
        <li key={item.label} className="flex items-center gap-1.5 text-[11px] text-muted-foreground sm:text-[12px]">
          <span className="size-2 shrink-0 rounded-full" style={{ background: item.color }} />
          {item.label}
        </li>
      ))}
    </ul>
  );
}

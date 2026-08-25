export type ChartPt = { x: number; y: number };

/** Catmull–Rom spline → cubic Bézier. Smooth ECG-style curves without a chart lib. */
export function splinePath(points: ChartPt[]): string {
  if (points.length === 0) return "";
  if (points.length === 1) return `M ${points[0].x} ${points[0].y}`;
  let d = `M ${points[0].x} ${points[0].y}`;
  for (let i = 0; i < points.length - 1; i++) {
    const p0 = points[i - 1] ?? points[i];
    const p1 = points[i];
    const p2 = points[i + 1];
    const p3 = points[i + 2] ?? p2;
    const c1x = p1.x + (p2.x - p0.x) / 6;
    const c1y = p1.y + (p2.y - p0.y) / 6;
    const c2x = p2.x - (p3.x - p1.x) / 6;
    const c2y = p2.y - (p3.y - p1.y) / 6;
    d += ` C ${c1x} ${c1y}, ${c2x} ${c2y}, ${p2.x} ${p2.y}`;
  }
  return d;
}

export function areaPath(line: string, points: ChartPt[], baselineY: number): string {
  if (!points.length || !line) return "";
  const first = points[0];
  const last = points[points.length - 1];
  return `${line} L ${last.x} ${baselineY} L ${first.x} ${baselineY} Z`;
}

export function roundTopBar(
  x: number,
  y: number,
  width: number,
  height: number,
  radius = 6
): string {
  const h = Math.max(height, 0);
  if (h === 0 || width <= 0) return "";
  const r = Math.min(radius, width / 2, h);
  return [
    `M ${x} ${y + h}`,
    `L ${x} ${y + r}`,
    `Q ${x} ${y} ${x + r} ${y}`,
    `L ${x + width - r} ${y}`,
    `Q ${x + width} ${y} ${x + width} ${y + r}`,
    `L ${x + width} ${y + h}`,
    "Z",
  ].join(" ");
}

/** First card is ink when there are 4; middle card is ink when there are 3. */
export function inkSlot(count: number): number {
  return count === 3 ? 1 : 0;
}

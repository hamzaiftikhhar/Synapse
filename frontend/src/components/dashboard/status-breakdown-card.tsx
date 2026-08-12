"use client";

import { Bar, BarChart, Cell, ResponsiveContainer, XAxis, YAxis } from "recharts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export type StatusCount = {
  status: string;
  label: string;
  count: number;
  color: string;
};

export function StatusBreakdownCard({
  title,
  subtitle,
  counts,
}: {
  title: string;
  subtitle?: string;
  counts: StatusCount[];
}) {
  const total = counts.reduce((sum, c) => sum + c.count, 0);
  const rows = counts.filter((c) => c.count > 0);

  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        {subtitle ? (
          <p className="mt-0.5 text-xs text-muted-foreground">{subtitle}</p>
        ) : null}
      </CardHeader>
      <CardContent>
        {total === 0 ? (
          <div className="flex h-40 flex-col items-center justify-center gap-1 text-center">
            <p className="text-sm font-medium text-navy">No appointments yet</p>
            <p className="text-xs text-muted-foreground">
              Status breakdown appears once appointments come in.
            </p>
          </div>
        ) : (
          <div className="h-40 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart
                data={rows}
                layout="vertical"
                margin={{ top: 0, right: 16, left: 0, bottom: 0 }}
                barCategoryGap={10}
              >
                <XAxis type="number" hide />
                <YAxis
                  dataKey="label"
                  type="category"
                  width={84}
                  axisLine={false}
                  tickLine={false}
                  tick={{ fontSize: 12, fill: "var(--foreground)" }}
                />
                <Bar dataKey="count" radius={[0, 8, 8, 0]} maxBarSize={18}>
                  {rows.map((row) => (
                    <Cell key={row.status} fill={row.color} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

import Link from "next/link";
import { ArrowUpRight, type LucideIcon } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";

const TONE_CHIP: Record<string, string> = {
  primary: "bg-primary/12 text-primary",
  success: "bg-success/12 text-success",
  warning: "bg-warning/12 text-warning",
  info: "bg-info/12 text-info",
  destructive: "bg-destructive/12 text-destructive",
};

export function StatCard({
  label,
  value,
  href,
  icon: Icon,
  tone = "primary",
}: {
  label: string;
  value: string | number;
  href: string;
  icon: LucideIcon;
  tone?: "primary" | "success" | "warning" | "info" | "destructive";
}) {
  return (
    <Card className="transition-shadow hover:shadow-md hover:shadow-black/[0.03]">
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
        <CardTitle className="text-sm font-medium text-muted-foreground">
          {label}
        </CardTitle>
        <div
          className={cn(
            "flex size-8 shrink-0 items-center justify-center rounded-xl",
            TONE_CHIP[tone]
          )}
        >
          <Icon className="size-4" />
        </div>
      </CardHeader>
      <CardContent>
        <div className="text-3xl font-semibold tracking-tight text-navy tabular-nums">
          {value}
        </div>
        <Link
          href={href}
          className="group/link mt-2.5 inline-flex items-center gap-1 text-xs font-medium text-primary"
        >
          View all
          <ArrowUpRight className="size-3 transition-transform group-hover/link:translate-x-0.5 group-hover/link:-translate-y-0.5" />
        </Link>
      </CardContent>
    </Card>
  );
}

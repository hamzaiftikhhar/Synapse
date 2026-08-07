import Link from "next/link";
import { ArrowUpRight, type LucideIcon } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export function StatCard({
  label,
  value,
  href,
  icon: Icon,
}: {
  label: string;
  value: string | number;
  href: string;
  icon: LucideIcon;
}) {
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
        <CardTitle className="text-sm font-medium text-muted-foreground">
          {label}
        </CardTitle>
        <div className="flex size-8 items-center justify-center rounded-xl bg-accent text-primary">
          <Icon className="size-4" />
        </div>
      </CardHeader>
      <CardContent>
        <div className="text-2xl font-semibold tracking-tight text-navy">
          {value}
        </div>
        <Link
          href={href}
          className="mt-2 inline-flex items-center gap-1 text-xs text-primary hover:underline"
        >
          View all <ArrowUpRight className="size-3" />
        </Link>
      </CardContent>
    </Card>
  );
}

"use client";

import { PageHeader } from "@/components/dashboard/page-header";

export default function PlatformPlaceholder({
  title,
  description,
}: {
  title: string;
  description: string;
}) {
  return (
    <div>
      <PageHeader title={title} description={description} />
      <div className="rounded-[6px] border border-dashed border-border bg-white px-4 py-10 text-center">
        <p className="text-sm text-muted-foreground">
          Platform module scaffold — APIs and UI will land here next.
        </p>
      </div>
    </div>
  );
}

import { PageHeader } from "@/components/dashboard/page-header";
import { TodoBackendNotice } from "@/components/dashboard/shell";

export const metadata = { title: "Settings" };

export default function Page() {
  return (
    <div>
      <PageHeader title="Settings" description="Workspace preferences and security." />
      <TodoBackendNotice feature="Settings" />
    </div>
  );
}

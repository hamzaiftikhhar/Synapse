import { PageHeader } from "@/components/dashboard/page-header";
import { TodoBackendNotice } from "@/components/dashboard/shell";

export const metadata = { title: "Analytics" };

export default function Page() {
  return (
    <div>
      <PageHeader title="Analytics" description="Conversation volume, booking conversion, and document health." />
      <TodoBackendNotice feature="Analytics" />
    </div>
  );
}

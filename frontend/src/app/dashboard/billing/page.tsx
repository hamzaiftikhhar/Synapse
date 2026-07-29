import { PageHeader } from "@/components/dashboard/page-header";
import { TodoBackendNotice } from "@/components/dashboard/shell";

export const metadata = { title: "Billing" };

export default function Page() {
  return (
    <div>
      <PageHeader title="Billing" description="Subscription and invoice management for Synapse SaaS." />
      <TodoBackendNotice feature="Billing" />
    </div>
  );
}

import { PageHeader } from "@/components/dashboard/page-header";
import { TodoBackendNotice } from "@/components/dashboard/shell";

export const metadata = { title: "Clinic" };

export default function Page() {
  return (
    <div>
      <PageHeader title="Clinic" description="Clinic profile, address, and branding settings." />
      <TodoBackendNotice feature="Clinic" />
    </div>
  );
}

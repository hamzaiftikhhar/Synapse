import { PageHeader } from "@/components/dashboard/page-header";
import { TodoBackendNotice } from "@/components/dashboard/shell";

export const metadata = { title: "Business Hours" };

export default function Page() {
  return (
    <div>
      <PageHeader title="Business Hours" description="Weekly open/close schedule for the clinic." />
      <TodoBackendNotice feature="Business Hours" />
    </div>
  );
}

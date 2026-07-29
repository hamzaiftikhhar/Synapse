import { PageHeader } from "@/components/dashboard/page-header";
import { TodoBackendNotice } from "@/components/dashboard/shell";

export const metadata = { title: "Insurance" };

export default function Page() {
  return (
    <div>
      <PageHeader title="Insurance" description="Accepted insurance plans for booking and chatbot answers." />
      <TodoBackendNotice feature="Insurance" />
    </div>
  );
}

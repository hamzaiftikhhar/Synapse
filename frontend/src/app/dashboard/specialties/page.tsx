import { PageHeader } from "@/components/dashboard/page-header";
import { TodoBackendNotice } from "@/components/dashboard/shell";

export const metadata = { title: "Specialties" };

export default function Page() {
  return (
    <div>
      <PageHeader title="Specialties" description="Specialty taxonomy for doctors." />
      <TodoBackendNotice feature="Specialties" />
    </div>
  );
}

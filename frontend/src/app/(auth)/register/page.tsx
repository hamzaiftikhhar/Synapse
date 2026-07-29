import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { APP_NAME } from "@/constants";

export const metadata = { title: "Register" };

export default function RegisterPage() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-muted/30 px-6">
      <div className="w-full max-w-[420px] rounded-[6px] border border-border bg-white p-8 shadow-sm">
        <Link href="/" className="text-lg font-semibold text-navy">
          {APP_NAME}
        </Link>
        <h1 className="mt-6 text-2xl font-semibold tracking-tight">
          Request clinic access
        </h1>
        <p className="mt-2 text-sm text-muted-foreground">
          {/* TODO: Backend endpoint required — POST /auth/register */}
          Self-serve registration is not available yet. Leave your details and
          our team will provision your clinic tenant.
        </p>
        <form className="mt-6 space-y-4">
          <div className="space-y-2">
            <Label htmlFor="clinic">Clinic name</Label>
            <Input id="clinic" placeholder="Acme Cardiology" disabled />
          </div>
          <div className="space-y-2">
            <Label htmlFor="email">Work email</Label>
            <Input id="email" type="email" placeholder="admin@clinic.com" disabled />
          </div>
          <Button className="w-full rounded-[6px]" disabled>
            Coming soon
          </Button>
        </form>
        <p className="mt-6 text-center text-sm text-muted-foreground">
          Already have an account?{" "}
          <Link href="/login" className="text-primary hover:underline">
            Sign in
          </Link>
        </p>
      </div>
    </div>
  );
}

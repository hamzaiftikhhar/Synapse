import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { APP_NAME } from "@/constants";

export const metadata = { title: "Reset password" };

export default function ResetPasswordPage() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-muted/30 px-6">
      <div className="w-full max-w-[400px] rounded-[6px] border border-border bg-white p-8 shadow-sm">
        <Link href="/" className="text-lg font-semibold text-navy">
          {APP_NAME}
        </Link>
        <h1 className="mt-6 text-2xl font-semibold tracking-tight">
          Choose a new password
        </h1>
        <p className="mt-2 text-sm text-muted-foreground">
          {/* TODO: Backend endpoint required — POST /auth/reset-password */}
          Token-based password reset is not available yet.
        </p>
        <form className="mt-6 space-y-4">
          <div className="space-y-2">
            <Label htmlFor="password">New password</Label>
            <Input id="password" type="password" disabled />
          </div>
          <div className="space-y-2">
            <Label htmlFor="confirm">Confirm password</Label>
            <Input id="confirm" type="password" disabled />
          </div>
          <Button className="w-full rounded-[6px]" disabled>
            Coming soon
          </Button>
        </form>
      </div>
    </div>
  );
}

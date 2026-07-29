import Link from "next/link";
import { APP_NAME } from "@/constants";

export const metadata = { title: "Verify email" };

export default function VerifyEmailPage() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-muted/30 px-6">
      <div className="w-full max-w-[400px] rounded-[6px] border border-border bg-white p-8 text-center shadow-sm">
        <Link href="/" className="text-lg font-semibold text-navy">
          {APP_NAME}
        </Link>
        <h1 className="mt-6 text-2xl font-semibold tracking-tight">
          Verify your email
        </h1>
        <p className="mt-2 text-sm text-muted-foreground">
          {/* TODO: Backend endpoint required — POST /auth/verify-email */}
          Email verification is not wired to the API yet.
        </p>
        <Link
          href="/login"
          className="mt-6 inline-flex h-8 items-center rounded-[6px] border border-border px-3 text-sm hover:bg-muted"
        >
          Back to sign in
        </Link>
      </div>
    </div>
  );
}

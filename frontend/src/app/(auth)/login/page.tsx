import { Suspense } from "react";
import { LoginForm } from "@/features/auth/login-form";

export const metadata = { title: "Sign in" };

export default function LoginPage() {
  return (
    <div className="grid min-h-screen lg:grid-cols-2">
      <div className="relative hidden overflow-hidden section-navy lg:block">
        <div className="glow-navy absolute inset-0" />
        <div className="relative flex h-full flex-col justify-between p-12">
          <p className="text-sm font-medium tracking-wide text-lavender">
            SYNAPSE
          </p>
          <div>
            <h2 className="max-w-md text-3xl font-semibold leading-tight tracking-tight text-white">
              The AI platform that helps{" "}
              <span className="text-gradient">clinics grow</span> without adding
              front-desk chaos.
            </h2>
            <p className="mt-4 max-w-sm text-sm leading-relaxed text-white/60">
              Book appointments, answer insurance questions, and surface clinic
              knowledge — all from an embeddable patient chatbot.
            </p>
          </div>
          <p className="text-xs text-white/40">
            HIPAA-ready architecture · Multi-tenant · Staff JWT portal
          </p>
        </div>
      </div>
      <div className="flex items-center justify-center bg-white px-6 py-16">
        <Suspense fallback={<div className="text-sm text-muted-foreground">Loading…</div>}>
          <LoginForm />
        </Suspense>
      </div>
    </div>
  );
}

"use client";

import { useState } from "react";
import { useSearchParams } from "next/navigation";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";

export default function ContactPage() {
  const [pending, setPending] = useState(false);
  const isEnterprise = useSearchParams().get("interest") === "enterprise";

  return (
    <div className="mx-auto max-w-xl px-4 py-20 sm:px-6">
      <h1 className="text-4xl font-semibold tracking-tight text-navy">
        {isEnterprise ? "Talk to us about Enterprise" : "Book a demo"}
      </h1>
      <p className="mt-3 text-muted-foreground">
        {isEnterprise
          ? "Tell us about your clinics and requirements — our team will follow up to scope a custom plan."
          : "Tell us about your clinic."}{" "}
        {/* TODO: Backend endpoint required — POST /contact */}
        This form is UI-only until a contact API exists.
      </p>
      <form
        className="mt-8 space-y-4"
        onSubmit={(e) => {
          e.preventDefault();
          setPending(true);
          setTimeout(() => {
            setPending(false);
            toast.message("Thanks — we captured this locally.", {
              description: "Wire a contact endpoint to deliver submissions.",
            });
          }, 400);
        }}
      >
        <div className="space-y-1.5">
          <Label>Name</Label>
          <Input required className="rounded-[6px]" />
        </div>
        <div className="space-y-1.5">
          <Label>Work email</Label>
          <Input type="email" required className="rounded-[6px]" />
        </div>
        <div className="space-y-1.5">
          <Label>Clinic name</Label>
          <Input required className="rounded-[6px]" />
        </div>
        <div className="space-y-1.5">
          <Label>Message</Label>
          <Textarea rows={4} className="rounded-[6px]" />
        </div>
        <Button type="submit" className="rounded-[6px]" disabled={pending}>
          {pending ? "Sending…" : "Request demo"}
        </Button>
      </form>
    </div>
  );
}

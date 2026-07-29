"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { ChatActionHandler, ChatMessage } from "@/types/chat";

export function AppointmentFormMessage({
  message,
  onAction,
}: {
  message: ChatMessage;
  onAction?: ChatActionHandler;
}) {
  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [phone, setPhone] = useState("");
  const [notes, setNotes] = useState("");

  return (
    <div className="space-y-3 rounded-[6px] border border-border bg-white p-3">
      <p className="text-xs font-medium text-navy">
        {(message.payload?.title as string) || "Appointment details"}
      </p>
      <div className="grid grid-cols-2 gap-2">
        <div className="space-y-1">
          <Label className="text-xs">First name</Label>
          <Input value={firstName} onChange={(e) => setFirstName(e.target.value)} className="h-8 rounded-[6px]" />
        </div>
        <div className="space-y-1">
          <Label className="text-xs">Last name</Label>
          <Input value={lastName} onChange={(e) => setLastName(e.target.value)} className="h-8 rounded-[6px]" />
        </div>
      </div>
      <div className="space-y-1">
        <Label className="text-xs">Phone</Label>
        <Input value={phone} onChange={(e) => setPhone(e.target.value)} className="h-8 rounded-[6px]" />
      </div>
      <div className="space-y-1">
        <Label className="text-xs">Notes</Label>
        <Input value={notes} onChange={(e) => setNotes(e.target.value)} className="h-8 rounded-[6px]" />
      </div>
      <Button
        size="sm"
        className="w-full rounded-[6px]"
        onClick={() =>
          onAction?.("submit_appointment", { firstName, lastName, phone, notes })
        }
      >
        Continue
      </Button>
    </div>
  );
}

"use client";

import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { BookingWizard } from "@/features/booking/booking-wizard";
import type { BookingStepPayload } from "@/types/api";

/** Legacy bottom-sheet wrapper — prefer BookingInlineCard in chat. */
export type BookingSheetProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  clinicSlug: string;
  initialMessage?: string;
  specialtyId?: string | null;
  specialtyName?: string | null;
  doctorId?: string | null;
  doctorName?: string | null;
  onConfirmed?: (payload: BookingStepPayload) => void;
};

export function BookingSheet({
  open,
  onOpenChange,
  clinicSlug,
  initialMessage = "",
  specialtyId = null,
  specialtyName = null,
  doctorId = null,
  doctorName = null,
  onConfirmed,
}: BookingSheetProps) {
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        side="bottom"
        className="mx-auto flex h-[min(92dvh,720px)] w-full max-w-lg flex-col gap-0 overflow-hidden rounded-t-[16px] p-0 data-[side=bottom]:max-h-[min(92dvh,720px)] sm:data-[side=bottom]:max-w-lg"
      >
        <SheetHeader className="sr-only">
          <SheetTitle>Book Appointment</SheetTitle>
        </SheetHeader>
        {open ? (
          <BookingWizard
            clinicSlug={clinicSlug}
            initialMessage={initialMessage}
            specialtyId={specialtyId}
            specialtyName={specialtyName}
            doctorId={doctorId}
            doctorName={doctorName}
            active={open}
            onConfirmed={(p) => {
              onConfirmed?.(p);
            }}
            onDismiss={() => onOpenChange(false)}
            className="flex h-full min-h-0 flex-1 flex-col"
          />
        ) : null}
      </SheetContent>
    </Sheet>
  );
}

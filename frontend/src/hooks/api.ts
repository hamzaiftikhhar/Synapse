"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  appointmentsService,
  type AppointmentListParams,
  authService,
  bookingService,
  chatService,
  doctorsService,
  documentsService,
  patientsService,
  servicesService,
  widgetService,
} from "@/services";
import type {
  AppointmentInput,
  AppointmentUpdateInput,
  ChatMessageInput,
  DoctorInput,
  DoctorUpdateInput,
  ListParams,
  MarketingChatInput,
  PatientInput,
  PatientUpdateInput,
  ServiceInput,
  ServiceUpdateInput,
  StaffLoginInput,
  WidgetGuestChatInput,
} from "@/types/api";

export const queryKeys = {
  me: ["me"] as const,
  patients: (p?: ListParams) => ["patients", p] as const,
  patient: (id: string) => ["patients", id] as const,
  doctors: (p?: ListParams) => ["doctors", p] as const,
  doctor: (id: string) => ["doctors", id] as const,
  services: (p?: ListParams) => ["services", p] as const,
  service: (id: string) => ["services", id] as const,
  appointments: (p?: AppointmentListParams) => ["appointments", p] as const,
  appointment: (id: string) => ["appointments", id] as const,
  documents: ["documents"] as const,
  document: (id: string) => ["documents", id] as const,
  chunks: (id: string) => ["documents", id, "chunks"] as const,
};

export function useMe(enabled = true) {
  return useQuery({
    queryKey: queryKeys.me,
    queryFn: () => authService.me(),
    enabled,
    retry: false,
  });
}

export function useLogin() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      input,
      remember,
    }: {
      input: StaffLoginInput;
      remember?: boolean;
    }) => authService.login(input, remember ?? true),
    onSuccess: (data) => {
      qc.setQueryData(queryKeys.me, {
        user: data.user,
        clinic: data.clinic,
      });
    },
  });
}

export function usePatients(params?: ListParams) {
  return useQuery({
    queryKey: queryKeys.patients(params),
    queryFn: () => patientsService.list(params),
  });
}

export function useCreatePatient() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: PatientInput) => patientsService.create(input),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["patients"] }),
  });
}

export function useUpdatePatient() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, input }: { id: string; input: PatientUpdateInput }) =>
      patientsService.update(id, input),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["patients"] }),
  });
}

export function useDeletePatient() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => patientsService.remove(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["patients"] }),
  });
}

export function useDoctors(params?: ListParams) {
  return useQuery({
    queryKey: queryKeys.doctors(params),
    queryFn: () => doctorsService.list(params),
  });
}

export function useCreateDoctor() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: DoctorInput) => doctorsService.create(input),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["doctors"] }),
  });
}

export function useUpdateDoctor() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, input }: { id: string; input: DoctorUpdateInput }) =>
      doctorsService.update(id, input),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["doctors"] }),
  });
}

export function useDeleteDoctor() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => doctorsService.remove(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["doctors"] }),
  });
}

export function useServices(params?: ListParams) {
  return useQuery({
    queryKey: queryKeys.services(params),
    queryFn: () => servicesService.list(params),
  });
}

export function useCreateService() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: ServiceInput) => servicesService.create(input),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["services"] }),
  });
}

export function useUpdateService() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, input }: { id: string; input: ServiceUpdateInput }) =>
      servicesService.update(id, input),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["services"] }),
  });
}

export function useDeleteService() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => servicesService.remove(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["services"] }),
  });
}

export function useAppointments(params?: AppointmentListParams) {
  return useQuery({
    queryKey: queryKeys.appointments(params),
    queryFn: () => appointmentsService.list(params),
  });
}

export function useCreateAppointment() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: AppointmentInput) => appointmentsService.create(input),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["appointments"] }),
  });
}

export function useUpdateAppointment() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      id,
      input,
    }: {
      id: string;
      input: AppointmentUpdateInput;
    }) => appointmentsService.update(id, input),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["appointments"] }),
  });
}

export function useCancelAppointment() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => appointmentsService.remove(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["appointments"] }),
  });
}

export function useDocuments() {
  return useQuery({
    queryKey: queryKeys.documents,
    queryFn: () => documentsService.list(),
  });
}

export function useUploadDocument() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ file, title }: { file: File; title?: string }) =>
      documentsService.upload(file, title),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.documents }),
  });
}

export function useReindexDocument() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => documentsService.reindex(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.documents }),
  });
}

export function useStaffChat() {
  return useMutation({
    mutationFn: (input: ChatMessageInput) => chatService.sendStaffMessage(input),
  });
}

export function usePatientChat() {
  return useMutation({
    mutationFn: (input: ChatMessageInput) =>
      chatService.sendPatientMessage(input),
  });
}

export function useGuestChat() {
  return useMutation({
    mutationFn: (input: WidgetGuestChatInput) =>
      widgetService.sendGuestMessage(input),
  });
}

export function useMarketingChat() {
  return useMutation({
    mutationFn: (input: MarketingChatInput) =>
      widgetService.sendMarketingMessage(input),
  });
}

/* ─── Booking wizard ───────────────────────────────────────── */

export function useBookingStart() {
  return useMutation({
    mutationFn: (input: import("@/types/api").BookingStartInput) =>
      bookingService.start(input),
  });
}

export function useBookingStep() {
  return useMutation({
    mutationFn: (input: import("@/types/api").BookingStepInput) =>
      bookingService.step(input),
  });
}

export function useBookingConfirm() {
  return useMutation({
    mutationFn: (input: import("@/types/api").BookingConfirmInput) =>
      bookingService.confirm(input),
  });
}

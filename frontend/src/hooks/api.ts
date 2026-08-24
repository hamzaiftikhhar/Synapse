"use client";

import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  analyticsService,
  appointmentsService,
  type AppointmentListParams,
  authService,
  billingService,
  bookingService,
  chatService,
  clinicsService,
  doctorsService,
  documentsService,
  importerService,
  insuranceService,
  patientsService,
  platformService,
  servicesService,
  specialtiesService,
  widgetService,
} from "@/services";
import type {
  AppointmentInput,
  AppointmentUpdateInput,
  BusinessHourInput,
  CancelSubscriptionInput,
  ChangePlanInput,
  ChatMessageInput,
  CheckoutInput,
  ClinicProfileUpdateInput,
  DocumentUpdateInput,
  DoctorInput,
  DoctorScheduleInput,
  DoctorUpdateInput,
  ImportJob,
  ImportMappingUpdateInput,
  ImportRecordType,
  ImportRecordUpdateInput,
  InsurancePlanInput,
  InsurancePlanUpdateInput,
  KnowledgeDocument,
  ListParams,
  MarketingChatInput,
  PatientInput,
  PatientUpdateInput,
  ServiceInput,
  ServiceUpdateInput,
  SpecialtyInput,
  SpecialtyUpdateInput,
  StaffLoginInput,
  WidgetGuestChatInput,
  WidgetSettingsUpdateInput,
} from "@/types/api";

function importJobIsActive(job: ImportJob | undefined) {
  return job?.status === "uploaded" || job?.status === "parsing";
}

function documentIsActive(doc: KnowledgeDocument) {
  return doc.status === "pending" || doc.status === "processing";
}

export const queryKeys = {
  me: ["me"] as const,
  conversations: (p?: import("@/types/api").ConversationListParams) =>
    ["conversations", p] as const,
  conversationMessages: (sessionId: string, before?: number) =>
    ["conversations", sessionId, "messages", before] as const,
  patients: (p?: ListParams) => ["patients", p] as const,
  patient: (id: string) => ["patients", id] as const,
  doctors: (p?: ListParams) => ["doctors", p] as const,
  doctor: (id: string) => ["doctors", id] as const,
  doctorSchedule: (id: string) => ["doctors", id, "schedule"] as const,
  services: (p?: ListParams) => ["services", p] as const,
  service: (id: string) => ["services", id] as const,
  specialties: (p?: ListParams) => ["specialties", p] as const,
  insurancePlans: (p?: ListParams) => ["insurance", p] as const,
  appointments: (p?: AppointmentListParams) => ["appointments", p] as const,
  appointment: (id: string) => ["appointments", id] as const,
  documents: ["documents"] as const,
  document: (id: string) => ["documents", id] as const,
  chunks: (id: string) => ["documents", id, "chunks"] as const,
  clinicProfile: ["clinic-profile"] as const,
  businessHours: ["business-hours"] as const,
  widgetSettings: ["widget-settings"] as const,
  onboardingStatus: ["onboarding-status"] as const,
  billingPlans: ["billing-plans"] as const,
  billingSubscription: ["billing-subscription"] as const,
  importJobs: (recordType?: ImportRecordType) => ["import-jobs", recordType] as const,
  importJob: (id: string) => ["import-jobs", id] as const,
  importJobRecords: (id: string, status?: string) =>
    ["import-jobs", id, "records", status] as const,
  clinicAnalytics: (days: number) => ["analytics", "clinic", days] as const,
  platformAiUsage: (days: number) => ["analytics", "platform", days] as const,
  platformOverview: ["platform", "overview"] as const,
  platformUsers: (p?: { search?: string; role?: string }) => ["platform", "users", p] as const,
  platformSubscriptions: (p?: { status?: string; search?: string }) =>
    ["platform", "subscriptions", p] as const,
  platformPlans: ["platform", "plans"] as const,
  platformDocuments: (p?: { status?: string; search?: string }) =>
    ["platform", "documents", p] as const,
  platformMonitoring: (days: number) => ["platform", "monitoring", days] as const,
  platformAudit: (p?: { action?: string; search?: string }) => ["platform", "audit", p] as const,
  platformSettings: ["platform", "settings"] as const,
  platformClinics: (search?: string) => ["platform", "clinics", search] as const,
  platformApplications: (status?: string) => ["platform", "applications", status] as const,
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
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["doctors"] });
      qc.invalidateQueries({ queryKey: queryKeys.onboardingStatus });
    },
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
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["doctors"] });
      qc.invalidateQueries({ queryKey: queryKeys.onboardingStatus });
    },
  });
}

export function useDoctorSchedule(doctorId: string | null) {
  return useQuery({
    queryKey: queryKeys.doctorSchedule(doctorId ?? ""),
    queryFn: () => doctorsService.getSchedule(doctorId!),
    enabled: Boolean(doctorId),
  });
}

export function useUpdateDoctorSchedule() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, input }: { id: string; input: DoctorScheduleInput[] }) =>
      doctorsService.updateSchedule(id, input),
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: queryKeys.doctorSchedule(vars.id) });
      qc.invalidateQueries({ queryKey: queryKeys.onboardingStatus });
    },
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
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["services"] });
      qc.invalidateQueries({ queryKey: queryKeys.onboardingStatus });
    },
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
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["services"] });
      qc.invalidateQueries({ queryKey: queryKeys.onboardingStatus });
    },
  });
}

/* ─── Specialties ──────────────────────────────────────────── */

export function useSpecialties(params?: ListParams) {
  return useQuery({
    queryKey: queryKeys.specialties(params),
    queryFn: () => specialtiesService.list(params),
  });
}

export function useCreateSpecialty() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: SpecialtyInput) => specialtiesService.create(input),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["specialties"] }),
  });
}

export function useUpdateSpecialty() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, input }: { id: string; input: SpecialtyUpdateInput }) =>
      specialtiesService.update(id, input),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["specialties"] }),
  });
}

export function useDeleteSpecialty() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => specialtiesService.remove(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["specialties"] }),
  });
}

/* ─── Insurance ────────────────────────────────────────────── */

export function useInsurancePlans(params?: ListParams) {
  return useQuery({
    queryKey: queryKeys.insurancePlans(params),
    queryFn: () => insuranceService.list(params),
  });
}

export function useCreateInsurancePlan() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: InsurancePlanInput) => insuranceService.create(input),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["insurance"] });
      qc.invalidateQueries({ queryKey: queryKeys.onboardingStatus });
    },
  });
}

export function useUpdateInsurancePlan() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, input }: { id: string; input: InsurancePlanUpdateInput }) =>
      insuranceService.update(id, input),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["insurance"] }),
  });
}

export function useDeleteInsurancePlan() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => insuranceService.remove(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["insurance"] }),
  });
}

/* ─── Clinic profile / business hours / widget settings / onboarding ── */

export function useClinicProfile(enabled = true) {
  return useQuery({
    queryKey: queryKeys.clinicProfile,
    queryFn: () => clinicsService.getMe(),
    enabled,
  });
}

export function useUpdateClinicProfile() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: ClinicProfileUpdateInput) => clinicsService.updateMe(input),
    onSuccess: (data) => {
      qc.setQueryData(queryKeys.clinicProfile, data);
      qc.invalidateQueries({ queryKey: queryKeys.onboardingStatus });
      qc.invalidateQueries({ queryKey: queryKeys.me });
    },
  });
}

export function useBusinessHours() {
  return useQuery({
    queryKey: queryKeys.businessHours,
    queryFn: () => clinicsService.getBusinessHours(),
  });
}

export function useUpdateBusinessHours() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: BusinessHourInput[]) => clinicsService.updateBusinessHours(input),
    onSuccess: (data) => {
      qc.setQueryData(queryKeys.businessHours, data);
      qc.invalidateQueries({ queryKey: queryKeys.onboardingStatus });
    },
  });
}

export function useWidgetSettings() {
  return useQuery({
    queryKey: queryKeys.widgetSettings,
    queryFn: () => clinicsService.getWidgetSettings(),
  });
}

export function useUpdateWidgetSettings() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: WidgetSettingsUpdateInput) =>
      clinicsService.updateWidgetSettings(input),
    onSuccess: (data) => qc.setQueryData(queryKeys.widgetSettings, data),
  });
}

export function useOnboardingStatus(enabled = true) {
  return useQuery({
    queryKey: queryKeys.onboardingStatus,
    queryFn: () => clinicsService.getOnboardingStatus(),
    enabled,
  });
}

export function useCompleteOnboarding() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => clinicsService.completeOnboarding(),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.me });
      qc.invalidateQueries({ queryKey: queryKeys.clinicProfile });
    },
  });
}

export function useClinicAnalytics(days: number) {
  return useQuery({
    queryKey: queryKeys.clinicAnalytics(days),
    queryFn: () => analyticsService.clinic(days),
  });
}

export function usePlatformAiUsage(days: number, enabled = true) {
  return useQuery({
    queryKey: queryKeys.platformAiUsage(days),
    queryFn: () => platformService.aiUsage(days),
    enabled,
  });
}

export function usePlatformOverview(enabled = true) {
  return useQuery({
    queryKey: queryKeys.platformOverview,
    queryFn: () => platformService.overview(),
    enabled,
  });
}

export function usePlatformClinics(search = "", enabled = true) {
  return useQuery({
    queryKey: queryKeys.platformClinics(search),
    queryFn: () => platformService.listClinics(search),
    enabled,
  });
}

export function usePlatformApplications(status = "", enabled = true) {
  return useQuery({
    queryKey: queryKeys.platformApplications(status),
    queryFn: () => platformService.listApplications(status),
    enabled,
  });
}

export function usePlatformUsers(params?: { search?: string; role?: string }, enabled = true) {
  return useQuery({
    queryKey: queryKeys.platformUsers(params),
    queryFn: () => platformService.listUsers(params),
    enabled,
  });
}

export function usePlatformSubscriptions(
  params?: { status?: string; search?: string },
  enabled = true
) {
  return useQuery({
    queryKey: queryKeys.platformSubscriptions(params),
    queryFn: () => platformService.listSubscriptions(params),
    enabled,
  });
}

export function usePlatformDocuments(
  params?: { status?: string; search?: string },
  enabled = true
) {
  return useQuery({
    queryKey: queryKeys.platformDocuments(params),
    queryFn: () => platformService.listDocuments(params),
    enabled,
  });
}

export function usePlatformMonitoring(days: number, enabled = true) {
  return useQuery({
    queryKey: queryKeys.platformMonitoring(days),
    queryFn: () => platformService.aiMonitoring(days),
    enabled,
  });
}

export function usePlatformAudit(
  params?: { action?: string; search?: string },
  enabled = true
) {
  return useQuery({
    queryKey: queryKeys.platformAudit(params),
    queryFn: () => platformService.listAudit(params),
    enabled,
  });
}

export function usePlatformSettings(enabled = true) {
  return useQuery({
    queryKey: queryKeys.platformSettings,
    queryFn: () => platformService.settings(),
    enabled,
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
    refetchInterval: (query) => {
      const rows = query.state.data;
      if (!rows?.length) return false;
      return rows.some(documentIsActive) ? 1500 : false;
    },
  });
}

export function useDocument(id: string | null) {
  return useQuery({
    queryKey: queryKeys.document(id ?? ""),
    queryFn: () => documentsService.get(id!),
    enabled: Boolean(id),
    refetchInterval: (query) => {
      const doc = query.state.data;
      if (!doc) return false;
      return documentIsActive(doc) ? 1500 : false;
    },
  });
}

export function useDocumentChunks(id: string | null) {
  return useQuery({
    queryKey: queryKeys.chunks(id ?? ""),
    queryFn: () => documentsService.chunks(id!),
    enabled: Boolean(id),
  });
}

export function useUploadDocument() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      file,
      title,
      onProgress,
    }: {
      file: File;
      title?: string;
      onProgress?: (percent: number) => void;
    }) => documentsService.upload(file, title, onProgress),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.documents }),
  });
}

export function useUpdateDocument() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, input }: { id: string; input: DocumentUpdateInput }) =>
      documentsService.update(id, input),
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: queryKeys.documents });
      qc.invalidateQueries({ queryKey: queryKeys.document(vars.id) });
    },
  });
}

export function useDeleteDocument() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => documentsService.remove(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.documents }),
  });
}

export function useCancelDocument() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => documentsService.cancel(id),
    onSuccess: (_data, id) => {
      qc.invalidateQueries({ queryKey: queryKeys.documents });
      qc.invalidateQueries({ queryKey: queryKeys.document(id) });
    },
  });
}

export function useReindexDocument() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => documentsService.reindex(id),
    onSuccess: (_data, id) => {
      qc.invalidateQueries({ queryKey: queryKeys.documents });
      qc.invalidateQueries({ queryKey: queryKeys.document(id) });
    },
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
    mutationFn: ({
      visitor_id,
      ...input
    }: WidgetGuestChatInput & { visitor_id?: string | null }) =>
      widgetService.sendGuestMessage(input, visitor_id),
  });
}

export function useMarketingChat() {
  return useMutation({
    mutationFn: (input: MarketingChatInput) =>
      widgetService.sendMarketingMessage(input),
  });
}

/* ─── Staff conversations inbox ────────────────────────────────── */

export function useConversations(
  params?: import("@/types/api").ConversationListParams
) {
  return useQuery({
    queryKey: queryKeys.conversations(params),
    queryFn: () => chatService.listConversations(params),
  });
}

export function useConversationMessages(sessionId: string | null) {
  return useInfiniteQuery({
    queryKey: ["conversations", sessionId, "messages"] as const,
    queryFn: ({ pageParam }: { pageParam?: number }) =>
      chatService.getConversationMessages(sessionId as string, {
        before: pageParam,
      }),
    initialPageParam: undefined as number | undefined,
    // The cursor for the *next* (older) page is the oldest message's own
    // sequence_number in the page just loaded — same cursor semantics as
    // the patient-facing widget's own pagination.
    getNextPageParam: (lastPage) =>
      lastPage.has_more && lastPage.messages.length
        ? lastPage.messages[0].sequence_number
        : undefined,
    enabled: Boolean(sessionId),
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

/* ─── Billing (Paddle) ─────────────────────────────────────── */

export function usePlans() {
  return useQuery({
    queryKey: queryKeys.billingPlans,
    queryFn: () => billingService.listPlans(),
  });
}

export function useSubscription(options?: { watch?: boolean }) {
  return useQuery({
    queryKey: queryKeys.billingSubscription,
    queryFn: () => billingService.getSubscription(),
    refetchInterval: options?.watch ? 3000 : false,
  });
}

export function useCreateCheckout() {
  return useMutation({
    mutationFn: (input: CheckoutInput) => billingService.createCheckout(input),
  });
}

export function useCancelSubscription() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: CancelSubscriptionInput) =>
      billingService.cancelSubscription(input),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.billingSubscription });
    },
  });
}

export function useChangePlan() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: ChangePlanInput) => billingService.changePlan(input),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.billingSubscription });
    },
  });
}

export function useResumeSubscription() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => billingService.resumeSubscription(),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.billingSubscription });
    },
  });
}

/* ─── Spreadsheet data import ──────────────────────────────── */

function invalidateForRecordType(qc: ReturnType<typeof useQueryClient>, recordType: ImportRecordType) {
  const key = {
    providers: "doctors",
    services: "services",
    specialties: "specialties",
    insurance: "insurance",
  }[recordType];
  qc.invalidateQueries({ queryKey: [key] });
  qc.invalidateQueries({ queryKey: queryKeys.onboardingStatus });
}

export function useImportJobs(recordType?: ImportRecordType) {
  return useQuery({
    queryKey: queryKeys.importJobs(recordType),
    queryFn: () => importerService.listJobs(recordType),
  });
}

export function useImportJob(id: string | null) {
  return useQuery({
    queryKey: queryKeys.importJob(id ?? ""),
    queryFn: () => importerService.getJob(id!),
    enabled: Boolean(id),
    refetchInterval: (query) => (importJobIsActive(query.state.data) ? 1200 : false),
  });
}

export function useImportJobRecords(id: string | null, status?: string) {
  return useQuery({
    queryKey: queryKeys.importJobRecords(id ?? "", status),
    queryFn: () => importerService.listRecords(id!, status),
    enabled: Boolean(id),
  });
}

export function useCreateImportJob() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      recordType,
      file,
      onProgress,
    }: {
      recordType: ImportRecordType;
      file: File;
      onProgress?: (percent: number) => void;
    }) => importerService.createJob(recordType, file, onProgress),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["import-jobs"] }),
  });
}

export function useUpdateImportMapping() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ jobId, input }: { jobId: string; input: ImportMappingUpdateInput }) =>
      importerService.updateMapping(jobId, input),
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: queryKeys.importJob(vars.jobId) });
      qc.invalidateQueries({ queryKey: ["import-jobs", vars.jobId, "records"] });
    },
  });
}

export function useUpdateImportRecord() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      jobId,
      recordId,
      input,
    }: {
      jobId: string;
      recordId: string;
      input: ImportRecordUpdateInput;
    }) => importerService.updateRecord(jobId, recordId, input),
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: ["import-jobs", vars.jobId, "records"] });
      qc.invalidateQueries({ queryKey: queryKeys.importJob(vars.jobId) });
    },
  });
}

export function useApproveImportRecord() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ jobId, recordId }: { jobId: string; recordId: string }) =>
      importerService.approveRecord(jobId, recordId),
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: ["import-jobs", vars.jobId, "records"] });
      qc.invalidateQueries({ queryKey: queryKeys.importJob(vars.jobId) });
    },
  });
}

export function useApproveAllImportRecords() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (jobId: string) => importerService.approveAll(jobId),
    onSuccess: (_data, jobId) => {
      qc.invalidateQueries({ queryKey: ["import-jobs", jobId, "records"] });
      qc.invalidateQueries({ queryKey: queryKeys.importJob(jobId) });
    },
  });
}

export function useRejectImportRecord() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ jobId, recordId }: { jobId: string; recordId: string }) =>
      importerService.rejectRecord(jobId, recordId),
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: ["import-jobs", vars.jobId, "records"] });
      qc.invalidateQueries({ queryKey: queryKeys.importJob(vars.jobId) });
    },
  });
}

export function useCommitImportJob() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ jobId }: { jobId: string; recordType: ImportRecordType }) =>
      importerService.commitJob(jobId),
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: queryKeys.importJob(vars.jobId) });
      invalidateForRecordType(qc, vars.recordType);
    },
  });
}

export function useDeleteImportJob() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (jobId: string) => importerService.deleteJob(jobId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["import-jobs"] }),
  });
}

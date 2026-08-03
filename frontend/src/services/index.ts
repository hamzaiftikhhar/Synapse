import { api, persistStaffTokens, clearStaffTokens, widgetApi, setPatientToken, setActiveTenant } from "@/lib/api/client";
import { STORAGE_KEYS } from "@/constants";
import type {
  Appointment,
  AppointmentInput,
  AppointmentUpdateInput,
  ChatMessageInput,
  ChatMessageResponse,
  Doctor,
  DoctorInput,
  DoctorUpdateInput,
  DocumentChunk,
  DocumentUpdateInput,
  KnowledgeDocument,
  ListParams,
  MeResponse,
  MessageOut,
  OTPSendInput,
  OTPSendResponse,
  OTPVerifyInput,
  Paginated,
  Patient,
  PatientInput,
  PatientTokenResponse,
  PatientUpdateInput,
  Service,
  ServiceInput,
  ServiceUpdateInput,
  StaffLoginInput,
  StaffRegisterInput,
  StaffTokenResponse,
  Tenant,
} from "@/types/api";

function listQuery(params?: ListParams & Record<string, unknown>) {
  return { params };
}

/* ─── Auth (Staff) ─────────────────────────────────────────── */

export const authService = {
  async login(input: StaffLoginInput, remember = true) {
    const { data } = await api.post<StaffTokenResponse>("/auth/login", input);
    persistStaffTokens(data.access_token, data.refresh_token, remember);
    if (data.tenant) setActiveTenant(data.tenant);
    else if (data.clinic?.slug) setActiveTenant(data.clinic.slug);
    return data;
  },
  async register(input: StaffRegisterInput) {
    const { data } = await api.post<MessageOut>("/auth/register", input);
    return data;
  },
  async verifyEmail(token: string) {
    const { data } = await api.post<MessageOut>("/auth/verify-email", { token });
    return data;
  },
  async resendVerification(email: string) {
    const { data } = await api.post<MessageOut>("/auth/resend-verification", {
      email,
    });
    return data;
  },
  async forgotPassword(email: string) {
    const { data } = await api.post<MessageOut>("/auth/forgot-password", {
      email,
    });
    return data;
  },
  async resetPassword(token: string, password: string) {
    const { data } = await api.post<MessageOut>("/auth/reset-password", {
      token,
      password,
    });
    return data;
  },
  async changePassword(current_password: string, new_password: string) {
    const { data } = await api.post<MessageOut>("/auth/change-password", {
      current_password,
      new_password,
    });
    return data;
  },
  async me() {
    const { data } = await api.get<MeResponse>("/auth/me");
    return data;
  },
  async tenants() {
    const { data } = await api.get<Tenant[]>("/auth/tenants");
    return data;
  },
  async selectTenant(tenant: string) {
    const { data } = await api.post<StaffTokenResponse>("/auth/tenants/select", {
      tenant,
    });
    persistStaffTokens(data.access_token, data.refresh_token, true);
    setActiveTenant(data.tenant || tenant);
    return data;
  },
  async createClinic(input: {
    name: string;
    slug: string;
    email?: string | null;
    phone?: string;
    timezone?: string;
  }) {
    const { data } = await api.post<import("@/types/api").Clinic>(
      "/auth/clinics",
      input
    );
    setActiveTenant(data.slug);
    return data;
  },
  async enterClinic(tenant: string) {
    const { data } = await api.post<StaffTokenResponse>("/auth/enter-clinic", {
      tenant,
    });
    const remember = localStorage.getItem(STORAGE_KEYS.rememberMe) === "1";
    persistStaffTokens(data.access_token, data.refresh_token, remember);
    setActiveTenant(data.tenant || data.clinic?.slug || tenant);
    return data;
  },
  async exitClinic() {
    const { data } = await api.post<StaffTokenResponse>("/auth/exit-clinic", {});
    const remember = localStorage.getItem(STORAGE_KEYS.rememberMe) === "1";
    persistStaffTokens(data.access_token, data.refresh_token, remember);
    setActiveTenant(null);
    return data;
  },
  async refresh(refresh_token: string) {
    const { data } = await api.post<StaffTokenResponse>("/auth/refresh", {
      refresh_token,
    });
    return data;
  },
  logout() {
    clearStaffTokens();
  },
};

export const platformService = {
  async listClinics(search = "") {
    const { data } = await api.get<
      Array<{
        id: string;
        slug: string;
        name: string;
        email: string;
        status: string;
        timezone: string;
        doctor_count: number;
        staff_count: number;
        document_count: number;
        appointment_count_30d: number;
        token_usage_30d: number;
        created_at: string;
      }>
    >("/platform/clinics", { params: search ? { search } : undefined });
    return data;
  },
  async patchClinic(id: string, input: { status?: string; name?: string }) {
    const { data } = await api.patch(`/platform/clinics/${id}`, input);
    return data;
  },
};

/* ─── Widget / Patient Auth ────────────────────────────────── */

export const widgetAuthService = {
  async sendOtp(input: OTPSendInput) {
    const { data } = await widgetApi.post<OTPSendResponse>(
      "/widget/otp/send",
      input
    );
    return data;
  },
  async verifyOtp(input: OTPVerifyInput) {
    const { data } = await widgetApi.post<PatientTokenResponse>(
      "/widget/otp/verify",
      input
    );
    setPatientToken(data.access_token);
    return data;
  },
};

/* ─── Widget (public) ──────────────────────────────────────── */

export const widgetService = {
  async getConfig(clinicSlug: string) {
    const { data } = await widgetApi.get<import("@/types/api").WidgetConfig>(
      "/widget/config",
      { params: { clinic_slug: clinicSlug } }
    );
    return data;
  },
  async sendGuestMessage(input: import("@/types/api").WidgetGuestChatInput) {
    const { data } = await widgetApi.post<ChatMessageResponse>(
      "/widget/chat/guest",
      input
    );
    return data;
  },
  async sendMarketingMessage(input: import("@/types/api").MarketingChatInput) {
    const { data } = await widgetApi.post<ChatMessageResponse>(
      "/widget/chat/marketing",
      input
    );
    return data;
  },
};

/* ─── Booking wizard ───────────────────────────────────────── */

export const bookingService = {
  async start(input: import("@/types/api").BookingStartInput) {
    const { data } = await widgetApi.post<import("@/types/api").BookingStepPayload>(
      "/widget/booking/start",
      input
    );
    return data;
  },
  async step(input: import("@/types/api").BookingStepInput) {
    const { data } = await widgetApi.post<import("@/types/api").BookingStepPayload>(
      "/widget/booking/step",
      input
    );
    return data;
  },
  async sendOtp(input: {
    clinic_slug: string;
    session_token: string;
    booking_id: string;
  }) {
    const { data } = await widgetApi.post<{
      message: string;
      session_token: string;
      booking_id: string;
      expires_in_minutes: number;
      debug_code?: string | null;
      phone: string;
    }>("/widget/booking/otp/send", input);
    return data;
  },
  async confirm(input: import("@/types/api").BookingConfirmInput) {
    const { data } = await widgetApi.post<import("@/types/api").BookingStepPayload>(
      "/widget/booking/confirm",
      input
    );
    return data;
  },
};

/* ─── Chat ─────────────────────────────────────────────────── */

export const chatService = {
  async sendPatientMessage(input: ChatMessageInput) {
    const { data } = await widgetApi.post<ChatMessageResponse>(
      "/chat/message",
      input
    );
    return data;
  },
  async sendStaffMessage(input: ChatMessageInput) {
    const { data } = await api.post<ChatMessageResponse>(
      "/chat/message/staff",
      input
    );
    return data;
  },
};

/* ─── Patients ─────────────────────────────────────────────── */

export const patientsService = {
  async list(params?: ListParams) {
    const { data } = await api.get<Paginated<Patient>>(
      "/patients",
      listQuery(params)
    );
    return data;
  },
  async get(id: string) {
    const { data } = await api.get<Patient>(`/patients/${id}`);
    return data;
  },
  async create(input: PatientInput) {
    const { data } = await api.post<Patient>("/patients", input);
    return data;
  },
  async update(id: string, input: PatientUpdateInput) {
    const { data } = await api.patch<Patient>(`/patients/${id}`, input);
    return data;
  },
  async remove(id: string) {
    const { data } = await api.delete<MessageOut>(`/patients/${id}`);
    return data;
  },
};

/* ─── Doctors ──────────────────────────────────────────────── */

export const doctorsService = {
  async list(params?: ListParams) {
    const { data } = await api.get<Paginated<Doctor>>(
      "/doctors",
      listQuery(params)
    );
    return data;
  },
  async get(id: string) {
    const { data } = await api.get<Doctor>(`/doctors/${id}`);
    return data;
  },
  async create(input: DoctorInput) {
    const { data } = await api.post<Doctor>("/doctors", input);
    return data;
  },
  async update(id: string, input: DoctorUpdateInput) {
    const { data } = await api.patch<Doctor>(`/doctors/${id}`, input);
    return data;
  },
  async remove(id: string) {
    const { data } = await api.delete<MessageOut>(`/doctors/${id}`);
    return data;
  },
};

/* ─── Services ─────────────────────────────────────────────── */

export const servicesService = {
  async list(params?: ListParams) {
    const { data } = await api.get<Paginated<Service>>(
      "/services",
      listQuery(params)
    );
    return data;
  },
  async get(id: string) {
    const { data } = await api.get<Service>(`/services/${id}`);
    return data;
  },
  async create(input: ServiceInput) {
    const { data } = await api.post<Service>("/services", input);
    return data;
  },
  async update(id: string, input: ServiceUpdateInput) {
    const { data } = await api.patch<Service>(`/services/${id}`, input);
    return data;
  },
  async remove(id: string) {
    const { data } = await api.delete<MessageOut>(`/services/${id}`);
    return data;
  },
};

/* ─── Appointments ─────────────────────────────────────────── */

export type AppointmentListParams = ListParams & {
  status?: string;
  doctor_id?: string;
  patient_id?: string;
  from_date?: string;
  to_date?: string;
};

export const appointmentsService = {
  async list(params?: AppointmentListParams) {
    const { data } = await api.get<Paginated<Appointment>>(
      "/appointments",
      listQuery(params)
    );
    return data;
  },
  async get(id: string) {
    const { data } = await api.get<Appointment>(`/appointments/${id}`);
    return data;
  },
  async create(input: AppointmentInput) {
    const { data } = await api.post<Appointment>("/appointments", input);
    return data;
  },
  async update(id: string, input: AppointmentUpdateInput) {
    const { data } = await api.patch<Appointment>(`/appointments/${id}`, input);
    return data;
  },
  async remove(id: string) {
    const { data } = await api.delete<MessageOut>(`/appointments/${id}`);
    return data;
  },
};

/* ─── Knowledge / Documents ────────────────────────────────── */

export const documentsService = {
  async list() {
    const { data } = await api.get<KnowledgeDocument[]>("/documents");
    return data;
  },
  async get(id: string) {
    const { data } = await api.get<KnowledgeDocument>(`/documents/${id}`);
    return data;
  },
  async upload(
    file: File,
    title = "",
    onProgress?: (percent: number) => void
  ) {
    const form = new FormData();
    form.append("file", file);
    if (title) form.append("title", title);
    const { data } = await api.post<KnowledgeDocument>("/documents", form, {
      headers: { "Content-Type": "multipart/form-data" },
      onUploadProgress: (event) => {
        if (!onProgress || !event.total) return;
        onProgress(Math.min(100, Math.round((event.loaded / event.total) * 100)));
      },
    });
    return data;
  },
  async update(id: string, input: DocumentUpdateInput) {
    const { data } = await api.patch<KnowledgeDocument>(
      `/documents/${id}`,
      input
    );
    return data;
  },
  async remove(id: string) {
    await api.delete(`/documents/${id}`);
  },
  async cancel(id: string) {
    const { data } = await api.post<KnowledgeDocument>(
      `/documents/${id}/cancel`
    );
    return data;
  },
  async chunks(id: string) {
    const { data } = await api.get<DocumentChunk[]>(`/documents/${id}/chunks`);
    return data;
  },
  async reindex(id: string) {
    const { data } = await api.post<KnowledgeDocument>(
      `/documents/${id}/reindex`
    );
    return data;
  },
  async downloadBlob(id: string, inline = false) {
    const { data } = await api.get<Blob>(`/documents/${id}/download`, {
      params: inline ? { inline: true } : undefined,
      responseType: "blob",
    });
    return data;
  },
};

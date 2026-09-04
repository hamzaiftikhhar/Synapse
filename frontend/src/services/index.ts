import { api, persistStaffTokens, clearStaffTokens, widgetApi, setPatientToken, setActiveTenant } from "@/lib/api/client";
import { STORAGE_KEYS } from "@/constants";
import type {
  Appointment,
  AppointmentInput,
  AppointmentUpdateInput,
  AvailableSlot,
  BusinessHour,
  BusinessHourInput,
  ChatMessageInput,
  ChatMessageResponse,
  ChatMessagesPageOut,
  ChatResumeOut,
  ClinicProfile,
  ClinicProfileUpdateInput,
  Doctor,
  DoctorInput,
  DoctorScheduleInput,
  DoctorScheduleSlot,
  DoctorUpdateInput,
  DocumentChunk,
  DocumentUpdateInput,
  ImportCommitOut,
  ImportJob,
  ImportMappingUpdateInput,
  ImportBulkApproveOut,
  ImportRecord,
  ImportRecordType,
  ImportRecordUpdateInput,
  InsurancePlan,
  InsurancePlanInput,
  InsurancePlanUpdateInput,
  KnowledgeDocument,
  ListParams,
  MeResponse,
  MessageOut,
  OnboardingStatus,
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
  Specialty,
  SpecialtyInput,
  SpecialtyUpdateInput,
  StaffLoginInput,
  StaffRegisterInput,
  StaffTokenResponse,
  Tenant,
  User,
  WidgetSettingsOut,
  WidgetSettingsUpdateInput,
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
  async acceptInvite(input: import("@/types/api").AcceptInviteInput) {
    const { data } = await api.post<StaffTokenResponse>("/auth/accept-invite", input);
    persistStaffTokens(data.access_token, data.refresh_token, true);
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
  async patchMe(input: { first_name?: string; last_name?: string; phone_number?: string }) {
    const { data } = await api.patch<User>("/auth/me", input);
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
  async overview() {
    const { data } = await api.get<import("@/types/api").PlatformOverview>("/platform/overview");
    return data;
  },
  async listClinics(search = "") {
    const { data } = await api.get<import("@/types/api").PlatformClinicRow[]>(
      "/platform/clinics",
      { params: search ? { search } : undefined }
    );
    return data;
  },
  async createClinic(input: {
    name: string;
    slug: string;
    email: string;
    phone?: string;
    timezone?: string;
    owner_email?: string;
  }) {
    const { data } = await api.post("/platform/clinics", input);
    return data;
  },
  async patchClinic(id: string, input: { status?: string; name?: string }) {
    const { data } = await api.patch(`/platform/clinics/${id}`, input);
    return data;
  },
  async listApplications(status = "") {
    const { data } = await api.get<import("@/types/api").ClinicApplication[]>(
      "/platform/applications",
      { params: status ? { status } : undefined }
    );
    return data;
  },
  async getApplication(id: string) {
    const { data } = await api.get<import("@/types/api").ClinicApplication>(
      `/platform/applications/${id}`
    );
    return data;
  },
  async approveApplication(id: string, options?: { slug?: string; plan_slug?: string }) {
    const { data } = await api.post<import("@/types/api").ApplicationActionResponse>(
      `/platform/applications/${id}/approve`,
      { slug: options?.slug || null, plan_slug: options?.plan_slug || null }
    );
    return data;
  },
  async rejectApplication(id: string, input: import("@/types/api").RejectApplicationInput) {
    const { data } = await api.post<import("@/types/api").ClinicApplication>(
      `/platform/applications/${id}/reject`,
      input
    );
    return data;
  },
  async reviewApplication(id: string) {
    const { data } = await api.post<import("@/types/api").ClinicApplication>(
      `/platform/applications/${id}/review`,
      {}
    );
    return data;
  },
  async aiUsage(days = 30) {
    const { data } = await api.get<import("@/types/api").PlatformAiUsage>(
      "/platform/ai-usage",
      { params: { days } }
    );
    return data;
  },
  async listUsers(params?: { search?: string; role?: string }) {
    const { data } = await api.get<import("@/types/api").PlatformUser[]>("/platform/users", {
      params,
    });
    return data;
  },
  async inviteUser(input: import("@/types/api").InviteUserInput) {
    const { data } = await api.post<import("@/types/api").PlatformUser>(
      "/platform/users/invite",
      input
    );
    return data;
  },
  async patchUser(
    id: number,
    input: { is_active?: boolean; role?: string; first_name?: string; last_name?: string }
  ) {
    const { data } = await api.patch<import("@/types/api").PlatformUser>(
      `/platform/users/${id}`,
      input
    );
    return data;
  },
  async listSubscriptions(params?: { status?: string; search?: string }) {
    const { data } = await api.get<import("@/types/api").PlatformSubscription[]>(
      "/platform/subscriptions",
      { params }
    );
    return data;
  },
  async listPlans() {
    const { data } = await api.get<import("@/types/api").PlatformPlan[]>("/platform/plans");
    return data;
  },
  async patchPlan(
    id: string,
    input: Partial<
      Pick<
        import("@/types/api").PlatformPlan,
        | "name"
        | "display_price_cents"
        | "is_active"
        | "display_order"
        | "paddle_price_id_sandbox"
        | "paddle_price_id_live"
      >
    >
  ) {
    const { data } = await api.patch<import("@/types/api").PlatformPlan>(
      `/platform/plans/${id}`,
      input
    );
    return data;
  },
  async listDocuments(params?: { status?: string; search?: string }) {
    const { data } = await api.get<import("@/types/api").PlatformDocument[]>(
      "/platform/documents",
      { params }
    );
    return data;
  },
  async reindexDocument(id: string) {
    const { data } = await api.post<import("@/types/api").PlatformDocument>(
      `/platform/documents/${id}/reindex`,
      {}
    );
    return data;
  },
  async deleteDocument(id: string) {
    const { data } = await api.delete<import("@/types/api").PlatformDocument>(
      `/platform/documents/${id}`
    );
    return data;
  },
  async aiMonitoring(days = 7) {
    const { data } = await api.get<import("@/types/api").PlatformMonitoring>(
      "/platform/ai-monitoring",
      { params: { days } }
    );
    return data;
  },
  async listAudit(params?: { action?: string; search?: string }) {
    const { data } = await api.get<import("@/types/api").PlatformAuditRow[]>("/platform/audit", {
      params,
    });
    return data;
  },
  async settings() {
    const { data } = await api.get<import("@/types/api").PlatformSettings>("/platform/settings");
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

/**
 * Bearer identifier for the anonymous ChatVisitor — always a header, never
 * a body/query param (matches the backend contract exactly: keeps it out
 * of request-body logs, and it's an identifier, not an authorization
 * token, so it doesn't belong in a URL either). Omitted entirely when
 * there is no visitor yet — a first-time browser sends no header at all,
 * not an empty string.
 */
const VISITOR_HEADER = "X-Synapse-Visitor-Id";

function visitorHeaders(visitorId?: string | null) {
  return visitorId ? { [VISITOR_HEADER]: visitorId } : undefined;
}

export const widgetService = {
  async getConfig(clinicSlug: string) {
    const { data } = await widgetApi.get<import("@/types/api").WidgetConfig>(
      "/widget/config",
      { params: { clinic_slug: clinicSlug } }
    );
    return data;
  },
  /**
   * Pure read — never creates a ChatVisitor or ChatSession server-side.
   * Callers must not invoke this at all when there is no stored visitor
   * id (see chat-widget.tsx's mount effect) — that's what keeps a
   * brand-new browser from hitting the backend just to be told "no history".
   */
  async resume(clinicSlug: string, visitorId?: string | null) {
    const { data } = await widgetApi.get<ChatResumeOut>("/widget/chat/resume", {
      params: { clinic_slug: clinicSlug },
      headers: visitorHeaders(visitorId),
    });
    return data;
  },
  /** Cursor pagination for older messages — `before` is the oldest
   * sequence_number already loaded; omit for the newest page. */
  async getMessages(
    sessionToken: string,
    clinicSlug: string,
    params: { before?: number; limit?: number } = {},
    visitorId?: string | null
  ) {
    const { data } = await widgetApi.get<ChatMessagesPageOut>(
      `/widget/chat/sessions/${encodeURIComponent(sessionToken)}/messages`,
      {
        params: { clinic_slug: clinicSlug, ...params },
        headers: visitorHeaders(visitorId),
      }
    );
    return data;
  },
  async sendGuestMessage(
    input: import("@/types/api").WidgetGuestChatInput,
    visitorId?: string | null
  ) {
    const { data } = await widgetApi.post<ChatMessageResponse>(
      "/widget/chat/guest",
      input,
      { headers: visitorHeaders(visitorId) }
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

/** Deterministic UI actions — the frontend already knows the intent (a
 * card or a frontend-authored menu button was clicked, not typed free
 * text), so these bypass /chat/guest and its NLU/LLM classification
 * entirely. Same ChatMessageResponse shape as chatService so the result
 * renders through the existing parseChatResponse path unchanged. */
export const widgetUiActionService = {
  async searchSpecialty(input: { clinic_slug: string; specialty_id: string }) {
    const { data } = await widgetApi.post<ChatMessageResponse>(
      "/widget/specialty/search",
      input
    );
    return data;
  },
  async browseDoctors(input: { clinic_slug: string }) {
    const { data } = await widgetApi.post<ChatMessageResponse>(
      "/widget/doctors/browse",
      input
    );
    return data;
  },
  async clinicHours(input: { clinic_slug: string }) {
    const { data } = await widgetApi.post<ChatMessageResponse>(
      "/widget/clinic/hours",
      input
    );
    return data;
  },
};

/* ─── Appointments (widget, OTP-verified session) ──────────── */

export const widgetAppointmentsService = {
  async list(input: { clinic_slug: string; session_token: string }) {
    const { data } = await widgetApi.post<{
      appointments: import("@/types/chat").AppointmentCardData[];
    }>("/widget/appointments/list", input);
    return data;
  },
  async cancel(input: {
    clinic_slug: string;
    session_token: string;
    appointment_id: string;
  }) {
    const { data } = await widgetApi.post<{ detail: string; appointment_id: string }>(
      "/widget/appointments/cancel",
      input
    );
    return data;
  },
  async reschedule(input: {
    clinic_slug: string;
    session_token: string;
    appointment_id: string;
  }) {
    const { data } = await widgetApi.post<{
      detail: string;
      appointment_id: string;
      doctor_id: string;
      doctor_name: string;
      service_id: string | null;
      service_name: string | null;
      start_time: string;
      end_time: string;
      when?: string;
    }>("/widget/appointments/reschedule", input);
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
      input,
      { timeout: 90_000 }
    );
    return data;
  },
  /** Pure read — mirrors widgetService.resume, but for the dashboard's
   * own staff/QA chat widget: finds *this staff user's* most recent QA
   * session in the *current* clinic (both resolved from the staff JWT,
   * same `api` client as sendStaffMessage), never creates one. */
  async resumeStaffChat() {
    const { data } = await api.get<import("@/types/api").StaffChatResumeOut>(
      "/chat/message/staff/resume"
    );
    return data;
  },
  /** Staff-authenticated — a clinic's own staff and a super admin who has
   * entered the clinic both resolve to the same tenant via the JWT, so
   * this is exactly the same `api` client every other dashboard list
   * uses, not the widget's visitor-header-based client. */
  async listConversations(params?: import("@/types/api").ConversationListParams) {
    const { data } = await api.get<
      import("@/types/api").Paginated<import("@/types/api").ConversationSummary>
    >("/chat/conversations", { params });
    return data;
  },
  async getConversationMessages(
    sessionId: string,
    params: { before?: number; limit?: number } = {}
  ) {
    const { data } = await api.get<import("@/types/api").ConversationMessagesOut>(
      `/chat/conversations/${encodeURIComponent(sessionId)}/messages`,
      { params }
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
  async getSchedule(id: string) {
    const { data } = await api.get<DoctorScheduleSlot[]>(`/doctors/${id}/schedule`);
    return data;
  },
  async updateSchedule(id: string, input: DoctorScheduleInput[]) {
    const { data } = await api.put<DoctorScheduleSlot[]>(
      `/doctors/${id}/schedule`,
      input
    );
    return data;
  },
  async getAvailableSlots(
    id: string,
    date: string,
    excludeAppointmentId?: string
  ) {
    const { data } = await api.get<AvailableSlot[]>(
      `/doctors/${id}/available-slots`,
      { params: { date, exclude_appointment_id: excludeAppointmentId } }
    );
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

/* ─── Clinic profile / business hours / widget settings / onboarding ── */

export const clinicsService = {
  async getMe() {
    const { data } = await api.get<ClinicProfile>("/clinics/me");
    return data;
  },
  async updateMe(input: ClinicProfileUpdateInput) {
    const { data } = await api.patch<ClinicProfile>("/clinics/me", input);
    return data;
  },
  async getBusinessHours() {
    const { data } = await api.get<BusinessHour[]>("/clinics/me/business-hours");
    return data;
  },
  async updateBusinessHours(input: BusinessHourInput[]) {
    const { data } = await api.put<BusinessHour[]>(
      "/clinics/me/business-hours",
      input
    );
    return data;
  },
  async getWidgetSettings() {
    const { data } = await api.get<WidgetSettingsOut>("/clinics/me/widget-settings");
    return data;
  },
  async updateWidgetSettings(input: WidgetSettingsUpdateInput) {
    const { data } = await api.patch<WidgetSettingsOut>(
      "/clinics/me/widget-settings",
      input
    );
    return data;
  },
  async getOnboardingStatus() {
    const { data } = await api.get<OnboardingStatus>("/clinics/me/onboarding-status");
    return data;
  },
  async completeOnboarding() {
    const { data } = await api.post<ClinicProfile>("/clinics/me/onboarding/complete");
    return data;
  },
};

/* ─── Clinic analytics ─────────────────────────────────────── */

export const analyticsService = {
  async clinic(days = 30) {
    const { data } = await api.get<import("@/types/api").ClinicAnalytics>(
      "/analytics",
      { params: { days } }
    );
    return data;
  },
  async overview(range = "30d") {
    const { data } = await api.get<import("@/types/api").AnalyticsOverview>(
      "/analytics/overview",
      { params: { range } }
    );
    return data;
  },
  async insights(range = "30d") {
    const { data } = await api.get<import("@/types/api").AnalyticsInsights>(
      "/analytics/insights",
      { params: { range } }
    );
    return data;
  },
  async breakdown(
    dimension: Exclude<
      import("@/types/api").AnalyticsBreakdownDimension,
      "doctor_status"
    >,
    range = "30d"
  ) {
    const { data } = await api.get<import("@/types/api").AnalyticsBreakdown>(
      "/analytics/breakdown",
      { params: { dimension, range } }
    );
    return data;
  },
  async doctorStatusBreakdown(range = "30d") {
    const { data } = await api.get<import("@/types/api").AnalyticsDoctorStatusBreakdown>(
      "/analytics/breakdown",
      { params: { dimension: "doctor_status", range } }
    );
    return data;
  },
  async calendar(year: number, month: number) {
    const { data } = await api.get<import("@/types/api").AnalyticsCalendar>(
      "/analytics/calendar",
      { params: { year, month } }
    );
    return data;
  },
};

export const billingService = {
  async listPlans() {
    const { data } = await api.get<import("@/types/api").Plan[]>("/billing/plans");
    return data;
  },
  async getSubscription() {
    const { data } = await api.get<import("@/types/api").Subscription>(
      "/billing/subscription"
    );
    return data;
  },
  async createCheckout(input: import("@/types/api").CheckoutInput) {
    const { data } = await api.post<import("@/types/api").CheckoutResponse>(
      "/billing/checkout",
      input
    );
    return data;
  },
  async cancelSubscription(input: import("@/types/api").CancelSubscriptionInput) {
    const { data } = await api.post<import("@/types/api").Subscription>(
      "/billing/subscription/cancel",
      input
    );
    return data;
  },
  async changePlan(input: import("@/types/api").ChangePlanInput) {
    const { data } = await api.post<import("@/types/api").Subscription>(
      "/billing/subscription/change-plan",
      input
    );
    return data;
  },
  async resumeSubscription() {
    const { data } = await api.post<import("@/types/api").Subscription>(
      "/billing/subscription/resume",
      {}
    );
    return data;
  },
};

/* ─── Clinic applications (public "Get Started" intake) ───────── */

export const applicationsService = {
  async submit(input: import("@/types/api").ClinicApplicationInput) {
    const { data } = await api.post<import("@/types/api").ClinicApplicationSubmitResponse>(
      "/applications",
      input
    );
    return data;
  },
};

/* ─── Specialties ──────────────────────────────────────────── */

export const specialtiesService = {
  async list(params?: ListParams) {
    const { data } = await api.get<Paginated<Specialty>>(
      "/specialties",
      listQuery(params)
    );
    return data;
  },
  async create(input: SpecialtyInput) {
    const { data } = await api.post<Specialty>("/specialties", input);
    return data;
  },
  async update(id: string, input: SpecialtyUpdateInput) {
    const { data } = await api.patch<Specialty>(`/specialties/${id}`, input);
    return data;
  },
  async remove(id: string) {
    const { data } = await api.delete<MessageOut>(`/specialties/${id}`);
    return data;
  },
};

/* ─── Insurance ────────────────────────────────────────────── */

export const insuranceService = {
  async list(params?: ListParams) {
    const { data } = await api.get<Paginated<InsurancePlan>>(
      "/insurance",
      listQuery(params)
    );
    return data;
  },
  async create(input: InsurancePlanInput) {
    const { data } = await api.post<InsurancePlan>("/insurance", input);
    return data;
  },
  async update(id: string, input: InsurancePlanUpdateInput) {
    const { data } = await api.patch<InsurancePlan>(`/insurance/${id}`, input);
    return data;
  },
  async remove(id: string) {
    const { data } = await api.delete<MessageOut>(`/insurance/${id}`);
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

/* ─── Spreadsheet data import ──────────────────────────────── */

export const importerService = {
  async listJobs(recordType?: ImportRecordType) {
    const { data } = await api.get<ImportJob[]>("/import/jobs", {
      params: recordType ? { record_type: recordType } : undefined,
    });
    return data;
  },
  async getJob(id: string) {
    const { data } = await api.get<ImportJob>(`/import/jobs/${id}`);
    return data;
  },
  async createJob(
    recordType: ImportRecordType,
    file: File,
    onProgress?: (percent: number) => void
  ) {
    const form = new FormData();
    form.append("record_type", recordType);
    form.append("file", file);
    const { data } = await api.post<ImportJob>("/import/jobs", form, {
      headers: { "Content-Type": "multipart/form-data" },
      onUploadProgress: (event) => {
        if (!onProgress || !event.total) return;
        onProgress(Math.min(100, Math.round((event.loaded / event.total) * 100)));
      },
    });
    return data;
  },
  async listRecords(jobId: string, status?: string) {
    const { data } = await api.get<Paginated<ImportRecord>>(
      `/import/jobs/${jobId}/records`,
      { params: { status, limit: 500 } }
    );
    return data;
  },
  async updateMapping(jobId: string, input: ImportMappingUpdateInput) {
    const { data } = await api.patch<ImportJob>(`/import/jobs/${jobId}/mapping`, input);
    return data;
  },
  async updateRecord(jobId: string, recordId: string, input: ImportRecordUpdateInput) {
    const { data } = await api.patch<ImportRecord>(
      `/import/jobs/${jobId}/records/${recordId}`,
      input
    );
    return data;
  },
  async approveRecord(jobId: string, recordId: string) {
    const { data } = await api.post<ImportRecord>(
      `/import/jobs/${jobId}/records/${recordId}/approve`
    );
    return data;
  },
  async approveAll(jobId: string) {
    const { data } = await api.post<ImportBulkApproveOut>(
      `/import/jobs/${jobId}/approve-all`
    );
    return data;
  },
  async rejectRecord(jobId: string, recordId: string) {
    const { data } = await api.post<ImportRecord>(
      `/import/jobs/${jobId}/records/${recordId}/reject`
    );
    return data;
  },
  async commitJob(jobId: string) {
    const { data } = await api.post<ImportCommitOut>(`/import/jobs/${jobId}/commit`);
    return data;
  },
  async deleteJob(jobId: string) {
    await api.delete(`/import/jobs/${jobId}`);
  },
};

/** Shared API domain types — aligned with Synapse OpenAPI schemas. */

export type UserRole = "SUPER_ADMIN" | "CLINIC_ADMIN" | "STAFF";

export type ClinicType =
  | "primary_care"
  | "medical_specialty"
  | "neurology"
  | "cardiology"
  | "dermatology"
  | "aesthetics"
  | "dental"
  | "physical_therapy"
  | "behavioral_health"
  | "laboratory"
  | "urgent_care"
  | "cosmetic_surgery"
  | "multi_specialty"
  | "other"
  | "";

export type ClinicAddress = {
  line1?: string;
  line2?: string;
  city?: string;
  state?: string;
  postal_code?: string;
  country?: string;
};

export type Clinic = {
  id: string;
  slug: string;
  name: string;
  timezone: string;
  status?: string;
  clinic_type?: ClinicType;
  phone?: string;
  address?: ClinicAddress;
  onboarding_step?: string;
  onboarding_completed_at?: string | null;
};

export type ClinicProfile = Clinic & {
  email: string;
  created_at: string;
  updated_at: string;
};

export type ClinicProfileUpdateInput = {
  name?: string;
  clinic_type?: ClinicType;
  email?: string;
  phone?: string;
  address?: ClinicAddress;
  timezone?: string;
  onboarding_step?: string;
};

export type BusinessHour = {
  day_of_week: number;
  open_time: string | null;
  close_time: string | null;
  is_closed: boolean;
};

export type BusinessHourInput = {
  day_of_week: number;
  open_time?: string | null;
  close_time?: string | null;
  is_closed?: boolean;
};

export type DoctorScheduleSlot = {
  id: string;
  day_of_week: number;
  start_time: string;
  end_time: string;
  slot_duration_min: number;
  is_active: boolean;
};

export type DoctorScheduleInput = {
  day_of_week: number;
  start_time: string;
  end_time: string;
  slot_duration_min?: number;
  is_active?: boolean;
};

export type WidgetSettingsConfig = {
  widget?: {
    primary_color?: string;
    position?: string;
    greeting?: string;
  };
  ai?: Record<string, unknown>;
  booking?: {
    mode?: string;
    ai_discovery?: boolean;
    require_auth?: boolean;
    verification_mode?: "sms" | "email" | "sms_or_email" | "none";
    max_slots_preview?: number;
    date_horizon_days?: number;
    slot_hold_minutes?: number;
    slot_duration_min?: number;
    lead_time_hours?: number;
    cancellation_policy?: string;
  };
  feature_flags?: Record<string, boolean>;
};

export type WidgetSettingsOut = {
  configuration: WidgetSettingsConfig;
};

export type WidgetSettingsUpdateInput = {
  configuration: Partial<WidgetSettingsConfig>;
};

export type OnboardingChecklist = {
  clinic: boolean;
  location: boolean;
  providers: boolean;
  services: boolean;
  hours: boolean;
  availability: boolean;
};

export type OnboardingCounts = {
  providers: number;
  services: number;
  specialties: number;
  insurance_plans: number;
};

export type OnboardingStatus = {
  ready: boolean;
  checklist: OnboardingChecklist;
  counts: OnboardingCounts;
};

export type Specialty = {
  id: string;
  name: string;
  slug: string;
  description: string;
  is_active: boolean;
  is_deleted: boolean;
  created_at: string;
  updated_at: string;
};

export type SpecialtyInput = {
  name: string;
  slug?: string;
  description?: string;
  is_active?: boolean;
};

export type SpecialtyUpdateInput = Partial<SpecialtyInput>;

export type InsurancePlan = {
  id: string;
  provider_name: string;
  plan_name: string;
  plan_type: string;
  is_accepted: boolean;
  notes: string;
  is_deleted: boolean;
  created_at: string;
  updated_at: string;
};

export type InsurancePlanInput = {
  provider_name: string;
  plan_name?: string;
  plan_type?: string;
  is_accepted?: boolean;
  notes?: string;
};

export type InsurancePlanUpdateInput = Partial<InsurancePlanInput>;

export type User = {
  id: number;
  email: string;
  username: string;
  first_name: string;
  last_name: string;
  role: UserRole;
  is_clinic_owner: boolean;
  email_verified?: boolean;
  email_verified_at?: string | null;
};

export type Tenant = {
  slug: string;
  name: string;
  status: string;
  role?: string;
};

export type StaffTokenResponse = {
  access_token: string;
  refresh_token: string;
  token_type?: string;
  expires_in_minutes: number;
  user: User;
  clinic: Clinic | null;
  tenant?: string | null;
  tenants?: Tenant[];
};

export type MeResponse = {
  user: User;
  clinic: Clinic | null;
  tenant?: string | null;
  tenants?: Tenant[];
  can_exit_clinic?: boolean;
};

export type StaffLoginInput = {
  email: string;
  password: string;
  clinic_slug?: string | null;
  remember?: boolean;
};

export type StaffRegisterInput = {
  email: string;
  password: string;
  first_name?: string;
  last_name?: string;
};

export type AcceptInviteInput = {
  token: string;
  password: string;
};

export type MessageOut = {
  message?: string;
  detail?: string;
};

export type Paginated<T> = {
  count: number;
  results: T[];
};

export type Patient = {
  id: string;
  phone: string;
  email: string;
  first_name: string;
  last_name: string;
  full_name: string;
  date_of_birth: string | null;
  preferred_language: string;
  is_verified: boolean;
  created_at: string;
  updated_at: string;
};

export type PatientInput = {
  phone: string;
  first_name: string;
  last_name: string;
  email?: string;
  date_of_birth?: string | null;
  preferred_language?: string;
  is_verified?: boolean;
};

export type PatientUpdateInput = Partial<PatientInput>;

export type Doctor = {
  id: string;
  full_name: string;
  title: string;
  bio: string;
  photo_url: string;
  languages: string[];
  is_active: boolean;
  is_accepting_patients: boolean;
  is_deleted: boolean;
  specialty_ids: string[];
  service_ids: string[];
  created_at: string;
  updated_at: string;
};

export type DoctorInput = {
  full_name: string;
  title?: string;
  bio?: string;
  photo_url?: string;
  languages?: string[] | null;
  is_active?: boolean;
  is_accepting_patients?: boolean;
  specialty_ids?: string[];
  service_ids?: string[];
};

export type DoctorUpdateInput = Partial<DoctorInput>;

export type Service = {
  id: string;
  name: string;
  description: string;
  code?: string;
  category?: string;
  duration_min: number;
  price_cents: number | null;
  is_active: boolean;
  is_deleted: boolean;
  metadata?: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

export type ServiceInput = {
  name: string;
  description?: string;
  code?: string;
  category?: string;
  duration_min?: number;
  price_cents?: number | null;
  is_active?: boolean;
  metadata?: Record<string, unknown>;
};

export type ServiceUpdateInput = Partial<ServiceInput>;

export type AppointmentStatus =
  | "pending"
  | "confirmed"
  | "cancelled"
  | "completed"
  | "no_show"
  | "rescheduled";

export type AppointmentSource =
  | "chatbot"
  | "admin"
  | "phone"
  | "walk_in"
  | "import";

export type Appointment = {
  id: string;
  doctor_id: string;
  doctor_name: string;
  patient_id: string;
  patient_name: string;
  service_id: string | null;
  service_name: string | null;
  insurance_plan_id: string | null;
  insurance_name: string | null;
  start_time: string;
  end_time: string;
  status: AppointmentStatus | string;
  confirmation_code: string;
  notes: string;
  source: AppointmentSource | string;
  created_at: string;
  updated_at: string;
};

export type AppointmentInput = {
  doctor_id: string;
  patient_id: string;
  start_time: string;
  end_time: string;
  service_id?: string | null;
  insurance_plan_id?: string | null;
  status?: string;
  notes?: string;
  source?: string;
  confirmation_code?: string | null;
};

export type AppointmentUpdateInput = Partial<AppointmentInput>;

export type DocumentStatus =
  | "pending"
  | "processing"
  | "chunked"
  | "indexed"
  | "failed"
  | "cancelled";

export type ProcessingStage =
  | "queued"
  | "uploading"
  | "extracting"
  | "chunking"
  | "embedding"
  | "storing"
  | "completed"
  | "failed"
  | "cancelled";

export type KnowledgeDocument = {
  id: string;
  title: string;
  file_name: string;
  file_type: string;
  file_size_bytes: number | null;
  status: DocumentStatus;
  processing_stage: ProcessingStage | string;
  chunk_count: number;
  error_message: string;
  routing_summary?: string;
  routing_keywords?: string[];
  uploaded_by_name?: string | null;
  uploaded_by_email?: string | null;
  processing_started_at?: string | null;
  processing_finished_at?: string | null;
  created_at: string;
  updated_at: string;
};

export type DocumentUpdateInput = {
  title?: string;
  routing_summary?: string;
  routing_keywords?: string[];
};

export type DocumentChunk = {
  id: string;
  chunk_number: number;
  content: string;
  heading: string;
  page_start: number | null;
  page_end: number | null;
  page_number: number | null;
  estimated_token_count: number | null;
  chunk_type: "paragraph" | "list" | "heading" | "mixed";
  has_embedding: boolean;
  embedding_model: string;
  created_at: string;
};

/* ─── Spreadsheet data import (onboarding bulk-import) ────────────────── */

export type ImportRecordType = "providers" | "services" | "specialties";

export type ImportJobStatus =
  | "uploaded"
  | "parsing"
  | "mapped"
  | "validated"
  | "reviewed"
  | "committed"
  | "failed";

export type ImportRecordStatus =
  | "needs_review"
  | "ready"
  | "duplicate"
  | "approved"
  | "rejected"
  | "committed";

export type ImportColumnMapping = Record<
  string,
  { target: string | null; confidence: number; reason: string }
>;

export type ImportJobCounts = {
  needs_review: number;
  ready: number;
  duplicate: number;
  approved: number;
  rejected: number;
  committed: number;
};

export type ImportJob = {
  id: string;
  record_type: ImportRecordType;
  status: ImportJobStatus;
  file_name: string;
  file_type: string;
  file_size_bytes: number | null;
  column_mapping: ImportColumnMapping;
  total_row_count: number;
  error_message: string;
  metadata: { mapping_source?: "llm" | "heuristic_fallback" } & Record<string, unknown>;
  counts: ImportJobCounts;
  committed_at: string | null;
  created_at: string;
  updated_at: string;
};

export type ImportCanonicalField = {
  source: string;
  value: unknown;
  confidence: number;
  reason: string;
};

export type ImportValidationError = { field: string; message: string };

export type ImportDuplicateMatch = {
  model: string;
  id: string | null;
  row_number: number | null;
  similarity: number;
  label: string;
};

export type ImportRecord = {
  id: string;
  row_number: number;
  raw_data: Record<string, string>;
  canonical_data: Record<string, ImportCanonicalField>;
  status: ImportRecordStatus;
  validation_errors: ImportValidationError[];
  duplicate_match: ImportDuplicateMatch | null;
  created_entity_type: string;
  created_entity_id: string | null;
  created_at: string;
  updated_at: string;
};

export type ImportMappingUpdateInput = {
  mapping: Record<string, string | null>;
};

export type ImportRecordUpdateInput = {
  values: Record<string, unknown>;
};

export type ImportCommitOut = {
  job: ImportJob;
  created_count: number;
};

export type ImportBulkApproveOut = {
  approved_count: number;
  skipped_count: number;
};

export type ChatTimings = {
  nlu_ms: number;
  decision_ms: number;
  sql_ms: number;
  vector_ms: number;
  llm_ms: number;
  fast_path_ms: number;
  total_ms: number;
};

export type ChatMessageResponse = {
  response: string;
  route: string;
  intent: string;
  confidence: number;
  needs_sql: boolean;
  needs_vector: boolean;
  needs_llm: boolean;
  safety_message: string | null;
  timings: ChatTimings;
  meta: Record<string, unknown>;
};

export type ChatMessageInput = {
  message: string;
  session_token?: string | null;
};

export type WidgetConfig = {
  clinic_slug: string;
  clinic_name: string;
  phone: string;
  configuration: {
    widget?: {
      primary_color?: string;
      position?: string;
      greeting?: string;
    };
    booking?: {
      require_auth?: boolean;
      verification_mode?: "sms" | "email" | "sms_or_email" | "none";
      slot_duration_min?: number;
      mode?: "doctor_first" | "specialty_first" | "general";
    };
    feature_flags?: Record<string, boolean>;
  };
};

export type WidgetGuestChatInput = {
  clinic_slug: string;
  message: string;
  session_token?: string | null;
};

export type MarketingChatInput = {
  message: string;
};

export type BookingSpecialty = {
  id: string;
  name: string;
  slug?: string;
  description?: string;
  doctor_count?: number;
  plain_label?: string;
};

export type BookingDoctor = {
  id: string;
  name: string;
  title?: string;
  bio?: string;
  photo_url?: string;
  languages?: string[];
  specialties?: string[];
  next_available?: {
    id?: string;
    label?: string;
    start?: string;
    date?: string;
    time?: string;
  } | null;
};

export type BookingSlot = {
  id: string;
  label: string;
  start: string;
  end?: string;
  doctor?: string;
  doctor_id?: string;
  time?: string;
  date?: string;
  day_label?: string;
};

export type BookingDateDensity = "plenty" | "few" | "almost_full" | "closed";

export type BookingDateOption = {
  date: string;
  label: string;
  is_today?: boolean;
  density?: BookingDateDensity;
  reason?: string;
};

export type BookingStepPayload = {
  booking_id: string;
  session_token?: string;
  mode: string;
  step: string;
  progress: { current: number; total: number };
  reason?: string;
  guidance?: string;
  suggested_specialties?: BookingSpecialty[];
  specialty_chip?: { id: string; name: string } | null;
  options: Record<string, unknown>;
  hold?: { expires_at: string } | null;
  /** Set when a select_hero action's slot was taken between render and tap. */
  stale_hero?: boolean;
  confirmation?: {
    confirmation_code?: string;
    appointment_id?: string;
    slot_summary?: string;
    doctor_name?: string;
    date?: string;
    start?: string;
    first_name?: string;
    last_name?: string;
  } | null;
};

export type BookingStartInput = {
  clinic_slug: string;
  session_token?: string | null;
  message?: string;
  reason?: string;
  specialty_id?: string | null;
  specialty_name?: string | null;
  doctor_id?: string | null;
  doctor_name?: string | null;
  service_id?: string | null;
  service_name?: string | null;
  slot_start?: string | null;
  slot_end?: string | null;
  insurance_name?: string | null;
  /** Reschedule flow: the appointment this new booking replaces. It stays
   * live until BookingService.confirm atomically swaps it for the new one. */
  replaces_appointment_id?: string | null;
};

export type BookingStepInput = {
  clinic_slug: string;
  session_token: string;
  booking_id: string;
  action: string;
  value?: Record<string, unknown>;
};

export type BookingConfirmInput = {
  clinic_slug: string;
  session_token: string;
  booking_id: string;
  otp_code: string;
};

export type OTPSendInput = {
  clinic_slug: string;
  phone?: string;
  email?: string;
  channel?: string | null;
  session_token?: string | null;
  first_name?: string | null;
  last_name?: string | null;
};

export type OTPSendResponse = {
  message: string;
  session_token: string;
  patient_id: string | number;
  expires_in_minutes: number;
  channel?: string;
  debug_code?: string | null;
};

export type OTPVerifyInput = {
  clinic_slug: string;
  phone?: string;
  email?: string;
  code: string;
  session_token?: string | null;
  first_name?: string | null;
  last_name?: string | null;
};

export type PatientAuth = {
  id: string;
  phone: string;
  first_name: string;
  last_name: string;
  is_verified: boolean;
  verified_at?: string | null;
};

export type PatientTokenResponse = {
  access_token: string;
  token_type?: string;
  expires_in_minutes: number;
  patient: PatientAuth;
  clinic: Clinic;
  session_token?: string | null;
};

export type ListParams = {
  search?: string;
  limit?: number;
  offset?: number;
  is_active?: boolean;
  include_deleted?: boolean;
};

/* ─── Billing (Paddle) ──────────────────────────────────────── */

export type SubscriptionStatus =
  | "incomplete"
  | "trialing"
  | "active"
  | "past_due"
  | "paused"
  | "canceled";

export type Plan = {
  id: string;
  slug: string;
  name: string;
  billing_interval: "month" | "year";
  display_price_cents: number | null;
  display_currency: string;
};

export type Subscription = {
  status: SubscriptionStatus;
  plan: Plan | null;
  current_period_start: string | null;
  current_period_end: string | null;
  cancel_at_period_end: boolean;
  canceled_at: string | null;
  has_access: boolean;
};

export type CheckoutInput = {
  plan_slug: string;
};

export type CheckoutResponse = {
  paddle_environment: "sandbox" | "live";
  paddle_price_id: string;
  paddle_customer_id: string;
};

export type CancelSubscriptionInput = {
  at_period_end: boolean;
};

export type ChangePlanInput = {
  plan_slug: string;
};

/* ─── Clinic applications (Get Started intake) ─────────────────── */

export type ClinicApplicationStatus =
  | "pending"
  | "reviewing"
  | "approved"
  | "rejected"
  | "converted";

export type ClinicApplicationInput = {
  clinic_name: string;
  owner_name: string;
  work_email: string;
  phone?: string;
  website?: string;
  num_doctors?: number | null;
  current_scheduling_system?: string;
  plan_slug: string;
  notes?: string;
};

export type ClinicApplicationSubmitResponse = {
  id: string;
  status: ClinicApplicationStatus;
  created_at: string;
};

export type ClinicApplication = {
  id: string;
  clinic_name: string;
  owner_name: string;
  work_email: string;
  phone: string;
  website: string;
  num_doctors: number | null;
  current_scheduling_system: string;
  notes: string;
  plan_slug: string;
  status: ClinicApplicationStatus;
  rejection_reason: string;
  converted_clinic_id: string | null;
  created_at: string;
};

export type RejectApplicationInput = {
  reason?: string;
};

export type ApplicationActionResponse = {
  application: ClinicApplication;
  clinic: Clinic | null;
};

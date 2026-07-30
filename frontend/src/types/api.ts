/** Shared API domain types — aligned with Synapse OpenAPI schemas. */

export type UserRole = "SUPER_ADMIN" | "CLINIC_ADMIN" | "STAFF";

export type Clinic = {
  id: string;
  slug: string;
  name: string;
  timezone: string;
};

export type User = {
  id: number;
  email: string;
  username: string;
  first_name: string;
  last_name: string;
  role: UserRole;
  is_clinic_owner: boolean;
};

export type StaffTokenResponse = {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in_minutes: number;
  user: User;
  clinic: Clinic | null;
};

export type MeResponse = {
  user: User;
  clinic: Clinic | null;
};

export type StaffLoginInput = {
  email: string;
  password: string;
  clinic_slug: string;
};

export type Paginated<T> = {
  count: number;
  results: T[];
};

export type MessageOut = {
  detail: string;
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
  duration_min: number;
  price_cents: number | null;
  is_active: boolean;
  is_deleted: boolean;
  created_at: string;
  updated_at: string;
};

export type ServiceInput = {
  name: string;
  description?: string;
  duration_min?: number;
  price_cents?: number | null;
  is_active?: boolean;
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
  | "failed";

export type KnowledgeDocument = {
  id: string;
  title: string;
  file_name: string;
  file_type: string;
  file_size_bytes: number | null;
  status: DocumentStatus;
  chunk_count: number;
  error_message: string;
  created_at: string;
  updated_at: string;
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
  confirmation?: {
    confirmation_code?: string;
    appointment_id?: string;
    slot_summary?: string;
    doctor_name?: string;
    date?: string;
    start?: string;
  } | null;
};

export type BookingStartInput = {
  clinic_slug: string;
  session_token?: string | null;
  message?: string;
  reason?: string;
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
  phone: string;
  session_token?: string | null;
  first_name?: string | null;
  last_name?: string | null;
};

export type OTPSendResponse = {
  message: string;
  session_token: string;
  patient_id: string;
  expires_in_minutes: number;
  debug_code?: string | null;
};

export type OTPVerifyInput = {
  clinic_slug: string;
  phone: string;
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
  token_type: string;
  expires_in_minutes: number;
  patient: PatientAuth;
  clinic: Clinic;
};

export type ListParams = {
  search?: string;
  limit?: number;
  offset?: number;
  is_active?: boolean;
  include_deleted?: boolean;
};

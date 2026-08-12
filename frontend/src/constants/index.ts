export const STORAGE_KEYS = {
  accessToken: "synapse_staff_access",
  refreshToken: "synapse_staff_refresh",
  rememberMe: "synapse_remember_me",
  activeTenant: "synapse_active_tenant",
  patientAccessToken: "synapse_patient_access",
  chatSession: "synapse_chat_session",
} as const;

export const APP_NAME = "Synapse";

export const NAV_MARKETING = [
  { href: "/features", label: "Features" },
  { href: "/solutions", label: "Solutions" },
  { href: "/pricing", label: "Pricing" },
  { href: "/developers", label: "Developers" },
  { href: "/about", label: "About" },
  { href: "/blog", label: "Blog" },
] as const;

export const DASHBOARD_NAV = [
  { href: "/dashboard", label: "Dashboard", icon: "LayoutDashboard" },
  { href: "/dashboard/clinic", label: "Clinic", icon: "Building2" },
  { href: "/dashboard/doctors", label: "Doctors", icon: "Stethoscope" },
  { href: "/dashboard/services", label: "Services", icon: "BriefcaseMedical" },
  { href: "/dashboard/specialties", label: "Specialties", icon: "Tags" },
  { href: "/dashboard/insurance", label: "Insurance", icon: "Shield" },
  { href: "/dashboard/business-hours", label: "Business Hours", icon: "Clock" },
  { href: "/dashboard/appointments", label: "Appointments", icon: "Calendar" },
  { href: "/dashboard/patients", label: "Patients", icon: "Users" },
  { href: "/dashboard/knowledge", label: "Knowledge Base", icon: "BookOpen" },
  { href: "/dashboard/chatbot", label: "Chatbot", icon: "Bot" },
  { href: "/dashboard/analytics", label: "Analytics", icon: "BarChart3" },
  { href: "/dashboard/billing", label: "Billing", icon: "CreditCard" },
  { href: "/dashboard/settings", label: "Settings", icon: "Settings" },
  { href: "/dashboard/profile", label: "Profile", icon: "User" },
] as const;

/** Super Admin platform portal — shown when no clinic tenant is active. */
export const PLATFORM_NAV = [
  { href: "/dashboard/platform", label: "Overview", icon: "LayoutDashboard" },
  {
    href: "/dashboard/platform/applications",
    label: "Applications",
    icon: "ClipboardList",
  },
  { href: "/dashboard/platform/clinics", label: "Clinics", icon: "Building2" },
  { href: "/dashboard/platform/users", label: "Users", icon: "Users" },
  {
    href: "/dashboard/platform/subscriptions",
    label: "Subscriptions",
    icon: "CreditCard",
  },
  { href: "/dashboard/platform/ai-usage", label: "AI Usage", icon: "BarChart3" },
  {
    href: "/dashboard/platform/documents",
    label: "Documents",
    icon: "BookOpen",
  },
  {
    href: "/dashboard/platform/ai-monitoring",
    label: "AI Monitoring",
    icon: "Bot",
  },
  {
    href: "/dashboard/platform/audit",
    label: "Audit Logs",
    icon: "Shield",
  },
  {
    href: "/dashboard/platform/settings",
    label: "Platform Settings",
    icon: "Settings",
  },
  { href: "/dashboard/profile", label: "Profile", icon: "User" },
] as const;


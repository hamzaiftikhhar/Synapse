export const STORAGE_KEYS = {
  accessToken: "synapse_staff_access",
  refreshToken: "synapse_staff_refresh",
  rememberMe: "synapse_remember_me",
  activeTenant: "synapse_active_tenant",
  patientAccessToken: "synapse_patient_access",
  chatSession: "synapse_chat_session",
  // Per-clinic, like chatSession — localStorage (not sessionStorage) since
  // this is the one identifier meant to survive a browser restart. Never
  // invented client-side: only ever set from a value the backend returned.
  chatVisitor: "synapse_visitor_id",
  explicitLogout: "synapse_explicit_logout",
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

export type DashboardNavItem = {
  href: string;
  label: string;
  icon: string;
};

export type DashboardNavGroup = {
  id: string;
  label: string;
  /** Collapsed by default unless the active route is inside this group. */
  collapsible?: boolean;
  defaultOpen?: boolean;
  items: DashboardNavItem[];
};

/**
 * Clinic portal IA — grouped by job, not by module dump.
 *
 * Profile is intentionally absent: it is a person account, not a clinic
 * destination (Stripe / Linear / GitHub). Reach it from the avatar menu.
 * Clinic identity lives under Workspace; booking/widget live in Settings.
 */
export const DASHBOARD_NAV: DashboardNavGroup[] = [
  {
    id: "overview",
    label: "Overview",
    items: [
      { href: "/dashboard", label: "Dashboard", icon: "LayoutDashboard" },
      { href: "/dashboard/analytics", label: "Analytics", icon: "BarChart3" },
    ],
  },
  {
    id: "front-desk",
    label: "Front desk",
    items: [
      { href: "/dashboard/appointments", label: "Appointments", icon: "Calendar" },
      { href: "/dashboard/patients", label: "Patients", icon: "Users" },
      { href: "/dashboard/conversations", label: "Conversations", icon: "MessageSquare" },
    ],
  },
  {
    id: "practice",
    label: "Practice",
    collapsible: true,
    defaultOpen: true,
    items: [
      { href: "/dashboard/doctors", label: "Doctors", icon: "Stethoscope" },
      { href: "/dashboard/services", label: "Services", icon: "BriefcaseMedical" },
      { href: "/dashboard/specialties", label: "Specialties", icon: "Tags" },
      { href: "/dashboard/insurance", label: "Insurance", icon: "Shield" },
    ],
  },
  {
    id: "assistant",
    label: "Assistant",
    items: [
      { href: "/dashboard/chatbot", label: "Chatbot", icon: "Bot" },
      { href: "/dashboard/knowledge", label: "Knowledge base", icon: "BookOpen" },
    ],
  },
  {
    id: "workspace",
    label: "Workspace",
    collapsible: true,
    defaultOpen: false,
    items: [
      { href: "/dashboard/clinic", label: "Clinic profile", icon: "Building2" },
      { href: "/dashboard/business-hours", label: "Business hours", icon: "Clock" },
      { href: "/dashboard/billing", label: "Billing", icon: "CreditCard" },
      { href: "/dashboard/settings", label: "Settings", icon: "Settings" },
    ],
  },
];

/** Super Admin platform portal — shown when no clinic tenant is active. */
export const PLATFORM_NAV: DashboardNavGroup[] = [
  {
    id: "overview",
    label: "Overview",
    items: [{ href: "/dashboard/platform", label: "Home", icon: "LayoutDashboard" }],
  },
  {
    id: "clinics",
    label: "Clinics",
    items: [
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
    ],
  },
  {
    id: "intelligence",
    label: "Intelligence",
    collapsible: true,
    defaultOpen: true,
    items: [
      { href: "/dashboard/platform/ai-usage", label: "AI usage", icon: "BarChart3" },
      {
        href: "/dashboard/platform/ai-monitoring",
        label: "AI monitoring",
        icon: "Bot",
      },
      {
        href: "/dashboard/platform/documents",
        label: "Documents",
        icon: "BookOpen",
      },
    ],
  },
  {
    id: "admin",
    label: "Admin",
    collapsible: true,
    defaultOpen: false,
    items: [
      { href: "/dashboard/platform/audit", label: "Audit logs", icon: "Shield" },
      {
        href: "/dashboard/platform/settings",
        label: "Platform settings",
        icon: "Settings",
      },
    ],
  },
];

const ROOT_HREFS = new Set(["/dashboard", "/dashboard/platform"]);

export function isNavHrefActive(href: string, pathname: string): boolean {
  if (ROOT_HREFS.has(href)) return pathname === href;
  return pathname === href || pathname.startsWith(`${href}/`);
}

export function navGroupContainsPath(
  group: DashboardNavGroup,
  pathname: string
): boolean {
  return group.items.some((item) => isNavHrefActive(item.href, pathname));
}


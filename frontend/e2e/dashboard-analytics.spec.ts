import { execSync } from "node:child_process";
import { expect, test } from "@playwright/test";

const REPO_ROOT = "/Users/apple/development/Synapse";
const PYTHON = `${REPO_ROOT}/.venv/bin/python`;

function djangoShell(code: string): string {
  const out = execSync(
    `${PYTHON} manage.py shell -c '${code.replace(/'/g, "'\\''")}'`,
    { cwd: REPO_ROOT, encoding: "utf-8" }
  );
  const lines = out.trim().split("\n");
  return lines[lines.length - 1];
}

function seedClinicAdminToken(clinicSlug: string): string {
  return djangoShell(`
from apps.accounts.models import User, UserRole, ClinicStaff
from apps.api.auth.jwt import create_staff_access_token
from apps.clinics.models import Clinic, ClinicStatus
clinic, _ = Clinic.objects.get_or_create(
    slug="${clinicSlug}",
    defaults=dict(name="E2E Analytics Clinic", email="e2e-analytics@test.com",
                  phone="+12125550911", timezone="America/New_York", status=ClinicStatus.ACTIVE),
)
email = "e2e-analytics-owner-${clinicSlug}@test.com"
user = User.objects.filter(email=email).first()
if not user:
    user = User.objects.create_user(
        username="e2e-analytics-owner-${clinicSlug}", email=email, password="Sup3rSecret!",
        role=UserRole.CLINIC_ADMIN, is_clinic_owner=True, is_active=True,
    )
ClinicStaff.objects.get_or_create(user=user, clinic=clinic, defaults=dict(is_active=True))
token = create_staff_access_token(user_id=user.id, role=user.role, tenant=clinic.slug, clinic_id=clinic.id)
print(token)
`);
}

async function injectStaffAuth(page: import("@playwright/test").Page, token: string) {
  await page.addInitScript((t) => {
    localStorage.setItem("synapse_staff_access", t);
    localStorage.setItem("synapse_staff_refresh", t);
    localStorage.setItem("synapse_remember_me", "1");
  }, token);
}

test.describe("Dashboard analytics — overview and insights", () => {
  const clinicSlug = `e2e-analytics-${Date.now()}`;
  let token: string;

  test.beforeAll(() => {
    token = seedClinicAdminToken(clinicSlug);
  });

  test.afterAll(() => {
    // This spec never creates an Appointment (only Clinic/User/ClinicStaff,
    // all of which cascade-delete via the clinic FK), so no need to clear
    // Appointment.doctor/patient PROTECT rows first.
    djangoShell(`
from apps.clinics.models import Clinic
c = Clinic.objects.filter(slug="${clinicSlug}").first()
if c:
    c.delete()
print("ok")
`);
  });

  test("empty clinic dashboard shows KPIs, empty charts, and date range", async ({
    page,
  }) => {
    await injectStaffAuth(page, token);
    await page.goto("/dashboard");

    await expect(page.getByText("Here's what's happening with your clinic.")).toBeVisible({
      timeout: 15_000,
    });
    await expect(page.getByText("Conversations", { exact: true }).first()).toBeVisible();
    await expect(page.getByText("Completed appointments")).toBeVisible();
    await expect(page.getByRole("tab", { name: "30 days" })).toBeVisible();
    await expect(page.getByText("No activity yet")).toBeVisible();
    await expect(page.getByText("Recent conversations")).toBeVisible();
    await expect(page.getByRole("heading", { name: "Bookings" })).toBeVisible();
    await expect(page.getByText("Upcoming appointments")).toBeVisible();
    await expect(page.getByText("No upcoming visits")).toBeVisible();

    await page.getByRole("tab", { name: "7 days" }).click();
    // Base UI's Tab marks the active tab via `aria-selected` / a boolean
    // `data-active` presence attribute, not Radix's `data-state="active"` —
    // this project uses @base-ui/react/tabs (see src/components/ui/tabs.tsx),
    // so asserting `data-state` here never passes regardless of behavior.
    await expect(page.getByRole("tab", { name: "7 days" })).toHaveAttribute(
      "aria-selected",
      "true"
    );
  });

  test("analytics page renders section headings and empty states", async ({ page }) => {
    await injectStaffAuth(page, token);
    await page.goto("/dashboard/analytics");

    await expect(page.getByRole("heading", { name: "Analytics" })).toBeVisible({
      timeout: 15_000,
    });
    await expect(page.getByText("Understand how patients interact with Synapse.")).toBeVisible();
    await expect(page.getByText("Appointments today")).toBeVisible();
    await expect(page.getByText("Patients with upcoming visits")).toBeVisible();
    await expect(page.getByText("Conversation volume")).toBeVisible();
    await expect(page.getByText("No conversations yet")).toBeVisible();
    await expect(page.getByRole("heading", { name: "Appointments", exact: true })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Patients", exact: true })).toBeVisible();
    await expect(page.getByRole("heading", { name: "AI usage" })).toBeVisible();
    await expect(page.getByText("Patients by appointment count")).toHaveCount(0);
    await expect(page.getByText("Appointments by provider")).toHaveCount(0);
    await expect(page.getByText("Provider performance")).toHaveCount(0);
  });

  test("failed overview request shows a retryable error", async ({ page }) => {
    await page.route("**/api/v1/analytics/overview**", (route) =>
      route.fulfill({ status: 500, contentType: "application/json", body: "{}" })
    );
    await injectStaffAuth(page, token);
    await page.goto("/dashboard");

    await expect(page.getByText("Unable to load analytics").first()).toBeVisible({
      timeout: 15_000,
    });
    await expect(page.getByRole("button", { name: "Try again" }).first()).toBeVisible();
  });
});

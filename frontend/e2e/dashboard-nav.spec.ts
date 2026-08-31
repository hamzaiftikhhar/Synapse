import { execSync } from "node:child_process";
import { expect, test } from "@playwright/test";

const REPO_ROOT = "/Users/apple/development/Synapse";

function djangoShell(code: string): string {
  const out = execSync(
    `python manage.py shell -c '${code.replace(/'/g, "'\\''")}'`,
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
    defaults=dict(name="E2E Nav Clinic", email="e2e-nav@test.com",
                  phone="+12125550921", timezone="America/New_York", status=ClinicStatus.ACTIVE),
)
email = "e2e-nav-owner-${clinicSlug}@test.com"
user = User.objects.filter(email=email).first()
if not user:
    user = User.objects.create_user(
        username="e2e-nav-owner-${clinicSlug}", email=email, password="Sup3rSecret!",
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

test.describe("Dashboard sidebar information architecture", () => {
  const clinicSlug = `e2e-nav-${Date.now()}`;
  let token: string;

  test.beforeAll(() => {
    token = seedClinicAdminToken(clinicSlug);
  });

  test.afterAll(() => {
    djangoShell(`
from apps.clinics.models import Clinic
c = Clinic.objects.filter(slug="${clinicSlug}").first()
if c:
    c.delete()
print("ok")
`);
  });

  test("groups daily work first and keeps profile out of the sidebar", async ({
    page,
  }) => {
    await injectStaffAuth(page, token);
    await page.goto("/dashboard");

    const nav = page.getByRole("navigation", { name: "Clinic portal" });
    await expect(nav).toBeVisible({ timeout: 15_000 });

    await expect(nav.getByText("Overview", { exact: true })).toBeVisible();
    await expect(nav.getByText("Front desk", { exact: true })).toBeVisible();
    await expect(nav.getByText("Practice", { exact: true })).toBeVisible();
    await expect(nav.getByText("Assistant", { exact: true })).toBeVisible();
    await expect(nav.getByRole("button", { name: "Workspace" })).toBeVisible();

    await expect(nav.getByRole("link", { name: "Dashboard" })).toBeVisible();
    await expect(nav.getByRole("link", { name: "Appointments" })).toBeVisible();
    await expect(nav.getByRole("link", { name: "Chatbot" })).toBeVisible();

    // Person account is avatar-only — not a clinic destination.
    await expect(nav.getByRole("link", { name: "Your account" })).toHaveCount(0);
    await expect(nav.getByRole("link", { name: "Profile" })).toHaveCount(0);

    // Workspace starts collapsed on Overview.
    await expect(nav.getByRole("link", { name: "Clinic profile" })).toBeHidden();
    await nav.getByRole("button", { name: "Workspace" }).click();
    await expect(nav.getByRole("link", { name: "Clinic profile" })).toBeVisible();
    await expect(nav.getByRole("link", { name: "Settings" })).toBeVisible();

    await page.getByRole("button", { name: "Account menu" }).click();
    await expect(
      page.getByRole("menuitem", { name: "Your account" })
    ).toBeVisible();
  });

  test("clinic, settings, and account pages own distinct jobs with related links", async ({
    page,
  }) => {
    await injectStaffAuth(page, token);
    await page.goto("/dashboard/clinic");

    const nav = page.getByRole("navigation", { name: "Clinic portal" });
    await expect(nav.getByRole("link", { name: "Clinic profile" })).toBeVisible({
      timeout: 15_000,
    });
    await expect(page.getByRole("heading", { name: "Clinic profile" })).toBeVisible();
    await expect(page.getByText("Identity", { exact: true })).toBeVisible();
    await expect(page.getByText("Contact", { exact: true })).toBeVisible();
    await expect(page.getByText("Address", { exact: true })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Related" })).toBeVisible();

    await page.goto("/dashboard/settings");
    await expect(page.getByRole("heading", { name: "Settings" })).toBeVisible({
      timeout: 15_000,
    });
    const settingsNav = page.getByRole("navigation", { name: "Settings sections" });
    await expect(settingsNav.getByRole("button", { name: "Workspace" })).toBeVisible();
    await expect(settingsNav.getByRole("button", { name: "Booking" })).toBeVisible();
    await expect(settingsNav.getByRole("button", { name: "Widget" })).toBeVisible();
    await settingsNav.getByRole("button", { name: "Booking" }).click();
    await expect(page).toHaveURL(/tab=booking/);
    await expect(page.getByText("Booking lead time (hours)")).toBeVisible();

    await page.goto("/dashboard/profile");
    await expect(page.getByRole("heading", { name: "Your account" })).toBeVisible({
      timeout: 15_000,
    });
    await expect(
      page.getByText("Clinic name and address are on Clinic profile")
    ).toBeVisible();
  });

  test("mobile drawer is the dark sidebar with grouped nav", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await injectStaffAuth(page, token);
    await page.goto("/dashboard");

    await expect(
      page.getByText("Here's what's happening with your clinic.")
    ).toBeVisible({ timeout: 15_000 });

    await page.getByRole("button", { name: "Open menu" }).click();
    const nav = page.getByRole("navigation", { name: "Clinic portal" });
    await expect(nav).toBeVisible();
    await expect(nav.getByText("Front desk", { exact: true })).toBeVisible();

    const sidebar = page.getByTestId("dashboard-sidebar");
    const box = await sidebar.boundingBox();
    expect(box).toBeTruthy();
    expect(box!.width).toBeGreaterThan(200);
    expect(box!.width).toBeLessThanOrEqual(280);
  });
});

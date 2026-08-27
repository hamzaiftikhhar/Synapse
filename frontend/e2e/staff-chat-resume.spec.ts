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

function seedClinicAdminToken(clinicSlug: string, emailPrefix: string): string {
  return djangoShell(`
from apps.accounts.models import User, UserRole, ClinicStaff
from apps.api.auth.jwt import create_staff_access_token
from apps.clinics.models import Clinic, ClinicStatus
clinic, _ = Clinic.objects.get_or_create(
    slug="${clinicSlug}",
    defaults=dict(name="E2E Resume Clinic", email="e2e-resume@test.com",
                  phone="+12125550911", timezone="America/New_York", status=ClinicStatus.ACTIVE),
)
email = "${emailPrefix}-${clinicSlug}@test.com"
user = User.objects.filter(email=email).first()
if not user:
    user = User.objects.create_user(
        username="${emailPrefix}-${clinicSlug}", email=email, password="Sup3rSecret!",
        role=UserRole.CLINIC_ADMIN, is_clinic_owner=True, is_active=True,
    )
ClinicStaff.objects.get_or_create(user=user, clinic=clinic, defaults=dict(is_active=True))
token = create_staff_access_token(user_id=user.id, role=user.role, tenant=clinic.slug, clinic_id=clinic.id)
print(token)
`);
}

function seedSuperAdminTokens(clinicSlugA: string, clinicSlugB: string): { tokenA: string; tokenB: string } {
  const out = djangoShell(`
from apps.accounts.models import User, UserRole
from apps.api.auth.jwt import create_staff_access_token
from apps.clinics.models import Clinic, ClinicStatus
clinic_a, _ = Clinic.objects.get_or_create(
    slug="${clinicSlugA}",
    defaults=dict(name="E2E Resume Clinic A", email="e2e-resume-a@test.com",
                  phone="+12125550911", timezone="America/New_York", status=ClinicStatus.ACTIVE),
)
clinic_b, _ = Clinic.objects.get_or_create(
    slug="${clinicSlugB}",
    defaults=dict(name="E2E Resume Clinic B", email="e2e-resume-b@test.com",
                  phone="+12125550911", timezone="America/New_York", status=ClinicStatus.ACTIVE),
)
email = "e2e-resume-sa-${clinicSlugA}@test.com"
sa = User.objects.filter(email=email).first()
if not sa:
    sa = User.objects.create_user(
        username="e2e-resume-sa-${clinicSlugA}", email=email, password="Sup3rSecret!",
        role=UserRole.SUPER_ADMIN, is_active=True,
    )
token_a = create_staff_access_token(user_id=sa.id, role=sa.role, tenant=clinic_a.slug, clinic_id=clinic_a.id)
token_b = create_staff_access_token(user_id=sa.id, role=sa.role, tenant=clinic_b.slug, clinic_id=clinic_b.id)
print(token_a + "|" + token_b)
`);
  const [tokenA, tokenB] = out.split("|");
  return { tokenA, tokenB };
}

function deleteClinic(clinicSlug: string) {
  djangoShell(`
from apps.clinics.models import Clinic
c = Clinic.objects.filter(slug="${clinicSlug}").first()
if c:
    c.delete()
print("ok")
`);
}

function deleteSuperAdmin(clinicSlugA: string) {
  // seedSuperAdminTokens creates this user independent of any clinic (a
  // super admin isn't a ClinicStaff row), so deleting the clinics alone
  // doesn't cascade it away — without this it accumulates one orphaned
  // user per test run, same class of leak the clinic cleanup fixed.
  djangoShell(`
from apps.accounts.models import User
User.objects.filter(email="e2e-resume-sa-${clinicSlugA}@test.com").delete()
print("ok")
`);
}

async function injectStaffAuth(
  page: import("@playwright/test").Page,
  token: string,
  tenant?: string
) {
  await page.addInitScript(
    ({ t, tenant }) => {
      localStorage.setItem("synapse_staff_access", t);
      localStorage.setItem("synapse_staff_refresh", t);
      localStorage.setItem("synapse_remember_me", "1");
      if (tenant) localStorage.setItem("synapse_active_tenant", tenant);
    },
    { t: token, tenant }
  );
}

async function openWidgetAndSend(page: import("@playwright/test").Page, text: string) {
  await page.goto("/dashboard");
  await page.waitForTimeout(2000);
  await page.locator('button[class*="rounded-full"]').last().click();
  await page.waitForTimeout(1000);
  const input = page.getByPlaceholder("Write a message");
  await input.click();
  await input.fill(text);
  await page.getByRole("button", { name: "Send message" }).click();
  await page.waitForTimeout(4000);
}

// Regression coverage for the bug where the dashboard's own staff/QA chat
// widget never remembered a prior conversation on refresh, even though it
// was sitting right there in the staff Conversations tab — see ROADMAP.md's
// staff-widget-resume phase for the full root cause.

test.describe("Staff chat widget — resume after refresh", () => {
  const clinicSlug = `e2e-resume-${Date.now()}`;
  let token: string;

  test.beforeAll(() => {
    token = seedClinicAdminToken(clinicSlug, "e2e-resume-owner");
  });

  test.afterAll(() => {
    deleteClinic(clinicSlug);
  });

  test("a clinic admin's conversation survives a page refresh", async ({ page }) => {
    await injectStaffAuth(page, token, clinicSlug);
    const marker = `resume-marker-${Date.now()}`;
    await openWidgetAndSend(page, marker);

    await page.reload();
    await page.waitForTimeout(2000);
    await page.locator('button[class*="rounded-full"]').last().click();
    await page.waitForTimeout(3000);

    await expect(page.getByText(marker)).toBeVisible({ timeout: 10_000 });
  });
});

test.describe("Staff chat widget — per-clinic isolation for a super admin", () => {
  const clinicSlugA = `e2e-resume-a-${Date.now()}`;
  const clinicSlugB = `e2e-resume-b-${Date.now()}`;
  let tokenA: string;
  let tokenB: string;

  test.beforeAll(() => {
    ({ tokenA, tokenB } = seedSuperAdminTokens(clinicSlugA, clinicSlugB));
  });

  test.afterAll(() => {
    deleteClinic(clinicSlugA);
    deleteClinic(clinicSlugB);
    deleteSuperAdmin(clinicSlugA);
  });

  test("switching clinics resumes a different conversation per clinic, never mixed up", async ({
    page,
  }) => {
    const markerA = `sa-a-${Date.now()}`;
    const markerB = `sa-b-${Date.now()}`;

    await injectStaffAuth(page, tokenA, clinicSlugA);
    await openWidgetAndSend(page, markerA);

    await injectStaffAuth(page, tokenB, clinicSlugB);
    await page.goto("/dashboard");
    await page.waitForTimeout(2000);
    await page.locator('button[class*="rounded-full"]').last().click();
    await page.waitForTimeout(3000);
    await expect(page.getByText(markerA)).not.toBeVisible();

    const input = page.getByPlaceholder("Write a message");
    await input.click();
    await input.fill(markerB);
    await page.getByRole("button", { name: "Send message" }).click();
    await page.waitForTimeout(4000);

    await injectStaffAuth(page, tokenA, clinicSlugA);
    await page.goto("/dashboard");
    await page.waitForTimeout(2000);
    await page.locator('button[class*="rounded-full"]').last().click();
    await page.waitForTimeout(3000);
    await expect(page.getByText(markerA)).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(markerB)).not.toBeVisible();
  });
});

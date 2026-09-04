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

/**
 * Super Admin already entered into clinic A. Switching to clinic B from the
 * workspace switcher must remount the dashboard against B without requiring
 * a second click / soft-nav no-op on /dashboard.
 */
test.describe("Workspace switcher clinic handoff", () => {
  const stamp = Date.now();
  const clinicA = `e2e-ws-a-${stamp}`;
  const clinicB = `e2e-ws-b-${stamp}`;
  let token: string;

  test.beforeAll(() => {
    token = djangoShell(`
from apps.accounts.models import User, UserRole
from apps.api.auth.jwt import create_staff_access_token, create_staff_refresh_token
from apps.clinics.models import Clinic, ClinicStatus
User.objects.filter(email="e2e-ws-super@test.com").delete()
Clinic.objects.filter(slug__in=["${clinicA}", "${clinicB}"]).delete()
a = Clinic.objects.create(
    slug="${clinicA}", name="Alpha Switch Clinic", email="a-${stamp}@test.com",
    phone="+12125550111", timezone="America/New_York", status=ClinicStatus.ACTIVE,
)
b = Clinic.objects.create(
    slug="${clinicB}", name="Beta Switch Clinic", email="b-${stamp}@test.com",
    phone="+12125550112", timezone="America/New_York", status=ClinicStatus.ACTIVE,
)
user = User.objects.create_user(
    username="e2e-ws-super", email="e2e-ws-super@test.com", password="Sup3rSecret!",
    role=UserRole.SUPER_ADMIN, is_active=True, is_staff=True,
)
access = create_staff_access_token(
    user_id=user.id, role=user.role, tenant=a.slug, clinic_id=a.id,
)
refresh = create_staff_refresh_token(
    user_id=user.id, role=user.role, tenant=a.slug, clinic_id=a.id,
)
print(access + "|" + refresh)
`);
  });

  test.afterAll(() => {
    djangoShell(`
from apps.accounts.models import User
from apps.clinics.models import Clinic
User.objects.filter(email="e2e-ws-super@test.com").delete()
Clinic.objects.filter(slug__in=["${clinicA}", "${clinicB}"]).delete()
print("ok")
`);
  });

  test("switching clinics from All clinics flyout remounts the new workspace", async ({
    page,
  }) => {
    const [access, refresh] = token.split("|");
    await page.addInitScript(
      ({ accessToken, refreshToken, tenant }) => {
        localStorage.setItem("synapse_staff_access", accessToken);
        localStorage.setItem("synapse_staff_refresh", refreshToken);
        localStorage.setItem("synapse_remember_me", "1");
        localStorage.setItem("synapse_active_tenant", tenant);
      },
      { accessToken: access, refreshToken: refresh, tenant: clinicA }
    );

    await page.goto("/dashboard");
    const switcher = page.getByRole("button", { name: "Switch workspace" });
    await expect(switcher).toBeVisible({ timeout: 15_000 });
    await expect(switcher).toContainText("Alpha Switch Clinic");

    await switcher.click();
    // Submenu opens on hover/focus — point at All clinics then pick Beta.
    const allClinics = page.getByRole("menuitem", { name: /All clinics/i });
    await expect(allClinics).toBeVisible();
    await allClinics.hover();

    const beta = page.getByRole("menuitem", { name: /Beta Switch Clinic/i });
    await expect(beta).toBeVisible({ timeout: 10_000 });

    // enter-clinic must fire and land on the new clinic without a second
    // dashboard action. Capture the POST so a soft-nav no-op can't hide a
    // failed switch behind a stale header.
    const enterWait = page.waitForResponse(
      (res) =>
        res.url().includes("/auth/enter-clinic") && res.request().method() === "POST"
    );
    await beta.click();
    const enterRes = await enterWait;
    expect(enterRes.ok()).toBeTruthy();

    await expect(page.getByRole("button", { name: "Switch workspace" })).toContainText(
      "Beta Switch Clinic",
      { timeout: 20_000 }
    );
    await expect(page).toHaveURL(/\/dashboard/);
  });
});

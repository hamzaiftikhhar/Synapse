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
    defaults=dict(name="E2E Staff Clinic", email="e2e-staff@test.com",
                  phone="+12125550901", timezone="America/New_York", status=ClinicStatus.ACTIVE),
)
email = "e2e-staff-owner-${clinicSlug}@test.com"
user = User.objects.filter(email=email).first()
if not user:
    user = User.objects.create_user(
        username="e2e-staff-owner-${clinicSlug}", email=email, password="Sup3rSecret!",
        role=UserRole.CLINIC_ADMIN, is_clinic_owner=True, is_active=True,
    )
ClinicStaff.objects.get_or_create(user=user, clinic=clinic, defaults=dict(is_active=True))
token = create_staff_access_token(user_id=user.id, role=user.role, tenant=clinic.slug, clinic_id=clinic.id)
print(token)
`);
}

function seedConversationWithStructuredCard(clinicSlug: string): void {
  djangoShell(`
from apps.clinics.models import Clinic
from apps.chatbot.models import ChatVisitor, ChatSession, ChatSessionStatus, ChatMessage, MessageRole, MessageType
from apps.patients.models import Patient
c = Clinic.objects.get(slug="${clinicSlug}")
patient, _ = Patient.objects.get_or_create(
    clinic=c, phone="+15559990001", defaults=dict(first_name="Farah", last_name="Chattest"),
)
v, _ = ChatVisitor.objects.get_or_create(
    clinic=c, visitor_key="e2e-staff-visitor-${clinicSlug}", defaults=dict(patient=patient),
)
s, _ = ChatSession.objects.get_or_create(
    clinic=c, visitor=v, session_token="e2e-staff-session-${clinicSlug}",
    defaults=dict(status=ChatSessionStatus.ACTIVE, patient=patient, is_authenticated=True),
)
ChatMessage.objects.filter(session=s).delete()
ChatMessage.objects.create(
    clinic=c, session=s, role=MessageRole.USER, message_type=MessageType.TEXT,
    content="Who are your cardiologists?", sequence_number=1, metadata={},
)
ChatMessage.objects.create(
    clinic=c, session=s, role=MessageRole.ASSISTANT, message_type=MessageType.TEXT,
    content="Here are our cardiologists:", sequence_number=2,
    metadata={"doctors": [{"id": "d1", "name": "Dr. E2E Heart", "title": "Cardiologist"}]},
)
print("ok")
`);
}

async function injectStaffAuth(page: import("@playwright/test").Page, token: string) {
  await page.addInitScript((t) => {
    localStorage.setItem("synapse_staff_access", t);
    localStorage.setItem("synapse_staff_refresh", t);
    localStorage.setItem("synapse_remember_me", "1");
  }, token);
}

test.describe("Staff conversations inbox — real browser flow", () => {
  const clinicSlug = `e2e-staff-${Date.now()}`;
  let token: string;

  test.beforeAll(() => {
    token = seedClinicAdminToken(clinicSlug);
    seedConversationWithStructuredCard(clinicSlug);
  });

  test.afterAll(() => {
    // This spec never creates an Appointment (only Clinic/User/ClinicStaff/
    // Patient/chat rows, all of which cascade-delete via the clinic FK), so
    // no need to clear Appointment.doctor/patient PROTECT rows first.
    djangoShell(`
from apps.clinics.models import Clinic
c = Clinic.objects.filter(slug="${clinicSlug}").first()
if c:
    c.delete()
print("ok")
`);
  });

  test("clinic owner sees the conversation in the list, with the right preview", async ({
    page,
  }) => {
    await injectStaffAuth(page, token);
    await page.goto("/dashboard/conversations");

    await expect(page.getByText("Farah Chattest")).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText("Here are our cardiologists:")).toBeVisible();
  });

  test("opening a conversation renders the transcript, including a structured doctor card", async ({
    page,
  }) => {
    await injectStaffAuth(page, token);
    await page.goto("/dashboard/conversations");

    await page.getByText("Farah Chattest").click();

    await expect(page.getByText("Who are your cardiologists?")).toBeVisible({
      timeout: 10_000,
    });
    // Proves MessageRenderer reuse actually renders rich content in the
    // staff view, not just plain text — the persisted metadata's doctor
    // card must round-trip through the same component the patient widget
    // uses.
    await expect(page.getByText("Dr. E2E Heart")).toBeVisible();
  });

  test("search filters the conversation list by patient name", async ({ page }) => {
    await injectStaffAuth(page, token);
    await page.goto("/dashboard/conversations");
    await expect(page.getByText("Farah Chattest")).toBeVisible({ timeout: 15_000 });

    await page.getByPlaceholder("Search by name or phone…").fill("nonexistent-name-xyz");
    await expect(page.getByText("Farah Chattest")).not.toBeVisible();
    await expect(page.getByText("No conversations yet")).toBeVisible();

    await page.getByPlaceholder("Search by name or phone…").fill("Farah");
    await expect(page.getByText("Farah Chattest")).toBeVisible();
  });
});

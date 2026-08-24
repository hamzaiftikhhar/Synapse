import { execSync } from "node:child_process";
import { expect, test } from "@playwright/test";

/**
 * Real browser verification of ROADMAP.md's persistent-chat-history work
 * (Phase 29 Steps 1-5) — the thing that was previously only checked via
 * tsc/next build/direct backend curl calls because no browser-automation
 * tool existed in that environment. This is the first time it's actually
 * been clicked through.
 *
 * Each test seeds its own clinic (unique slug per test, not shared via
 * beforeAll) — deliberately self-contained so nothing depends on test
 * execution order or on state surviving across tests.
 */

const REPO_ROOT = "/Users/apple/development/Synapse";

function djangoShell(code: string): string {
  const out = execSync(
    `python manage.py shell -c '${code.replace(/'/g, "'\\''")}'`,
    { cwd: REPO_ROOT, encoding: "utf-8" }
  );
  const lines = out.trim().split("\n");
  return lines[lines.length - 1];
}

function uniqueSlug(prefix: string): string {
  return `${prefix}-${Date.now()}-${Math.floor(Math.random() * 100000)}`;
}

function seedClinic(slug: string): void {
  djangoShell(`
from apps.clinics.models import Clinic
Clinic.objects.get_or_create(
    slug="${slug}",
    defaults=dict(name="E2E Persistence Clinic", email="e2e-persist@test.com",
                  phone="+12125550900", timezone="America/New_York", status="active"),
)
print("ok")
`);
}

/** Seeds a session directly in the DB with `count` messages, bound to a
 * given visitor key, so pagination/date-separator behavior can be tested
 * without sending 60+ real chat turns through the NLU pipeline. */
function seedHistory(clinicSlug: string, visitorKey: string, count: number): void {
  djangoShell(`
from apps.clinics.models import Clinic
from apps.chatbot.models import ChatVisitor, ChatSession, ChatSessionStatus, ChatMessage, MessageRole, MessageType
c = Clinic.objects.get(slug="${clinicSlug}")
v, _ = ChatVisitor.objects.get_or_create(clinic=c, visitor_key="${visitorKey}")
s, _ = ChatSession.objects.get_or_create(
    clinic=c, visitor=v, session_token="tok-${visitorKey}",
    defaults=dict(status=ChatSessionStatus.ACTIVE),
)
for i in range(1, ${count} + 1):
    ChatMessage.objects.create(
        clinic=c, session=s,
        role=MessageRole.USER if i % 2 else MessageRole.ASSISTANT,
        message_type=MessageType.TEXT, content=f"seeded message {i}",
        sequence_number=i, metadata={},
    )
print("ok")
`);
}

test("first-time visitor: opening the widget never calls /chat/resume", async ({ page }) => {
  const clinicSlug = uniqueSlug("e2e-persist-first");
  seedClinic(clinicSlug);

  const resumeCalls: string[] = [];
  page.on("request", (req) => {
    if (req.url().includes("/chat/resume")) resumeCalls.push(req.url());
  });

  await page.goto(`/embed/${clinicSlug}`);
  await page.getByPlaceholder("Write a message").waitFor({ timeout: 30_000 });
  await page.waitForTimeout(1000);
  expect(resumeCalls).toHaveLength(0);
});

test("sending the first message creates a visitor id, persisted in localStorage", async ({
  page,
}) => {
  const clinicSlug = uniqueSlug("e2e-persist-send");
  seedClinic(clinicSlug);

  await page.goto(`/embed/${clinicSlug}`);
  const composer = page.getByPlaceholder("Write a message");
  await composer.fill("Hello, testing persistence");
  await page.getByRole("button", { name: "Send message" }).click();

  await expect(page.getByText("Hello, testing persistence")).toBeVisible();

  await expect
    .poll(
      () =>
        page.evaluate(() =>
          Object.keys(localStorage).some((k) => k.startsWith("synapse_visitor_id_"))
        ),
      { timeout: 25_000, message: "visitor id never landed in localStorage" }
    )
    .toBeTruthy();
});

test("returning visitor: reopening the widget resumes the prior conversation", async ({
  page,
}) => {
  const clinicSlug = uniqueSlug("e2e-persist-resume");
  seedClinic(clinicSlug);

  await page.goto(`/embed/${clinicSlug}`);
  const composer = page.getByPlaceholder("Write a message");
  await composer.fill("Persisted message for resume test");
  await page.getByRole("button", { name: "Send message" }).click();
  await expect(page.getByText("Persisted message for resume test")).toBeVisible();

  await expect
    .poll(() =>
      page.evaluate(() =>
        Object.keys(localStorage).some((k) => k.startsWith("synapse_visitor_id_"))
      )
    , { timeout: 25_000 })
    .toBeTruthy();

  const resumeStatuses: number[] = [];
  page.on("response", (res) => {
    if (res.url().includes("/chat/resume")) resumeStatuses.push(res.status());
  });

  await page.reload();
  await expect(page.getByText("Persisted message for resume test")).toBeVisible({
    timeout: 30_000,
  });
  expect(resumeStatuses).toContain(200);
});

test("scrolling up loads an older page and a date separator renders", async ({ page }) => {
  // A realistic floating-widget size, not the full test-browser viewport —
  // otherwise 50 one-line "seeded message N" bubbles fit on screen with
  // nothing to scroll, which would make this test pass or fail for the
  // wrong reason (the observer legitimately auto-loads more when there's
  // no scrollbar at all, same as real infinite-scroll UX should).
  await page.setViewportSize({ width: 400, height: 640 });

  const clinicSlug = uniqueSlug("e2e-persist-scroll");
  const visitorKey = uniqueSlug("visitor");
  seedClinic(clinicSlug);
  seedHistory(clinicSlug, visitorKey, 70);

  await page.addInitScript(
    ({ slug, key }) => {
      localStorage.setItem(`synapse_visitor_id_${slug}`, key);
    },
    { slug: clinicSlug, key: visitorKey }
  );

  await page.goto(`/embed/${clinicSlug}`);
  await expect(page.getByText("seeded message 70")).toBeVisible({ timeout: 30_000 });
  // Only the newest 50 of 70 are loaded initially — checked by DOM count,
  // not .not.toBeVisible() (Playwright's visibility check doesn't reliably
  // detect content merely scrolled out of an overflow:auto container).
  await expect(page.getByText(/^seeded message \d+$/)).toHaveCount(50);

  const olderPageCalls: string[] = [];
  page.on("response", (res) => {
    if (res.url().includes("/messages?") && res.url().includes("before=")) {
      olderPageCalls.push(res.url());
    }
  });

  const scrollContainer = page.locator(".overflow-y-auto").first();
  await scrollContainer.evaluate((el) => {
    el.scrollTop = 0;
  });

  await expect
    .poll(() => olderPageCalls.length, { timeout: 15_000 })
    .toBeGreaterThan(0);
  await expect(page.getByText(/^seeded message \d+$/)).toHaveCount(70, { timeout: 10_000 });
  await expect(page.getByText(/Today|Yesterday|\d{4}/).first()).toBeVisible();
});

test("the Latest button appears when scrolled away from the bottom and returns to it", async ({
  page,
}) => {
  await page.setViewportSize({ width: 400, height: 640 });

  const clinicSlug = uniqueSlug("e2e-persist-latest");
  const visitorKey = uniqueSlug("visitor");
  seedClinic(clinicSlug);
  seedHistory(clinicSlug, visitorKey, 55);

  await page.addInitScript(
    ({ slug, key }) => {
      localStorage.setItem(`synapse_visitor_id_${slug}`, key);
    },
    { slug: clinicSlug, key: visitorKey }
  );

  await page.goto(`/embed/${clinicSlug}`);
  await expect(page.getByText("seeded message 55")).toBeVisible({ timeout: 30_000 });

  const scrollContainer = page.locator(".overflow-y-auto").first();
  await scrollContainer.evaluate((el) => {
    el.scrollTop = 0;
  });

  const latestButton = page.getByRole("button", { name: /latest/i });
  await expect(latestButton).toBeVisible({ timeout: 10_000 });
  await latestButton.click();

  await expect(latestButton).not.toBeVisible({ timeout: 10_000 });
  const atBottom = await scrollContainer.evaluate(
    (el) => el.scrollHeight - el.scrollTop - el.clientHeight < 80
  );
  expect(atBottom).toBeTruthy();
});

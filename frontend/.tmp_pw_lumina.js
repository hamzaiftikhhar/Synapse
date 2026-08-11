const { chromium } = require('playwright');
const fs = require('fs');

const SHOTS = '/private/tmp/claude-501/-Users-apple-development-Synapse/063b801d-140c-4caa-a2a1-92fd48cd9850/scratchpad/shots_lumina';
if (!fs.existsSync(SHOTS)) fs.mkdirSync(SHOTS, { recursive: true });

async function shot(page, name) {
  await page.screenshot({ path: `${SHOTS}/${name}.png`, fullPage: true });
  console.log('SHOT', name);
}

async function sendMessage(page, text) {
  const input = page.locator('textarea, input[placeholder*="message" i], input[placeholder*="Write" i]').last();
  await input.click();
  await input.fill(text);
  await input.press('Enter');
}

async function bodyText(page) {
  return page.locator('body').innerText();
}

async function waitForIdle(page, maxMs = 20000) {
  const start = Date.now();
  while (Date.now() - start < maxMs) {
    const busy = await page.getByText('Looking into that', { exact: false }).count();
    if (!busy) return;
    await page.waitForTimeout(400);
  }
}

(async () => {
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  const page = await browser.newPage({ viewport: { width: 430, height: 900 } });
  const xhrLog = [];
  const consoleErrors = [];
  page.on('console', (msg) => { if (msg.type() === 'error') consoleErrors.push(msg.text()); });
  page.on('pageerror', (err) => consoleErrors.push('PAGEERROR: ' + err.message));
  page.on('requestfinished', async (req) => {
    if (req.url().includes('/api/v1/widget/')) {
      let status = null;
      try { status = (await req.response())?.status(); } catch {}
      xhrLog.push({ url: req.url().replace('http://127.0.0.1:8000/api/v1', ''), method: req.method(), status });
    }
  });

  console.log('\n=== LUMINA SCENARIO A: fresh session -> book via wizard -> OTP inside wizard -> show my appointments (no re-verify) ===');
  await page.goto('http://localhost:3000/embed/lumina-skin', { waitUntil: 'networkidle' });
  await page.waitForTimeout(1500);
  await shot(page, 'A1_loaded');

  await sendMessage(page, 'I would like to book an appointment');
  await page.waitForTimeout(4000);
  await shot(page, 'A2_wizard_opened');

  const uniqueEmail = `pw-lumina-${Date.now()}@example.com`;

  // Drive the wizard through whatever steps appear, generically.
  for (let i = 0; i < 12; i++) {
    const txt = await bodyText(page);
    console.log(`--- wizard iteration ${i}, snippet: ${txt.slice(-300).replace(/\n/g, ' | ')}`);

    if (/how would you like to book/i.test(txt)) {
      // PathStep - click "First available" (recommended option)
      const btn = page.locator('button', { hasText: /first available/i }).first();
      if (await btn.count()) { await btn.click(); await page.waitForTimeout(2500); continue; }
    }
    if (/choose a specialty/i.test(txt)) {
      const item = page.locator('ul li button').first();
      if (await item.count()) { await item.click(); await page.waitForTimeout(2000); continue; }
    }
    if (/choose a doctor/i.test(txt)) {
      const item = page.locator('button:has(span.text-sm.font-semibold)').first();
      if (await item.count()) { await item.click(); await page.waitForTimeout(2000); continue; }
      const anyDoctorBtn = page.getByText('Reserve').first();
      if (await anyDoctorBtn.count()) { await anyDoctorBtn.click(); await page.waitForTimeout(2000); continue; }
    }
    if (/choose a date/i.test(txt) || /when would you like to come in/i.test(txt)) {
      const enabledDate = page.locator('button:not([disabled])').filter({ hasNotText: '' });
      // Grid of date buttons — pick one that's not disabled, inside the date grid
      const dateBtn = page.locator('.grid.grid-cols-7 button:not([disabled])').first();
      if (await dateBtn.count()) { await dateBtn.click(); await page.waitForTimeout(2000); continue; }
    }
    if (/choose a time/i.test(txt)) {
      const slotBtn = page.locator('button').filter({ hasText: /AM|PM/i }).first();
      if (await slotBtn.count()) { await slotBtn.click(); await page.waitForTimeout(2000); continue; }
    }
    if (/almost done/i.test(txt)) {
      const nameInputs = page.locator('.grid.grid-cols-2 input');
      await nameInputs.nth(0).fill('Playwright');
      await nameInputs.nth(1).fill('Tester');
      const contactInput = page.locator('input[autocomplete="username"]').last();
      await contactInput.fill(uniqueEmail);
      await shot(page, `A3_details_filled_iter${i}`);
      const continueBtn = page.getByRole('button', { name: /continue to verification/i }).first();
      await continueBtn.click();
      await page.waitForTimeout(2500);
      continue;
    }
    if (/verify your (email|identity)/i.test(txt)) {
      const m = txt.match(/Dev code:\s*(\d{4,8})/i);
      await shot(page, `A4_otp_step_iter${i}`);
      if (m) {
        const codeInput = page.locator('input[autocomplete="one-time-code"]').last();
        await codeInput.fill(m[1]);
        const confirmBtn = page.getByRole('button', { name: /confirm appointment/i }).first();
        await confirmBtn.click();
        await page.waitForTimeout(3500);
      } else {
        console.log('NO DEV CODE FOUND IN OTP STEP');
      }
      continue;
    }
    if (/appointment confirmed|you'?re (all set|booked)|booking confirmed/i.test(txt)) {
      console.log('BOOKING CONFIRMED — breaking wizard loop');
      break;
    }
    console.log('UNMATCHED STEP — taking screenshot');
    await shot(page, `A_unmatched_iter${i}`);
  }

  await shot(page, 'A5_after_wizard_loop');
  let txt = await bodyText(page);
  console.log('CHECK booking appears confirmed:', /confirmed|booked|all set/i.test(txt));

  const xhrBeforeView = xhrLog.length;
  const [viewResp] = await Promise.all([
    page.waitForResponse((r) => r.url().includes('/widget/chat/guest'), { timeout: 30000 }),
    sendMessage(page, 'show me my appointments'),
  ]);
  console.log('VIEW_RESPONSE_STATUS:', viewResp.status());
  await page.waitForTimeout(600);
  await shot(page, 'A6_after_show_appointments');
  txt = await bodyText(page);
  const afterView = txt.split('show me my appointments').pop() || '';
  console.log('CHECK NO re-verification requested after booking:', !/verify your identity|verify it.?s you/i.test(afterView));
  console.log('CHECK appointment(s) shown:', /Dr\. Chloe Bennet/i.test(afterView) && /Reschedule/i.test(afterView));

  console.log('\n=== LUMINA SCENARIO B: cancel the just-booked appointment (same authenticated session) ===');
  const xhrBeforeCancel = xhrLog.length;
  const cancelBtn = page.getByRole('button', { name: /^cancel$/i }).first();
  if (await cancelBtn.count()) {
    await cancelBtn.click();
    await page.waitForTimeout(600);
    await shot(page, 'B1_cancel_confirm');
    txt = await bodyText(page);
    console.log('CHECK cancel confirmation shown:', /cancel appointment\?/i.test(txt));

    const confirmCancelBtn = page.getByRole('button', { name: /^cancel appointment$/i }).first();
    const [cancelResp] = await Promise.all([
      page.waitForResponse((r) => r.url().includes('/widget/appointments/cancel'), { timeout: 15000 }),
      confirmCancelBtn.click(),
    ]);
    console.log('CANCEL_RESPONSE_STATUS:', cancelResp.status());
    await page.waitForTimeout(600);
    await shot(page, 'B2_after_cancel');
    txt = await bodyText(page);
    console.log('CHECK cancellation success message shown:', /cancelled/i.test(txt));
    console.log('CHECK no re-verification during cancel:', !/verify your identity|verify it.?s you/i.test(txt.split('show me my appointments')[1] || ''));
  } else {
    console.log('NO_CANCEL_BUTTON_FOUND for scenario B');
  }
  console.log('CANCEL_FLOW_XHR:', JSON.stringify(xhrLog.slice(xhrBeforeCancel)));

  console.log('\nNEW_XHR_SINCE_VIEW_REQUEST:', JSON.stringify(xhrLog.slice(xhrBeforeView)));
  console.log('\nALL_XHR:', JSON.stringify(xhrLog));
  console.log('\nCONSOLE_ERRORS:', JSON.stringify(consoleErrors.slice(0, 30)));

  await browser.close();
})().catch((e) => {
  console.error('FAILED', e);
  process.exit(1);
});

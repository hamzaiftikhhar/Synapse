const { chromium } = require('playwright');
const fs = require('fs');
const SHOTS = '/private/tmp/claude-501/-Users-apple-development-Synapse/063b801d-140c-4caa-a2a1-92fd48cd9850/scratchpad/shots_lumina_resched';
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
async function bodyText(page) { return page.locator('body').innerText(); }

(async () => {
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  const page = await browser.newPage({ viewport: { width: 430, height: 950 } });
  page.on('pageerror', (err) => console.log('PAGEERROR', err.message));

  await page.goto('http://localhost:3000/embed/lumina-skin', { waitUntil: 'networkidle' });
  await page.waitForTimeout(1000);

  console.log('=== verify identity as real existing patient (alihamxa366@gmail.com, 7 appts) ===');
  const [r1] = await Promise.all([
    page.waitForResponse((r) => r.url().includes('/widget/chat/guest'), { timeout: 30000 }),
    sendMessage(page, 'I want to reschedule my appointment'),
  ]);
  console.log('first response status', r1.status());
  await page.waitForTimeout(600);
  await shot(page, '1_verify_prompt');

  // switch to email method
  const emailTab = page.getByRole('button', { name: /^email$/i }).first();
  await emailTab.click();
  await page.waitForTimeout(300);
  const emailInput = page.locator('input[type="email"]').first();
  await emailInput.fill('alihamxa366@gmail.com');
  const [sendResp] = await Promise.all([
    page.waitForResponse((r) => r.url().includes('/widget/otp/send'), { timeout: 15000 }),
    page.getByRole('button', { name: /send code/i }).first().click(),
  ]);
  console.log('otp/send status', sendResp.status());
  await page.waitForTimeout(500);
  let txt = await bodyText(page);
  const m = txt.match(/Dev only.{0,20}code is (\d{4,8})/i);
  console.log('debug code found:', !!m);
  if (!m) { await shot(page, 'ERR_no_debug_code'); await browser.close(); return; }

  await page.locator('input[aria-label="Digit 1 of 6"]').click();
  await page.keyboard.type(m[1]);
  const [verifyResp, listResp] = await Promise.all([
    page.waitForResponse((r) => r.url().includes('/widget/otp/verify'), { timeout: 15000 }),
    page.waitForResponse((r) => r.url().includes('/widget/appointments/list'), { timeout: 15000 }),
    page.getByRole('button', { name: /^verify$/i }).first().click(),
  ]);
  console.log('otp/verify status', verifyResp.status());
  console.log('appointments/list fired:', !!listResp, listResp.status());
  await page.waitForTimeout(500);
  await shot(page, '2_appointments_after_verify');
  txt = await bodyText(page);
  const doctorCount = (txt.match(/Reschedule/g) || []).length;
  console.log('CHECK multiple appointment cards shown (Reschedule button count):', doctorCount);

  // Grab appointment IDs directly from DB for cross-check before reschedule
  console.log('\n=== Click Reschedule on the FIRST appointment card, keep same doctor ===');
  const rescheduleBtn = page.getByRole('button', { name: /^reschedule$/i }).first();
  await rescheduleBtn.click();
  await page.waitForTimeout(400);
  await shot(page, '3_reschedule_confirm');
  txt = await bodyText(page);
  console.log('CHECK reschedule confirm shown:', /reschedule appointment\?/i.test(txt));

  const yesBtn = page.getByRole('button', { name: /yes, reschedule/i }).first();
  await yesBtn.click();
  await page.waitForTimeout(500);
  await shot(page, '4_reschedule_options');
  txt = await bodyText(page);
  console.log('CHECK keep-doctor option shown:', /keep /i.test(txt.toLowerCase()));

  const keepDoctorBtn = page.getByRole('button', { name: /^keep /i }).first();
  const [rescheduleApiResp] = await Promise.all([
    page.waitForResponse((r) => r.url().includes('/widget/appointments/reschedule'), { timeout: 15000 }),
    keepDoctorBtn.click(),
  ]);
  console.log('appointments/reschedule status', rescheduleApiResp.status());
  await page.waitForTimeout(2000);
  await shot(page, '5_wizard_for_new_slot');
  txt = await bodyText(page);
  console.log('CHECK wizard time-picker appeared:', /choose a date|choose a time|book appointment/i.test(txt));
  console.log('CHECK old appointment still described as booked until confirm:', /stays booked until you confirm/i.test(txt));
  console.log('CHECK no re-verification requested during reschedule setup:', !/verify your identity|verify it.?s you/i.test(txt.split('stays booked until you confirm')[1] || ''));

  console.log('\n=== Drive reschedule wizard to a new slot and confirm ===');
  for (let i = 0; i < 8; i++) {
    txt = await bodyText(page);
    console.log(`resched-wizard iter ${i}: ${txt.slice(-250).replace(/\n/g, ' | ')}`);
    if (/when would you like to come in|choose a date/i.test(txt)) {
      const dateBtn = page.locator('.grid.grid-cols-7 button:not([disabled])').first();
      if (await dateBtn.count()) { await dateBtn.click(); await page.waitForTimeout(2000); continue; }
    }
    if (/choose a time/i.test(txt)) {
      const slotBtn = page.locator('button').filter({ hasText: /AM|PM/i }).first();
      if (await slotBtn.count()) { await slotBtn.click(); await page.waitForTimeout(2000); continue; }
    }
    const latestChunk = txt.slice(-400);
    if (/almost done/i.test(latestChunk)) {
      console.log('DETAILS STEP RE-ASKED DURING RESCHEDULE OF ALREADY-AUTHENTICATED PATIENT — filling and continuing to see if a fresh OTP is then required');
      const nameInputs = page.locator('.grid.grid-cols-2 input');
      await nameInputs.nth(0).fill('Ali');
      await nameInputs.nth(1).fill('Hamza');
      const contactInput = page.locator('input[autocomplete="username"]').last();
      await contactInput.fill('alihamxa366@gmail.com');
      await page.getByRole('button', { name: /continue to verification/i }).first().click();
      await page.waitForTimeout(2500);
      continue;
    }
    if (/verify your (email|identity)/i.test(latestChunk) || /Dev code:/i.test(latestChunk)) {
      console.log('!!! FRESH OTP STEP REQUIRED DURING RESCHEDULE OF AN ALREADY-AUTHENTICATED PATIENT !!!');
      await shot(page, '6_UNEXPECTED_otp_step');
      const mm = latestChunk.match(/Dev code:\s*(\d{4,8})/i);
      if (mm) {
        const codeInput = page.locator('input[autocomplete="one-time-code"]').last();
        await codeInput.fill(mm[1]);
        await page.getByRole('button', { name: /confirm appointment/i }).first().click();
        await page.waitForTimeout(3000);
      } else {
        console.log('no dev code visible in latest chunk, breaking');
        break;
      }
      continue;
    }
    if (/confirmed for your appointment|we'?ve got you confirmed/i.test(txt)) {
      console.log('RESCHEDULE CONFIRMED');
      break;
    }
    await shot(page, `resched_unmatched_${i}`);
  }
  await shot(page, '7_final_state');

  await browser.close();
})().catch((e) => { console.error('FAILED', e); process.exit(1); });

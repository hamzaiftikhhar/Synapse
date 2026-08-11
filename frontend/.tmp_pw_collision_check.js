const { chromium } = require('playwright');

async function sendMessage(page, text) {
  const input = page.locator('textarea, input[placeholder*="message" i], input[placeholder*="Write" i]').last();
  await input.click();
  await input.fill(text);
  await input.press('Enter');
}
async function bodyText(page) { return page.locator('body').innerText(); }

async function bookWithEmail(browser, email) {
  const page = await browser.newPage({ viewport: { width: 430, height: 900 } });
  await page.goto('http://localhost:3000/embed/lumina-skin', { waitUntil: 'networkidle' });
  await page.waitForTimeout(800);
  await Promise.all([
    page.waitForResponse((r) => r.url().includes('/widget/chat/guest'), { timeout: 30000 }),
    sendMessage(page, 'I would like to book an appointment'),
  ]);
  await page.waitForTimeout(1500);

  for (let i = 0; i < 8; i++) {
    const txt = await bodyText(page);
    const firstAvailBtn = page.locator('button', { hasText: /^first available$/i }).first();
    const dateBtn = page.locator('.grid.grid-cols-7 button:not([disabled])').first();
    const slotBtn = page.locator('button').filter({ hasText: /AM|PM/i }).first();
    if (await firstAvailBtn.count()) {
      await firstAvailBtn.click(); await page.waitForTimeout(2000); continue;
    }
    if (await slotBtn.count()) {
      await slotBtn.click(); await page.waitForTimeout(2000); continue;
    }
    if (await dateBtn.count()) {
      await dateBtn.click(); await page.waitForTimeout(2000); continue;
    }
    if (/almost done/i.test(txt)) {
      const nameInputs = page.locator('.grid.grid-cols-2 input');
      await nameInputs.nth(0).fill('Collision');
      await nameInputs.nth(1).fill('Test');
      await page.locator('input[autocomplete="username"]').last().fill(email);
      await page.getByRole('button', { name: /continue to verification/i }).first().click();
      await page.waitForTimeout(2000); continue;
    }
    if (/verify your (email|identity)/i.test(txt)) {
      const m = txt.match(/Dev code:\s*(\d{4,8})/i);
      if (m) {
        await page.locator('input[autocomplete="one-time-code"]').last().fill(m[1]);
        await page.getByRole('button', { name: /confirm appointment/i }).first().click();
        await page.waitForTimeout(2500);
      }
      continue;
    }
    if (/confirmed for your appointment|we'?ve got you confirmed/i.test(txt)) break;
  }
  const final = await bodyText(page);
  const codeMatch = final.match(/Code\s+([A-Z0-9]{6})/);
  console.log(email, '-> confirmation code:', codeMatch ? codeMatch[1] : 'NOT FOUND');
  await page.close();
}

(async () => {
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  await bookWithEmail(browser, 'collision-test-abcdefg@example.com');
  await bookWithEmail(browser, 'collision-test-abcdefg@different.org');
  await browser.close();
})().catch((e) => { console.error('FAILED', e); process.exit(1); });

const { chromium } = require('playwright');
const fs = require('fs');
const SHOTS = '/private/tmp/claude-501/-Users-apple-development-Synapse/063b801d-140c-4caa-a2a1-92fd48cd9850/scratchpad/shots_debug1';
if (!fs.existsSync(SHOTS)) fs.mkdirSync(SHOTS, { recursive: true });

(async () => {
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  const page = await browser.newPage({ viewport: { width: 430, height: 900 } });
  page.on('console', (msg) => console.log('CONSOLE', msg.type(), msg.text()));
  page.on('pageerror', (err) => console.log('PAGEERROR', err.message));
  page.on('request', (req) => console.log('REQ', req.method(), req.url()));
  page.on('response', (res) => console.log('RES', res.status(), res.url()));
  page.on('requestfailed', (req) => console.log('REQFAILED', req.url(), req.failure()?.errorText));

  await page.goto('http://localhost:3000/embed/lumina-skin', { waitUntil: 'networkidle' });
  await page.waitForTimeout(1000);

  const input = page.locator('textarea, input[placeholder*="message" i], input[placeholder*="Write" i]').last();
  await input.click();
  await input.fill('I would like to book an appointment');
  await input.press('Enter');

  await page.waitForTimeout(6000);
  await page.screenshot({ path: `${SHOTS}/state.png`, fullPage: true });
  console.log('BODY:', await page.locator('body').innerText());

  await browser.close();
})().catch((e) => { console.error('FAILED', e); process.exit(1); });

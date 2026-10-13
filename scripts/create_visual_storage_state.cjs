const { chromium } = require('@playwright/test');
const fs = require('node:fs');
const path = require('node:path');

const baseURL = process.env.BOOSTUDY_E2E_BASE_URL || 'http://127.0.0.1:5000';
const username = process.env.BOOSTUDY_VISUAL_USERNAME;
const password = process.env.BOOSTUDY_VISUAL_PASSWORD;
const outputPath = path.resolve(process.env.BOOSTUDY_VISUAL_STORAGE_STATE || 'artifacts/visual/storage-state.json');

if (!username || !password) {
  throw new Error('Set BOOSTUDY_VISUAL_USERNAME and BOOSTUDY_VISUAL_PASSWORD for local visual auth.');
}

(async () => {
  const browser = await chromium.launch();
  const context = await browser.newContext();
  const page = await context.newPage();
  await page.goto(`${baseURL}/login?next=%2Fdashboard`, { waitUntil: 'networkidle' });
  const usernameField = page.locator('input[name="username"], input[name="email"]').first();
  await usernameField.fill(username);
  await page.locator('input[name="password"]').fill(password);
  await page.locator('button[type="submit"], input[type="submit"]').first().click();
  await page.waitForURL(/\/dashboard(?:\?|$)/, { timeout: 20_000 });
  fs.mkdirSync(path.dirname(outputPath), { recursive: true });
  await context.storageState({ path: outputPath });
  console.log(`Visual storage state saved to ${outputPath}`);
  await browser.close();
})().catch(async (error) => {
  console.error(error);
  process.exitCode = 1;
});

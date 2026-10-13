const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('@playwright/test');

const baseUrl = process.env.BOOSTUDY_E2E_BASE_URL || 'http://127.0.0.1:5000';
const storageState = process.env.BOOSTUDY_VISUAL_STORAGE_STATE;
const outputDir = path.resolve(process.env.BOOSTUDY_GOLDEN_OUTPUT || 'artifacts/visual/dashboard');
const screenshotPath = path.join(outputDir, 'golden-current-before.png');
const metricsPath = path.join(outputDir, 'golden-current-before-dom.json');

const selectors = {
  sidebar: '.bs-dashboard-sidebar',
  topbar: '.bs-dashboard-topbar',
  content: '.bs-dashboard-content',
  hero: '.bs-teacher-hero',
  summary: '.bs-teacher-summary-card',
  metrics: '.bs-teacher-metrics',
  mainRow: '.bs-teacher-main-grid',
  bottomRow: '.bs-teacher-bottom-grid',
  heroCopy: '.bs-teacher-hero-copy',
  heroMascot: '.bs-teacher-hero-mascot',
  sidebarFooter: '.bs-dashboard-sidebar-footer'
};

function rectData(rect) {
  if (!rect) return null;
  return {
    x: Math.round(rect.x),
    y: Math.round(rect.y),
    width: Math.round(rect.width),
    height: Math.round(rect.height),
    right: Math.round(rect.right),
    bottom: Math.round(rect.bottom)
  };
}

(async () => {
  fs.mkdirSync(outputDir, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  const contextOptions = { viewport: { width: 1536, height: 1024 }, deviceScaleFactor: 1 };
  if (storageState && fs.existsSync(storageState)) contextOptions.storageState = storageState;
  const context = await browser.newContext(contextOptions);
  const page = await context.newPage();
  await page.goto(`${baseUrl}/dashboard`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(350);
  await page.screenshot({ path: screenshotPath, fullPage: false });
  const metrics = await page.evaluate((selectorMap) => {
    const measured = {};
    for (const [name, selector] of Object.entries(selectorMap)) {
      const node = document.querySelector(selector);
      measured[name] = node ? node.getBoundingClientRect().toJSON() : null;
    }
    return {
      viewport: { width: window.innerWidth, height: window.innerHeight },
      document: { scrollWidth: document.documentElement.scrollWidth, scrollHeight: document.documentElement.scrollHeight },
      selectors: measured
    };
  }, selectors);
  fs.writeFileSync(metricsPath, `${JSON.stringify(metrics, null, 2)}\n`, 'utf8');
  await browser.close();
  console.log(`Captured ${screenshotPath}`);
  console.log(`Captured ${metricsPath}`);
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});

import { test, expect } from '@playwright/test';

const BASE_URL = process.env.BOOSTUDY_E2E_BASE_URL || 'http://127.0.0.1:5000';

async function login(page, username, password) {
  await page.context().clearCookies();
  await page.goto(`${BASE_URL}/login`, { waitUntil: 'domcontentloaded' });
  await page.fill('input[name="username"]', username);
  await page.fill('input[name="password"]', password);
  await Promise.all([
    page.waitForNavigation({ waitUntil: 'domcontentloaded' }),
    page.click('button[type="submit"]')
  ]);
}

test.describe('P0 Performance & Asset Integrity Recovery', () => {

  test('P-01: Lesson Room loads fast with 0 network timeouts and 100% visible icons', async ({ page }) => {
    const timeouts: string[] = [];
    const failedUrls: string[] = [];

    page.on('requestfailed', req => {
      const f = req.failure();
      const err = f ? f.errorText : 'Unknown';
      if (err.includes('TIMED_OUT') || err.includes('timeout')) {
        timeouts.push(req.url());
      }
      failedUrls.push(`${req.url()} (${err})`);
    });

    await login(page, 'qa_pool_tutor_1', '123456');

    const navStart = Date.now();
    const resp = await page.goto(`${BASE_URL}/lesson/2168/room`, { waitUntil: 'load', timeout: 25000 });
    const loadTime = Date.now() - navStart;

    expect(resp?.status()).toBe(200);
    expect(timeouts).toHaveLength(0);
    expect(loadTime).toBeLessThan(3500);

    // Verify icons inside visible layout tree have valid non-zero dimensions
    const iconResults = await page.evaluate(() => {
      function isElementVisible(el: HTMLElement | null): boolean {
        let curr = el;
        while (curr && curr !== document.body) {
          const s = window.getComputedStyle(curr);
          if (s.display === 'none' || s.visibility === 'hidden' || parseFloat(s.opacity) === 0) {
            return false;
          }
          curr = curr.parentElement;
        }
        return true;
      }

      const icons = Array.from(document.querySelectorAll<HTMLElement>('i[class*="ph-"], .ph, [class*="ph"]'));
      let visibleCount = 0;
      let zeroDimensionCount = 0;

      for (const ic of icons) {
        if (!isElementVisible(ic.parentElement)) continue;
        visibleCount++;
        const rect = ic.getBoundingClientRect();
        const before = window.getComputedStyle(ic, '::before');
        if (rect.width === 0 || rect.height === 0 || before.content === 'none' || before.content === '""') {
          zeroDimensionCount++;
        }
      }

      return { visibleCount, zeroDimensionCount };
    });

    expect(iconResults.visibleCount).toBeGreaterThan(30);
    expect(iconResults.zeroDimensionCount).toBe(0);
  });

  test('P-02: Local vendor assets respond with HTTP 200 and immutable caching', async ({ page }) => {
    const assets = [
      '/static/fonts/fonts.css',
      '/static/vendor/phosphor/phosphor.css',
      '/static/vendor/phosphor/regular/Phosphor.woff2',
      '/static/vendor/skulpt/skulpt.min.js',
      '/static/vendor/tom-select/tom-select.complete.min.js',
      '/static/vendor/codemirror/codemirror.min.js',
      '/static/vendor/prism/prism.min.js'
    ];

    for (const assetPath of assets) {
      const resp = await page.request.get(`${BASE_URL}${assetPath}`);
      expect(resp.status(), `Asset ${assetPath} must return HTTP 200`).toBe(200);
    }
  });

  test('P-03: Homework workspace loads without external asset timeouts', async ({ page }) => {
    const timeouts: string[] = [];
    page.on('requestfailed', req => {
      const f = req.failure();
      if (f && (f.errorText.includes('TIMED_OUT') || f.errorText.includes('timeout'))) {
        timeouts.push(req.url());
      }
    });

    await login(page, 'demo_student_2', 'demo123pass');

    const navStart = Date.now();
    const resp = await page.goto(`${BASE_URL}/submissions/2697`, { waitUntil: 'load', timeout: 25000 });
    const loadTime = Date.now() - navStart;

    expect(resp?.status()).toBe(200);
    expect(timeouts).toHaveLength(0);
    expect(loadTime).toBeLessThan(3500);

    const iconResults = await page.evaluate(() => {
      function isElementVisible(el: HTMLElement | null): boolean {
        let curr = el;
        while (curr && curr !== document.body) {
          const s = window.getComputedStyle(curr);
          if (s.display === 'none' || s.visibility === 'hidden' || parseFloat(s.opacity) === 0) {
            return false;
          }
          curr = curr.parentElement;
        }
        return true;
      }

      const icons = Array.from(document.querySelectorAll<HTMLElement>('i[class*="ph-"], .ph, [class*="ph"]'));
      let visibleCount = 0;
      let zeroDimensionCount = 0;

      for (const ic of icons) {
        if (!isElementVisible(ic.parentElement)) continue;
        visibleCount++;
        const rect = ic.getBoundingClientRect();
        const before = window.getComputedStyle(ic, '::before');
        if (rect.width === 0 || rect.height === 0 || before.content === 'none' || before.content === '""') {
          zeroDimensionCount++;
        }
      }

      return { visibleCount, zeroDimensionCount };
    });

    expect(iconResults.visibleCount).toBeGreaterThan(15);
    expect(iconResults.zeroDimensionCount).toBe(0);
  });
});

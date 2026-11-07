import { test, expect, Page } from '@playwright/test';
import * as fs from 'node:fs';
import * as path from 'node:path';

const BASE_URL = process.env.BOOSTUDY_E2E_BASE_URL || 'http://127.0.0.1:5000';
const VIDEO_DIR = path.resolve('artifacts/visual/oristera/videos');

test.use({ video: { mode: 'on', size: { width: 1600, height: 900 } } });

async function signIn(page: Page) {
  await page.goto(`${BASE_URL}/login`);
  await page.fill('input[name="username"]', 'demo_student_1');
  await page.fill('input[name="password"]', 'demo123pass');
  await page.locator('button[type="submit"]').click();
  await page.waitForFunction(() => location.pathname !== '/login', undefined, { timeout: 15_000 });
}

async function saveVideo(page: Page, name: string) {
  const video = page.video();
  if (!video) throw new Error('Playwright video recording is not available for this page.');
  fs.mkdirSync(VIDEO_DIR, { recursive: true });
  await page.close();
  await video.saveAs(path.join(VIDEO_DIR, name));
}

test.describe('ORISTERA Atlas video evidence', () => {
  test('idle, hover, immersion, topic, and return', async ({ page }) => {
    test.setTimeout(90_000);
    await page.setViewportSize({ width: 1600, height: 900 });
    await signIn(page);
    await page.goto(`${BASE_URL}/oristera/atlas`);
    await expect(page.locator('#ori-atlas-world')).toBeVisible();
    await page.waitForTimeout(15_000);

    const firstDomain = page.locator('.atlas-domain-trigger').first();
    await firstDomain.hover();
    await page.waitForTimeout(900);
    await firstDomain.click();
    await expect(page.locator('#ori-cluster-inspector')).toBeVisible();
    await page.waitForTimeout(1_000);
    await page.locator('.atlas-domain.is-active .ori-star-node').first().click();
    await expect(page.locator('#ori-skill-inspector')).toBeVisible();
    await page.waitForTimeout(1_000);
    await page.keyboard.press('Escape');
    await page.keyboard.press('Escape');
    await expect(page.locator('#ori-atlas-overview-card')).toBeVisible();
    await page.waitForTimeout(1_000);
    await saveVideo(page, 'atlas-idle-hover-immersion-topic-return.webm');
  });

  test('Nexus to Atlas and Atlas to Practice', async ({ page }) => {
    test.setTimeout(60_000);
    await page.setViewportSize({ width: 1600, height: 900 });
    await signIn(page);
    await page.goto(`${BASE_URL}/oristera/nexus`);
    await expect(page.locator('.ori-genesis-orb.orb-atlas')).toBeVisible();
    await page.locator('.ori-genesis-orb.orb-atlas').click();
    await expect(page.locator('.ori-atlas-tabs')).toBeVisible();
    await page.locator('.ori-atlas-tab').first().click();
    await page.locator('.atlas-domain.is-active .ori-star-node').first().click();
    await expect(page.locator('#ori-skill-inspector')).toBeVisible();
    await page.locator('#ori-insp-practice-link').click();
    await page.waitForURL(/\/oristera\/practice\?/);
    await expect(page.locator('.ori-practice-code-panel')).toBeVisible();
    await page.waitForTimeout(800);
    await saveVideo(page, 'atlas-nexus-practice.webm');
  });

  test('reduced motion remains calm and usable', async ({ page }) => {
    test.setTimeout(60_000);
    await page.setViewportSize({ width: 1600, height: 900 });
    await signIn(page);
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await page.goto(`${BASE_URL}/oristera/atlas`);
    await expect(page.locator('#ori-atlas-world')).toBeVisible();
    await page.locator('.ori-atlas-tab').nth(1).click();
    await page.locator('.atlas-domain.is-active .ori-star-node').first().click();
    await expect(page.locator('#ori-skill-inspector')).toBeVisible();
    await page.waitForTimeout(1_000);
    await saveVideo(page, 'atlas-reduced-motion-topic.webm');
  });
});

import fs from 'node:fs';
import path from 'node:path';
import { expect, test, type Page } from '@playwright/test';
import { runGeometryAudit } from './visual/geometry-audit';

const LANDING = '/static/landing-release-candidate-rc2-1/index.html';
const ANALYTICS = '[data-s32-story]';
const FOUNDER = '[data-s42-founder]';

async function openLanding(page: Page, viewport = { width: 1920, height: 1080 }) {
  await page.setViewportSize(viewport);
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
  const response = await page.goto(LANDING, { waitUntil: 'networkidle' });
  await page.evaluate(() => document.fonts.ready);
  expect(response?.status()).toBe(200);
  expect(await page.title()).toBe('BooStudy — Release Candidate 2.1');
  expect(await page.locator('meta[name="robots"]').getAttribute('content')).toBe('noindex, nofollow');
  return errors;
}

async function scrollStory(page: Page, selector: string, progress: number, settleMs = 180) {
  await page.locator(selector).evaluate((story, value) => {
    document.documentElement.style.scrollBehavior = 'auto';
    const top = story.getBoundingClientRect().top + window.scrollY;
    const range = Math.max(1, story.offsetHeight - window.innerHeight);
    window.scrollTo({ top: top + range * value, behavior: 'instant' });
  }, progress);
  if (settleMs) await page.waitForTimeout(settleMs);
}

async function enterFounder(page: Page) {
  return page.locator(FOUNDER).evaluate(async founder => {
    document.documentElement.style.scrollBehavior = 'auto';
    const top = founder.getBoundingClientRect().top + window.scrollY;
    window.scrollTo({ top: top - 300, behavior: 'instant' });
    await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    return { top, entryY: window.scrollY };
  });
}

test('Analytics stays visible through the former crossfade seam', async ({ page }) => {
  const errors = await openLanding(page);
  const samples = [];
  for (let i = 6000; i <= 7000; i += 25) {
    const progress = i / 10000;
    await scrollStory(page, ANALYTICS, progress, 100);
    const state = await page.locator(ANALYTICS).evaluate(story => {
      const app = story.querySelector<HTMLElement>('.s32-app-shell')!;
      const copy = story.querySelector<HTMLElement>('.s32-composition')!;
      const analytics = story.querySelector<HTMLElement>('[data-s33-view="analytics"]')!;
      const chart = story.querySelector<HTMLElement>('[data-s32-chart-data]')!;
      return {
        progress: (window.scrollY - (story.getBoundingClientRect().top + window.scrollY)) / Math.max(1, story.offsetHeight - window.innerHeight),
        appOpacity: Number(getComputedStyle(app).opacity),
        copyOpacity: Number(copy.style.getPropertyValue('--s33-copy-opacity')),
        analyticsHidden: analytics.hidden,
        chartChildren: chart.children.length,
        metrics: [...story.querySelectorAll('[data-s32-metric]')].map(node => node.textContent?.trim()),
        title: story.querySelector('[data-s32-title]')?.textContent?.trim(),
      };
    });
    samples.push(state);
    expect(state.appOpacity, `product opacity at ${progress}`).toBeGreaterThanOrEqual(0.99);
    expect(state.copyOpacity, `copy opacity at ${progress}`).toBeGreaterThanOrEqual(0.99);
    expect(state.analyticsHidden).toBe(false);
  }
  expect(new Set(samples.map(sample => sample.chartChildren))).toEqual(new Set([14]));
  expect(new Set(samples.map(sample => sample.title))).toEqual(new Set(['Понимай, что уже получается.']));
  expect(new Set(samples.map(sample => sample.metrics[0]))).toEqual(new Set(['4']));
  expect(errors).toEqual([]);
});

test('Founder reveals once without scroll and retains content after re-entry', async ({ page }) => {
  const errors = await openLanding(page);
  const entry = await enterFounder(page);
  await expect(page.locator(FOUNDER)).toHaveAttribute('data-reveal-state', 'revealing');
  await page.waitForTimeout(900);
  const midway = await page.evaluate(() => ({
    scrollY,
    shown: document.querySelectorAll('[data-s42-founder] [data-s42-reveal].is-revealed').length,
    total: document.querySelectorAll('[data-s42-founder] [data-s42-reveal]').length,
  }));
  expect(midway.scrollY).toBe(entry.entryY);
  expect(midway.shown).toBeGreaterThan(1);
  await expect(page.locator(FOUNDER)).toHaveAttribute('data-reveal-state', 'complete', { timeout: 5000 });
  await expect(page.getByRole('heading', { name: 'Создано преподавателем. Для настоящего обучения.' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Давай обсудим твоё обучение.' })).toBeVisible();
  await expect(page.locator(`${FOUNDER} a[href="https://t.me/eohada"]`)).toBeVisible();
  await expect(page.locator(`${FOUNDER} a[href="/register"]`)).toBeVisible();

  await page.mouse.wheel(0, 260);
  await page.waitForTimeout(100);
  await page.mouse.wheel(0, -260);
  await expect(page.locator(FOUNDER)).toHaveAttribute('data-reveal-state', 'complete');
  expect(await page.locator(`${FOUNDER} [data-s42-reveal].is-revealed`).count()).toBe(8);
  expect(await page.locator('[data-s42-finale], .s42-commercial-finale').count()).toBe(0);
  expect(errors).toEqual([]);
});

test('fast scroll completes the reveal and keyboard reaches both actions', async ({ page }) => {
  const errors = await openLanding(page);
  await enterFounder(page);
  await expect(page.locator(FOUNDER)).toHaveAttribute('data-reveal-state', 'revealing');
  await page.mouse.wheel(0, 260);
  await expect(page.locator(FOUNDER)).toHaveAttribute('data-reveal-state', 'complete');

  const telegram = page.locator(`${FOUNDER} a[href="https://t.me/eohada"]`);
  const register = page.locator(`${FOUNDER} a[href="/register"]`);
  await telegram.focus();
  await expect(telegram).toBeFocused();
  await page.keyboard.press('Tab');
  await expect(register).toBeFocused();
  expect(await telegram.evaluate(node => getComputedStyle(node).opacity)).toBe('1');
  expect(errors).toEqual([]);
});

test('reduced motion exposes all Founder text and actions immediately', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  const errors = await openLanding(page);
  const state = await page.locator(FOUNDER).evaluate(founder => ({
    revealState: founder.getAttribute('data-reveal-state'),
    hidden: [...founder.querySelectorAll('[data-s42-reveal]')].filter(node => getComputedStyle(node).opacity !== '1' || node.hasAttribute('hidden') || node.getAttribute('aria-hidden') === 'true').length,
    actionOpacity: [...founder.querySelectorAll('[data-s42-reveal-actions] a')].map(node => getComputedStyle(node).opacity),
  }));
  expect(state.revealState).toBe('complete');
  expect(state.hidden).toBe(0);
  expect(state.actionOpacity).toEqual(['1', '1']);
  expect(await page.locator(`${FOUNDER} a[href="https://t.me/eohada"]`).getAttribute('href')).toBe('https://t.me/eohada');
  expect(await page.locator(`${FOUNDER} a[href="/register"]`).getAttribute('href')).toBe('/register');
  expect(errors).toEqual([]);
});

test('RC2.1 geometry audit and screenshots at desktop, tablet, and mobile widths', async ({ page }) => {
  await openLanding(page);
  const evidence = path.resolve('output/landing-release-audit/evidence/rc2.1/visual-qa');
  fs.mkdirSync(evidence, { recursive: true });
  const viewports = [
    { name: '1920x1080', width: 1920, height: 1080 },
    { name: '1440x900', width: 1440, height: 900 },
    { name: '1366x768', width: 1366, height: 768 },
    { name: '1024x768', width: 1024, height: 768 },
    { name: '768x1024', width: 768, height: 1024 },
    { name: '390x844', width: 390, height: 844 },
    { name: '320x700', width: 320, height: 700 },
  ];
  const reports = [];
  const auditAtFounder = async (route: string) => {
    await page.goto(route, { waitUntil: 'networkidle' });
    await page.evaluate(() => {
      document.documentElement.style.scrollBehavior = 'auto';
      const founder = document.querySelector<HTMLElement>('[data-s42-founder]')!;
      window.scrollTo({ top: founder.getBoundingClientRect().top + window.scrollY, behavior: 'instant' });
    });
    if (route.includes('rc2-1')) {
      await expect(page.locator(FOUNDER)).toHaveAttribute('data-reveal-state', 'complete', { timeout: 5000 });
    }
    return runGeometryAudit(page, route);
  };
  for (const viewport of viewports) {
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    const baseline = await auditAtFounder('/static/landing-release-candidate-rc2/index.html');
    const report = await auditAtFounder(LANDING);
    const failSignature = (finding: { severity: string; rule: string; selector: string; detail: string }) => `${finding.rule}|${finding.selector}|${finding.detail}`;
    const baselineFailures = new Set(baseline.findings.filter(finding => finding.severity === 'FAIL').map(failSignature));
    const newFailures = report.findings.filter(finding => finding.severity === 'FAIL' && !baselineFailures.has(failSignature(finding)));
    reports.push({ viewport: viewport.name, baseline: { passes: baseline.passes, findings: baseline.findings }, rc2_1: { passes: report.passes, findings: report.findings }, newFailures });
    expect(newFailures, `new geometry failures at ${viewport.name}`).toEqual([]);
    expect(report.passes, `no horizontal overflow at ${viewport.name}`).toContain('horizontal overflow');
    const founderBounds = await page.locator(`${FOUNDER} .s42-founder-layout`).boundingBox();
    expect(founderBounds).not.toBeNull();
    expect(founderBounds!.x).toBeGreaterThanOrEqual(0);
    expect(founderBounds!.x + founderBounds!.width).toBeLessThanOrEqual(viewport.width + 1);
    await page.screenshot({ path: path.join(evidence, `founder-${viewport.name}.jpg`), type: 'jpeg', quality: 88 });
  }
  fs.writeFileSync(path.join(evidence, 'geometry-audit.json'), JSON.stringify(reports, null, 2) + '\n');
});

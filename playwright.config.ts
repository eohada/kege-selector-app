import { defineConfig, devices } from '@playwright/test';

const baseURL = process.env.BOOSTUDY_E2E_BASE_URL || 'http://127.0.0.1:5000';
const e2ePort = new URL(baseURL).port || '5000';

export default defineConfig({
  testDir: './tests/e2e',
  timeout: 45_000,
  expect: {
    timeout: 7_000,
  },
  fullyParallel: false,
  retries: process.env.CI ? 1 : 0,
  reporter: [
    ['list'],
    ['html', { outputFolder: process.env.PLAYWRIGHT_HTML_OUTPUT_DIR || 'playwright-report', open: 'never' }],
  ],
  outputDir: process.env.PLAYWRIGHT_OUTPUT_DIR || 'test-results',
  use: {
    baseURL,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
    actionTimeout: 12_000,
    navigationTimeout: 20_000,
  },
  projects: [
    {
      name: 'desktop-chromium',
      use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 1000 } },
    },
    {
      name: 'mobile-chromium',
      use: { ...devices['Pixel 7'] },
    },
  ],
  webServer: process.env.BOOSTUDY_E2E_SKIP_SERVER
    ? undefined
    : {
      command: `node scripts/playwright_server.cjs`,
        url: baseURL,
        reuseExistingServer: true,
        timeout: 90_000,
        env: { ...process.env, BOOSTUDY_UI_DEV: '1' },
      },
});

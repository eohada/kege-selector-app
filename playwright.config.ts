import { defineConfig, devices } from '@playwright/test';

const baseURL = process.env.BOOSTUDY_E2E_BASE_URL || 'http://127.0.0.1:5000';

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
    ['html', { outputFolder: 'playwright-report', open: 'never' }],
  ],
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
        command:
          'SECRET_KEY=boostudy-e2e-secret venv_linux/bin/python -c "from wsgi import app; app.run(host=\'127.0.0.1\', port=5000, debug=False, use_reloader=False)"',
        url: baseURL,
        reuseExistingServer: true,
        timeout: 90_000,
      },
});

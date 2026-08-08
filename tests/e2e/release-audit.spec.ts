import { expect, Page, test } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';

type Severity = 'critical' | 'warning' | 'info';

type AuditIssue = {
  severity: Severity;
  role: string;
  page: string;
  message: string;
  details?: string;
};

type PageAuditResult = {
  role: string;
  page: string;
  url: string;
  status: number | null;
  title: string;
  screenshot: string;
  metrics: {
    viewport: { width: number; height: number };
    bodyTextLength: number;
    horizontalOverflowPx: number;
    brokenImages: string[];
    tinyClickTargets: number;
    visibleButtons: number;
    visibleLinks: number;
  };
  issues: AuditIssue[];
};

const password = process.env.BOOSTUDY_E2E_PASSWORD || '123456';
const artifactRoot = path.join(process.cwd(), 'test-results', 'release-audit');
const screenshotRoot = path.join(artifactRoot, 'screenshots');
const markdownReportPath = path.join(process.cwd(), 'docs', 'qa', 'release_audit_report.md');
const jsonReportPath = path.join(artifactRoot, 'release_audit_report.json');
const results: PageAuditResult[] = [];

const accounts = {
  student: process.env.BOOSTUDY_E2E_STUDENT || 'qa_pool_student_1',
  tutor: process.env.BOOSTUDY_E2E_TUTOR || 'qa_pool_tutor_1',
  parent: process.env.BOOSTUDY_E2E_PARENT || 'qa_pool_parent_1',
  admin: process.env.BOOSTUDY_E2E_ADMIN || 'qa_pool_admin_1',
};

const journeys: Record<string, { username: string; pages: { name: string; url: string }[] }> = {
  student: {
    username: accounts.student,
    pages: [
      { name: 'Комната ученика', url: '/dashboard' },
      { name: 'Задания ученика', url: '/submissions' },
      { name: 'Тренажер ученика', url: '/trainer/v2' },
      { name: 'Теория ученика', url: '/theory' },
      { name: 'Расписание ученика', url: '/schedule' },
      { name: 'Уведомления ученика', url: '/notifications' },
      { name: 'Профиль ученика', url: '/user/profile' },
    ],
  },
  tutor: {
    username: accounts.tutor,
    pages: [
      { name: 'Дашборд преподавателя', url: '/dashboard' },
      { name: 'Список учеников', url: '/students' },
      { name: 'Расписание преподавателя', url: '/schedule' },
      { name: 'Работы', url: '/assignments' },
      { name: 'Проверка', url: '/submissions' },
      { name: 'Очередь проверки', url: '/reviews/queue' },
      { name: 'Библиотека', url: '/library/materials' },
      { name: 'Генератор', url: '/task-generator' },
      { name: 'Тренажер преподавателя', url: '/trainer/v2' },
      { name: 'Профиль преподавателя', url: '/user/profile' },
    ],
  },
  parent: {
    username: accounts.parent,
    pages: [
      { name: 'Кабинет родителя', url: '/parent/dashboard' },
      { name: 'Расписание родителя', url: '/schedule' },
      { name: 'Уведомления родителя', url: '/notifications' },
      { name: 'Профиль родителя', url: '/user/profile' },
    ],
  },
  admin: {
    username: accounts.admin,
    pages: [
      { name: 'Дашборд администратора', url: '/dashboard' },
      { name: 'Пользователи', url: '/admin/users' },
      { name: 'QA-пул', url: '/qa/pool' },
      { name: 'Тарифы', url: '/billing/plans' },
      { name: 'Подписки', url: '/billing/subscriptions' },
      { name: 'Maintenance', url: '/maintenance' },
      { name: 'Темы', url: '/admin/topics' },
    ],
  },
};

test.beforeAll(() => {
  fs.rmSync(artifactRoot, { recursive: true, force: true });
  fs.mkdirSync(screenshotRoot, { recursive: true });
});

test.afterAll(() => {
  fs.mkdirSync(path.dirname(markdownReportPath), { recursive: true });
  fs.writeFileSync(jsonReportPath, JSON.stringify(results, null, 2));
  fs.writeFileSync(markdownReportPath, buildMarkdownReport(results));
});

test.beforeEach(async ({ page }) => {
  await installErrorCollectors(page);
});

async function installErrorCollectors(page: Page) {
  const consoleErrors: string[] = [];
  const failedResponses: string[] = [];

  page.on('console', (message) => {
    if (message.type() === 'error') {
      consoleErrors.push(message.text());
    }
  });

  page.on('pageerror', (error) => {
    consoleErrors.push(error.message);
  });

  page.on('response', (response) => {
    if (response.status() >= 500) {
      failedResponses.push(`${response.status()} ${response.url()}`);
    }
  });

  (page as Page & { __auditErrors?: () => { consoleErrors: string[]; failedResponses: string[] } }).__auditErrors = () => ({
    consoleErrors,
    failedResponses,
  });
}

async function login(page: Page, username: string) {
  await page.goto('/logout').catch(() => undefined);
  await page.goto('/login', { waitUntil: 'domcontentloaded' });
  await page.locator('input[name="username"]').fill(username);
  await page.locator('input[name="password"]').fill(password);
  await page.getByRole('button', { name: /войти/i }).click();
  await page.waitForLoadState('networkidle');
  await expect(page).not.toHaveURL(/\/login(?:\?|$)/);
}

function sanitizeFileName(value: string) {
  return value.toLowerCase().replace(/[^a-zа-я0-9]+/gi, '-').replace(/^-|-$/g, '').slice(0, 90) || 'page';
}

function ignoredConsoleError(message: string) {
  return [
    /favicon/i,
    /ResizeObserver loop/i,
    /Failed to load resource.*404/i,
    /NS_BINDING_ABORTED/i,
    /net::ERR_ABORTED/i,
  ].some((pattern) => pattern.test(message));
}

async function auditPage(page: Page, role: string, pageInfo: { name: string; url: string }): Promise<PageAuditResult> {
  const issues: AuditIssue[] = [];
  const response = await page.goto(pageInfo.url, { waitUntil: 'domcontentloaded' });
  await page.waitForLoadState('networkidle', { timeout: 8_000 }).catch(() => undefined);
  await page.waitForTimeout(250);

  const status = response?.status() ?? null;
  if (status === null || status >= 500) {
    issues.push({ severity: 'critical', role, page: pageInfo.name, message: `Страница вернула ${status ?? 'нет ответа'}` });
  } else if (status >= 400) {
    issues.push({ severity: 'warning', role, page: pageInfo.name, message: `Страница вернула HTTP ${status}` });
  }

  const body = page.locator('body');
  await expect(body).toBeVisible();
  const bodyText = (await body.innerText().catch(() => '')).trim();
  if (/страница не загрузилась|ошибка!!|internal server error|traceback|werkzeug debugger/i.test(bodyText)) {
    issues.push({ severity: 'critical', role, page: pageInfo.name, message: 'На странице виден системный текст ошибки' });
  }
  if (bodyText.length < 80) {
    issues.push({ severity: 'warning', role, page: pageInfo.name, message: 'Страница выглядит почти пустой', details: `Текста: ${bodyText.length} символов` });
  }

  const metrics = await page.evaluate(() => {
    const viewport = { width: window.innerWidth, height: window.innerHeight };
    const horizontalOverflowPx = Math.max(0, document.documentElement.scrollWidth - document.documentElement.clientWidth);
    const brokenImages = Array.from(document.images)
      .filter((img) => img.offsetParent !== null && (!img.complete || img.naturalWidth === 0))
      .map((img) => img.currentSrc || img.src || img.getAttribute('alt') || 'unknown')
      .slice(0, 12);
    const clickable = Array.from(document.querySelectorAll<HTMLElement>('button, a[href], input[type="button"], input[type="submit"], [role="button"]'))
      .filter((el) => {
        const rect = el.getBoundingClientRect();
        const style = window.getComputedStyle(el);
        return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
      });
    const tinyClickTargets = clickable.filter((el) => {
      const rect = el.getBoundingClientRect();
      return rect.width < 28 || rect.height < 28;
    }).length;
    return {
      viewport,
      bodyTextLength: (document.body.innerText || '').trim().length,
      horizontalOverflowPx,
      brokenImages,
      tinyClickTargets,
      visibleButtons: Array.from(document.querySelectorAll('button, input[type="button"], input[type="submit"], [role="button"]')).length,
      visibleLinks: Array.from(document.querySelectorAll('a[href]')).length,
    };
  });

  if (metrics.horizontalOverflowPx > 4) {
    issues.push({ severity: 'warning', role, page: pageInfo.name, message: 'Есть горизонтальный скролл', details: `${metrics.horizontalOverflowPx}px лишней ширины` });
  }
  if (metrics.brokenImages.length) {
    issues.push({ severity: 'warning', role, page: pageInfo.name, message: 'Есть сломанные изображения', details: metrics.brokenImages.join('\n') });
  }
  if (metrics.tinyClickTargets > 8) {
    issues.push({ severity: 'info', role, page: pageInfo.name, message: 'Много очень маленьких кликабельных элементов', details: `${metrics.tinyClickTargets} элементов меньше 28px` });
  }

  const audit = (page as Page & { __auditErrors?: () => { consoleErrors: string[]; failedResponses: string[] } }).__auditErrors?.();
  const consoleErrors = (audit?.consoleErrors || []).filter((message) => !ignoredConsoleError(message));
  const failedResponses = audit?.failedResponses || [];
  for (const error of consoleErrors.slice(0, 8)) {
    issues.push({ severity: 'critical', role, page: pageInfo.name, message: 'Ошибка в консоли браузера', details: error });
  }
  for (const error of failedResponses.slice(0, 8)) {
    issues.push({ severity: 'critical', role, page: pageInfo.name, message: 'HTTP 500+ в сетевом запросе', details: error });
  }

  const screenshot = path.join(screenshotRoot, `${sanitizeFileName(role)}-${sanitizeFileName(pageInfo.name)}-${test.info().project.name}.png`);
  await page.screenshot({ path: screenshot, fullPage: true });

  return {
    role,
    page: pageInfo.name,
    url: pageInfo.url,
    status,
    title: await page.title(),
    screenshot,
    metrics,
    issues,
  };
}

function buildMarkdownReport(report: PageAuditResult[]) {
  const allIssues = report.flatMap((result) => result.issues);
  const critical = allIssues.filter((issue) => issue.severity === 'critical');
  const warnings = allIssues.filter((issue) => issue.severity === 'warning');
  const info = allIssues.filter((issue) => issue.severity === 'info');
  const checkedAt = new Date().toISOString();

  const lines = [
    '# Релизная ревизия BooStudy',
    '',
    `Дата прогона: ${checkedAt}`,
    '',
    '## Итог',
    '',
    `- Проверено страниц: ${report.length}`,
    `- Критичных проблем: ${critical.length}`,
    `- Предупреждений: ${warnings.length}`,
    `- UX-заметок: ${info.length}`,
    '',
  ];

  lines.push('## Проверенные страницы', '');
  for (const result of report) {
    const issueText = result.issues.length
      ? result.issues.map((issue) => `${issue.severity}: ${issue.message}`).join('; ')
      : 'OK';
    lines.push(`- ${result.role} · ${result.page} · ${result.status} · ${result.url} · ${issueText}`);
  }

  if (allIssues.length) {
    lines.push('', '## Найденные проблемы', '');
    for (const issue of allIssues) {
      lines.push(`### ${issue.severity.toUpperCase()} · ${issue.role} · ${issue.page}`);
      lines.push(issue.message);
      if (issue.details) {
        lines.push('', '```text', issue.details.slice(0, 2000), '```');
      }
      lines.push('');
    }
  }

  lines.push('', '## Скриншоты', '');
  for (const result of report) {
    lines.push(`- ${result.role} · ${result.page}: ${path.relative(process.cwd(), result.screenshot)}`);
  }

  return `${lines.join('\n')}\n`;
}

test.describe.configure({ mode: 'serial' });

for (const [role, journey] of Object.entries(journeys)) {
  test(`release audit: ${role}`, async ({ page }) => {
    await login(page, journey.username);
    for (const pageInfo of journey.pages) {
      const result = await auditPage(page, role, pageInfo);
      results.push(result);
      const critical = result.issues.filter((issue) => issue.severity === 'critical');
      expect(critical, `${role} / ${pageInfo.name}`).toEqual([]);
    }
  });
}

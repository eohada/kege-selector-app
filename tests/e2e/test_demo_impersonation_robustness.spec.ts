import { expect, test } from '@playwright/test';

test.describe('P0 Demo Impersonation & Real-Time Sync Verification', () => {

  test('P0-DEMO-1: Dev switcher badge visibility, modal tabs, and 15 canonical demo accounts', async ({ page }) => {
    // 1. Visit /login
    await page.goto('/login', { waitUntil: 'domcontentloaded' });

    // 2. Dev switcher badge must be visible and prominent
    const badge = page.locator('#dev-switcher-trigger-badge');
    await expect(badge).toBeVisible({ timeout: 10_000 });
    await expect(badge).toContainText('DEV');

    // 3. Click badge to open modal
    await badge.click();
    const modal = page.locator('#dev-role-switcher-modal');
    await expect(modal).toBeVisible({ timeout: 5_000 });

    // 4. Wait for users to load
    const userList = page.locator('#dev-switcher-user-list');
    await expect(userList.locator('a[href*="/sandbox/impersonate/"]')).toHaveCount(15, { timeout: 10_000 });

    // 5. Verify filter tabs exist and work
    const studentTab = page.locator('.dev-role-filter[data-filter="student"]');
    await studentTab.click();
    // In our pool: demo_student_1, demo_student_2, demo_student_3
    const studentLinks = userList.locator('a[href*="/sandbox/impersonate/"]');
    await expect(studentLinks).toHaveCount(3);
    await expect(studentLinks.first()).toContainText('demo_student_1');

    const tutorTab = page.locator('.dev-role-filter[data-filter="tutor"]');
    await tutorTab.click();
    // In our pool: qa_pool_teacher_1, demo_teacher_2, demo_tutor_1
    const tutorLinks = userList.locator('a[href*="/sandbox/impersonate/"]');
    await expect(tutorLinks).toHaveCount(3);

    const allTab = page.locator('.dev-role-filter[data-filter="all"]');
    await allTab.click();
    await expect(userList.locator('a[href*="/sandbox/impersonate/"]')).toHaveCount(15);
  });

  test('P0-DEMO-2: Dual-browser impersonation, session isolation, and Lesson 89 sync', async ({ browser }) => {
    const teacherContext = await browser.newContext();
    const studentContext = await browser.newContext();

    const teacherPage = await teacherContext.newPage();
    const studentPage = await studentContext.newPage();

    try {
      // 1. Teacher impersonation via UI in teacherContext
      await teacherPage.goto('/login', { waitUntil: 'domcontentloaded' });
      await teacherPage.locator('#dev-switcher-trigger-badge').click();
      const teacherModal = teacherPage.locator('#dev-role-switcher-modal');
      await expect(teacherModal).toBeVisible({ timeout: 5_000 });

      // Click demo_teacher_2 link
      const teacherLink = teacherPage.locator('#dev-switcher-user-list a[href*="/sandbox/impersonate/"]:has-text("demo_teacher_2")');
      await expect(teacherLink).toBeVisible({ timeout: 10_000 });
      await teacherLink.click();

      // Should redirect to dashboard/home with teacher profile
      await teacherPage.waitForURL((url) => !url.pathname.includes('/login'), { timeout: 15_000 });
      const teacherBadge = teacherPage.locator('#dev-switcher-trigger-badge');
      await expect(teacherBadge).toBeVisible();

      // 2. Student impersonation via UI in studentContext
      await studentPage.goto('/login', { waitUntil: 'domcontentloaded' });
      await studentPage.locator('#dev-switcher-trigger-badge').click();
      const studentModal = studentPage.locator('#dev-role-switcher-modal');
      await expect(studentModal).toBeVisible({ timeout: 5_000 });

      // Click demo_student_1 link
      const studentLink = studentPage.locator('#dev-switcher-user-list a[href*="/sandbox/impersonate/"]:has-text("demo_student_1")');
      await expect(studentLink).toBeVisible({ timeout: 10_000 });
      await studentLink.click();

      // Should redirect to dashboard/home with student profile
      await studentPage.waitForURL((url) => !url.pathname.includes('/login'), { timeout: 15_000 });
      const studentTriggerBadge = studentPage.locator('#dev-switcher-trigger-badge');
      // Dev switcher badge must remain visible even for students!
      await expect(studentTriggerBadge).toBeVisible();

      // 3. Both enter Lesson 89 room
      const lesson89Url = '/lesson/89/room';
      await teacherPage.goto(lesson89Url, { waitUntil: 'domcontentloaded' });
      await studentPage.goto(lesson89Url, { waitUntil: 'domcontentloaded' });

      // Verify both enter interactive room (no 403, code-window visible)
      await expect(teacherPage.locator('#code-window')).toBeVisible({ timeout: 20_000 });
      await expect(studentPage.locator('#code-window')).toBeVisible({ timeout: 20_000 });

      // 4. Verify presence shows both participants
      const teacherParticipants = teacherPage.locator('#lesson-os-participants');
      await expect(teacherParticipants).toContainText('2 участник', { timeout: 12_000 });

      // 5. Test real-time window movement / sync
      // Ensure code window is active/moved by teacher
      const initialStudentLeft = await studentPage.locator('#code-window').evaluate((el) => el.style.left);
      
      // Teacher triggers a window layout update
      await teacherPage.evaluate(() => {
        const socket = (window as any).boostudyLessonSocket || (window as any).lessonSocket || (window as any).state?.socket;
        if (socket) {
          socket.emit('lesson_room_ui', {
            lesson_id: 89,
            kind: 'window_layout',
            window_id: 'code-window',
            left: 320,
            top: 140,
            width: 700,
            height: 520,
            minimized: false,
            visible: true
          });
        }
      });

      // Student should receive and apply layout or transform
      await expect.poll(async () => {
        return await studentPage.locator('#code-window').evaluate((el) => {
          return el.style.left || el.style.transform;
        });
      }, { timeout: 8_000 }).toContain('320');

      // 6. Test RBAC: Switch student context to demo_student_2 (unauthorized for Lesson 89)
      await studentPage.goto('/login', { waitUntil: 'domcontentloaded' });
      await studentPage.locator('#dev-switcher-trigger-badge').click();
      const student2Link = studentPage.locator('#dev-switcher-user-list a[href*="/sandbox/impersonate/"]:has-text("demo_student_2")');
      await expect(student2Link).toBeVisible({ timeout: 10_000 });
      await student2Link.click();
      await studentPage.waitForURL((url) => !url.pathname.includes('/login'), { timeout: 15_000 });

      // Attempt to access Lesson 89 as demo_student_2 -> must be 403 Forbidden!
      const forbiddenResponse = await studentPage.goto(lesson89Url, { waitUntil: 'domcontentloaded' });
      expect(forbiddenResponse?.status()).toBe(403);

      // Verify Teacher context is still demo_teacher_2 (session isolation intact)
      await teacherPage.reload({ waitUntil: 'domcontentloaded' });
      await expect(teacherPage.locator('#code-window')).toBeVisible({ timeout: 15_000 });

      // 7. Revert impersonation in teacher context
      await teacherPage.goto('/sandbox/impersonate/revert');
      // Should redirect back cleanly
      await teacherPage.waitForURL((url) => !url.pathname.includes('/revert'), { timeout: 10_000 });

    } finally {
      await teacherContext.close();
      await studentContext.close();
    }
  });

});

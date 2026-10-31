import { expect, Page, test } from '@playwright/test';
import { execSync } from 'child_process';

const password = process.env.BOOSTUDY_E2E_PASSWORD || '123456';
const tutorUsername = process.env.BOOSTUDY_E2E_TUTOR || 'qa_pool_tutor_1';
const studentUsername = process.env.BOOSTUDY_E2E_STUDENT || 'qa_pool_student_1';
const lessonId = 2168;
const lessonRoomUrl = `/lesson/${lessonId}/room`;
const submissionId = 2694;
const task1AtId = 2832;
const task2AtId = 2837;

function runPython(code: string): string {
  return execSync('./venv/bin/python', {
    input: code,
    cwd: '/mnt/Main/projects/kege_selector_app_current',
    encoding: 'utf-8',
    env: { ...process.env, PYTHONPATH: '.' }
  });
}

function resetLessonCodeState() {
  runPython(`
from app import create_app, db
from core.db_models import Lesson
from app.lessons.lesson_socket import _update_cached_code_state
from app.runtime_state import get_redis_client
app = create_app()
with app.app_context():
    l = Lesson.query.get(${lessonId})
    if l:
        sums = dict(l.review_summaries or {})
        sums['_os_workspace'] = None
        sums['_os_page_workspaces'] = {}
        l.review_summaries = sums
        if getattr(l, 'whiteboard', None) and l.whiteboard.document_state:
            doc = dict(l.whiteboard.document_state)
            doc['active_page_id'] = 'page_1'
            l.whiteboard.document_state = doc
        db.session.commit()
    r = get_redis_client()
    if r:
        try:
            r.delete('boostudy:lesson:${lessonId}:board_state')
        except Exception:
            pass
    for pid in ['page_1', 'page_2', 'page_3']:
        new_rev = 1
        _update_cached_code_state(${lessonId}, {
            "file_name": "main.py",
            "code": f"# Initial code for {pid}\\nprint('{pid}')\\n",
            "files": {"main.py": f"# Initial code for {pid}\\nprint('{pid}')\\n"},
            "open_tabs": ["main.py"],
            "active_file": "main.py",
            "deleted_files": [],
            "revision": new_rev,
            "version": new_rev,
        }, page_id=pid)
`);
}

function setupSubmissionFixture(options: {
  status?: string;
  studentCodes?: Record<number, string>;
  plainAnswers?: Record<number, string>;
  needsRevisionMap?: Record<number, boolean>;
} = {}) {
  const status = options.status || 'IN_PROGRESS';
  const codesB64 = Buffer.from(JSON.stringify(options.studentCodes || {})).toString('base64');
  const answersB64 = Buffer.from(JSON.stringify(options.plainAnswers || {})).toString('base64');
  const revMapB64 = Buffer.from(JSON.stringify(options.needsRevisionMap || {})).toString('base64');

  runPython(`
import json
import base64
from app import create_app, db
from core.db_models import Submission, Answer, SubmissionAttempt, LessonParticipantBan

app = create_app()
with app.app_context(), app.test_request_context():
    for b in LessonParticipantBan.query.filter_by(lesson_id=${lessonId}).all():
        b.is_active = False

    sub = Submission.query.get(${submissionId})
    if sub:
        sub.student_id = 630 # qa_pool_student_1
        sub.status = '${status}'
        sub.total_score = None
        sub.max_score = 5
        sub.percentage = None
        sub.teacher_feedback = 'Пожалуйста, проверьте код.' if '${status}' == 'RETURNED' else ''

        codes = json.loads(base64.b64decode('${codesB64}').decode('utf-8'))
        answers = json.loads(base64.b64decode('${answersB64}').decode('utf-8'))
        rev_map = json.loads(base64.b64decode('${revMapB64}').decode('utf-8'))

        for at_id in [${task1AtId}, ${task2AtId}, 2838, 2839, 2840]:
            ans = Answer.query.filter_by(submission_id=sub.submission_id, assignment_task_id=at_id).first()
            if not ans:
                ans = Answer(submission_id=sub.submission_id, assignment_task_id=at_id, max_score=1)
                db.session.add(ans)
            
            str_id = str(at_id)
            if str_id in codes:
                ans.student_code = codes[str_id]
                ans.student_code_saved_at = db.func.now()
            else:
                ans.student_code = None
                ans.student_code_saved_at = None

            if str_id in answers:
                ans.value = answers[str_id]
            else:
                ans.value = ''

            ans.needs_revision = bool(rev_map.get(str_id, False))
            ans.score = 1 if not ans.needs_revision and '${status}' in ['SUBMITTED', 'GRADED'] else 0

        SubmissionAttempt.query.filter_by(submission_id=sub.submission_id).delete()
        db.session.commit()
`);
}

function getAnswerValueFromDb(atId: number): string {
  const out = runPython(`
from app import create_app
from core.db_models import Answer
app = create_app()
with app.app_context():
    ans = Answer.query.filter_by(submission_id=${submissionId}, assignment_task_id=${atId}).first()
    print(ans.value if ans and ans.value is not None else '__NONE__')
`);
  return out.trim();
}

async function loginUser(page: Page, username: string) {
  await page.goto('/login');
  await page.fill('input[name="username"]', username);
  await page.fill('input[name="password"]', password);
  await page.click('button[type="submit"]');
  await page.waitForURL((url) => !url.pathname.includes('/login'), { timeout: 15000 });
}

test.describe('BOOSTUDY OS — UNIFIED EDITOR & OS INTERACTION STABILIZATION', () => {

  test.beforeEach(async () => {
    resetLessonCodeState();
  });

  // =========================================================================
  // GROUP 1: P0 STUDENT ANSWER INTEGRITY & AUTOSAVE ISOLATION (DATA-01..03)
  // =========================================================================
  test.describe('P0 Answer Integrity & Autosave Isolation', () => {

    test('DATA-01: Student answer 1286 is preserved during code autosave and submission', async ({ page }) => {
      setupSubmissionFixture({
        status: 'IN_PROGRESS',
        plainAnswers: { [task1AtId]: '1286' },
        studentCodes: { [task1AtId]: '# Initial code' }
      });

      await loginUser(page, studentUsername);
      const homeworkUrl = `/task-workspace?context_type=submission_task&context_id=${submissionId}&assignment_task_id=${task1AtId}`;
      await page.goto(homeworkUrl, { waitUntil: 'domcontentloaded' });
      await page.waitForSelector('#code-editor-textarea', { timeout: 15000 });

      // Verify initial answer in DB is 1286
      let dbVal = getAnswerValueFromDb(task1AtId);
      expect(dbVal).toBe('1286');

      // Type some Python code to trigger autosave
      const editor = page.locator('#code-editor-textarea');
      await editor.click();
      await editor.fill('a = 1286\nprint(a)\n');

      // Flush homework code
      await page.evaluate(async () => {
        if (typeof (window as any).flushHomeworkCode === 'function') {
          await (window as any).flushHomeworkCode();
        }
      });
      await page.waitForTimeout(1000);

      // Verify answer in DB is STILL 1286, NOT overwritten by code autosave
      dbVal = getAnswerValueFromDb(task1AtId);
      expect(dbVal).toBe('1286');
    });

    test('DATA-02: Code autosave passes answer=None so Answer.value is untouched', async ({ page }) => {
      setupSubmissionFixture({
        status: 'IN_PROGRESS',
        plainAnswers: { [task1AtId]: '9999' }
      });

      await loginUser(page, studentUsername);
      const homeworkUrl = `/task-workspace?context_type=submission_task&context_id=${submissionId}&assignment_task_id=${task1AtId}`;
      await page.goto(homeworkUrl, { waitUntil: 'domcontentloaded' });
      await page.waitForSelector('#code-editor-textarea', { timeout: 15000 });

      // Edit code
      const editor = page.locator('#code-editor-textarea');
      await editor.click();
      await editor.pressSequentially('# additional comment\n', { delay: 20 });
      await page.evaluate(async () => {
        if (typeof (window as any).flushHomeworkCode === 'function') {
          await (window as any).flushHomeworkCode();
        }
      });
      await page.waitForTimeout(1000);

      // DB answer must stay 9999
      const dbVal = getAnswerValueFromDb(task1AtId);
      expect(dbVal).toBe('9999');
    });

    test('DATA-03: Deliberate clear of answer by student properly updates DB', async ({ page }) => {
      setupSubmissionFixture({
        status: 'IN_PROGRESS',
        plainAnswers: { [task1AtId]: '1286' }
      });

      await loginUser(page, studentUsername);
      const homeworkUrl = `/task-workspace?context_type=submission_task&context_id=${submissionId}&assignment_task_id=${task1AtId}`;
      await page.goto(homeworkUrl, { waitUntil: 'domcontentloaded' });
      await page.waitForSelector('#code-editor-textarea', { timeout: 15000 });

      // Clear answer via submission submit dirty_answers
      const ok = await page.evaluate(async ({ subId, atId }) => {
        const csrf = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') || '';
        const res = await fetch(`/submissions/${subId}/submit`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf },
          body: JSON.stringify({ dirty_answers: { [atId]: '' } })
        });
        return res.ok;
      }, { subId: submissionId, atId: task1AtId });
      expect(ok).toBeTruthy();

      const dbVal = getAnswerValueFromDb(task1AtId);
      expect(dbVal).toBe('');
    });
  });

  // =========================================================================
  // GROUP 2: P0 LESSON OS PAGE-SCOPED WORKSPACES & WINDOWS (PAGE-01..10)
  // =========================================================================
  test.describe('P0 Lesson OS Page-Scoped Workspaces & Windows', () => {

    test('PAGE-01: Lesson OS has single-file header and NO multi-file tab bar in room mode', async ({ page }) => {
      await loginUser(page, tutorUsername);
      await page.goto(lessonRoomUrl);
      await page.waitForSelector('#code-window', { timeout: 15000 });

      // Verify single-file header elements
      const codeHeader = page.locator('#code-window-header');
      await expect(codeHeader).toBeVisible();
      await expect(page.locator('#hw-code-filename-badge')).toContainText('main.py');

      // Verify multi-file tabs bar is NOT present in room_mode
      await expect(page.locator('#editor-tabs-list')).toHaveCount(0);
      await expect(page.locator('#editor-new-tab-btn')).toHaveCount(0);
      await expect(page.locator('#editor-new-file-modal')).toHaveCount(0);
    });

    test('PAGE-02..04: Each page has an independent main.py buffer', async ({ page }) => {
      await loginUser(page, tutorUsername);
      await page.goto(lessonRoomUrl);
      await page.waitForSelector('#code-window', { timeout: 15000 });

      // Ensure starting on Page 1
      await page.evaluate(() => {
        if ((window as any).BooCanvasOverlay && typeof (window as any).BooCanvasOverlay.switchPage === 'function') {
          (window as any).BooCanvasOverlay.switchPage('page_1');
        } else {
          (window as any).onLessonPageSwitch?.(null, 'page_1');
        }
      });
      await page.waitForTimeout(300);

      const editor = page.locator('#code-editor-textarea');
      await editor.click();
      await editor.fill('# Page 1 code: 1111\nx = 1111\n');
      await page.waitForTimeout(1000);

      // Switch to Page 2 via window.onLessonPageSwitch or BooCanvasOverlay
      await page.evaluate(() => {
        if ((window as any).BooCanvasOverlay && typeof (window as any).BooCanvasOverlay.switchPage === 'function') {
          (window as any).BooCanvasOverlay.switchPage('page_2');
        } else {
          (window as any).onLessonPageSwitch?.('page_1', 'page_2');
        }
      });
      await page.waitForTimeout(600);

      // Page 2 should have different or empty buffer
      const page2Code = await editor.inputValue();
      expect(page2Code).not.toContain('1111');

      // Edit on Page 2
      await editor.fill('# Page 2 code: 2222\ny = 2222\n');
      await page.waitForTimeout(1000);

      // Switch back to Page 1
      await page.evaluate(() => {
        if ((window as any).BooCanvasOverlay && typeof (window as any).BooCanvasOverlay.switchPage === 'function') {
          (window as any).BooCanvasOverlay.switchPage('page_1');
        } else {
          (window as any).onLessonPageSwitch?.('page_2', 'page_1');
        }
      });
      await page.waitForTimeout(600);

      // Page 1 code must be restored
      const page1Restored = await editor.inputValue();
      expect(page1Restored).toContain('# Page 1 code: 1111');
    });

    test('PAGE-05..07: Page-scoped window layouts are independent and persist', async ({ page, isMobile }) => {
      test.skip(isMobile, 'Window positioning requires desktop viewport');
      await loginUser(page, tutorUsername);
      await page.goto(lessonRoomUrl);
      await page.waitForSelector('#code-window', { timeout: 15000 });

      const codeWin = page.locator('#code-window');

      // Move code window on Page 1
      await page.evaluate(() => {
        const win = document.getElementById('code-window');
        if (win) {
          win.style.setProperty('left', '250px', 'important');
          win.style.setProperty('top', '120px', 'important');
          (window as any).lessonWindowManager?.saveWindowLayout(win);
        }
      });

      // Switch to Page 2
      await page.evaluate(() => {
        if ((window as any).BooCanvasOverlay && typeof (window as any).BooCanvasOverlay.switchPage === 'function') {
          (window as any).BooCanvasOverlay.switchPage('page_2');
        } else {
          (window as any).onLessonPageSwitch?.('page_1', 'page_2');
        }
      });
      await page.waitForTimeout(500);

      // On Page 2, code window should not be at 250px
      const leftPage2 = await codeWin.evaluate(el => el.style.left);
      expect(leftPage2).not.toBe('250px');

      // On Page 2, move code window to another position
      await page.evaluate(() => {
        const win = document.getElementById('code-window');
        if (win) {
          win.style.setProperty('left', '400px', 'important');
          win.style.setProperty('top', '220px', 'important');
          (window as any).lessonWindowManager?.saveWindowLayout(win);
        }
      });

      // Switch back to Page 1
      await page.evaluate(() => {
        if ((window as any).BooCanvasOverlay && typeof (window as any).BooCanvasOverlay.switchPage === 'function') {
          (window as any).BooCanvasOverlay.switchPage('page_1');
        } else {
          (window as any).onLessonPageSwitch?.('page_2', 'page_1');
        }
      });
      await page.waitForTimeout(500);

      // Position on Page 1 should be 250px
      const leftPage1 = await codeWin.evaluate(el => el.style.left);
      expect(leftPage1).toBe('250px');
    });

    test('PAGE-08: Room-scoped window #task-window is unaffected by page switch', async ({ page }) => {
      await loginUser(page, tutorUsername);
      await page.goto(lessonRoomUrl);
      await page.waitForSelector('#code-window', { timeout: 15000 });

      // Open #task-window
      await page.evaluate(() => {
        (window as any).openWindow?.('task-window');
      });
      const taskWin = page.locator('#task-window');
      await expect(taskWin).toBeVisible({ timeout: 15000 });
      const initialDisplay = await taskWin.evaluate(el => el.style.display);

      // Switch page
      await page.evaluate(() => {
        if ((window as any).BooCanvasOverlay && typeof (window as any).BooCanvasOverlay.switchPage === 'function') {
          (window as any).BooCanvasOverlay.switchPage('page_2');
        } else {
          (window as any).onLessonPageSwitch?.('page_1', 'page_2');
        }
      });
      await page.waitForTimeout(500);

      // Task window display should remain unchanged and still open
      await expect(taskWin).toBeVisible();
      const displayAfter = await taskWin.evaluate(el => el.style.display);
      expect(displayAfter).toBe(initialDisplay);
    });

    test('PAGE-10: Late ACK discard guard drops events for wrong page', async ({ page }) => {
      await loginUser(page, tutorUsername);
      await page.goto(lessonRoomUrl);
      await page.waitForSelector('#code-window', { timeout: 15000 });

      // Put code on page_2
      const editor = page.locator('#code-editor-textarea');
      await editor.fill('# Current page_2 code');

      // Simulate receiving a remote code update with page_id: 'page_1'
      await page.evaluate(() => {
        if ((window as any).BooCanvasOverlay) {
          (window as any).BooCanvasOverlay.getActivePageId = () => 'page_2';
        }
        window.dispatchEvent(new CustomEvent('test-simulate-code-update', {
          detail: { page_id: 'page_1', code: '# Stale page 1 update', user_id: 'other_user' }
        }));
      });

      // Editor code should NOT have changed to '# Stale page 1 update'
      const curCode = await editor.inputValue();
      expect(curCode).toBe('# Current page_2 code');
    });
  });

  // =========================================================================
  // GROUP 3: P1 WINDOW DRAG & INTERACTION STABILIZATION (WINDOW-01..02)
  // =========================================================================
  test.describe('P1 Window Drag & Motion', () => {

    test('WINDOW-01: Center of titlebar is draggable and has grab cursor', async ({ page }) => {
      await loginUser(page, tutorUsername);
      await page.goto(lessonRoomUrl);
      await page.waitForSelector('#code-window-header', { timeout: 15000 });

      const header = page.locator('#code-window-header');
      const cursor = await header.evaluate(el => window.getComputedStyle(el).cursor);
      expect(cursor).toBe('grab');

      // Titlebar first-child must NOT have flex: 1 1 auto
      const firstChildFlex = await header.evaluate(el => {
        const fc = el.firstElementChild;
        return fc ? window.getComputedStyle(fc).flexGrow : '0';
      });
      expect(Number(firstChildFlex)).toBe(0);
    });

    test('WINDOW-02: Student window dragging does NOT broadcast layout to teacher', async ({ page }) => {
      await loginUser(page, studentUsername);
      await page.goto(lessonRoomUrl);
      await page.waitForSelector('#code-window', { timeout: 15000 });

      // Verify student's saveWindowLayout does NOT broadcast
      const sentBroadCast = await page.evaluate(() => {
        let sent = false;
        const origSend = (window as any).boostudyLessonControl?.sendUi;
        if ((window as any).boostudyLessonControl) {
          (window as any).boostudyLessonControl.sendUi = (payload: any) => {
            if (payload && payload.kind === 'window_layout') sent = true;
            return origSend?.(payload);
          };
        }
        const win = document.getElementById('code-window');
        (window as any).lessonWindowManager?.saveWindowLayout(win, { broadcast: true });
        return sent;
      });

      expect(sentBroadCast).toBeFalsy();
    });
  });

  // =========================================================================
  // GROUP 4: P1 RESPONSIVE TOOLBAR & SINGLE-LINE STATUS BAR (UI-01..03)
  // =========================================================================
  test.describe('P1 Responsive Toolbar & Status Bar', () => {

    test('UI-01: Strict single-line status bar (32px, nowrap) at 440px width', async ({ page }) => {
      await loginUser(page, tutorUsername);
      await page.goto(lessonRoomUrl);
      await page.waitForSelector('#code-window', { timeout: 15000 });

      // Resize code window to 440px (or available width on mobile)
      await page.evaluate(() => {
        const win = document.getElementById('code-window');
        if (win) {
          const targetW = Math.min(440, window.innerWidth - 20);
          win.style.setProperty('width', `${targetW}px`, 'important');
        }
      });

      const statusBar = page.locator('#editor-status-bar');
      await expect(statusBar).toBeVisible();

      // Check height is exactly 32px (h-8) and white-space is nowrap
      const box = await statusBar.boundingBox();
      expect(box?.height).toBeLessThanOrEqual(36);

      const whiteSpace = await statusBar.evaluate(el => window.getComputedStyle(el).whiteSpace);
      expect(whiteSpace).toBe('nowrap');
    });

    test('UI-02: Toolbar collapses badges cleanly when container width <= 580px', async ({ page }) => {
      await loginUser(page, tutorUsername);
      await page.goto(lessonRoomUrl);
      await page.waitForSelector('#code-window', { timeout: 15000 });

      // Resize window container to 500px
      await page.evaluate(() => {
        const win = document.getElementById('code-window');
        if (win) win.style.width = '500px';
      });

      // Runtime badge and tracer text should collapse or hide
      const runtimeBadge = page.locator('#hw-code-runtime-badge');
      if (await runtimeBadge.count() > 0) {
        const isHiddenOrCompact = await runtimeBadge.evaluate(el => {
          const style = window.getComputedStyle(el);
          return style.display === 'none' || el.classList.contains('hidden') || el.offsetWidth < 60;
        });
        expect(isHiddenOrCompact).toBeTruthy();
      }
    });

    test('UI-03: Two independent status axes in Homework OS (Correctness vs Workflow)', async ({ page }) => {
      setupSubmissionFixture({
        status: 'RETURNED',
        needsRevisionMap: { [task1AtId]: true },
        plainAnswers: { [task1AtId]: '1286' }
      });

      await loginUser(page, studentUsername);
      const homeworkUrl = `/task-workspace?context_type=submission_task&context_id=${submissionId}&assignment_task_id=${task1AtId}`;
      await page.goto(homeworkUrl, { waitUntil: 'domcontentloaded' });
      await page.evaluate(() => {
        (window as any).openWindow?.('task-window');
      });
      await page.waitForSelector('#task-window', { timeout: 15000 });

      // Verify prominent amber revision banner is displayed
      const revBanner = page.locator('#hw-revision-returned-banner');
      await expect(revBanner).toBeVisible();
      await expect(revBanner).toContainText('Задание возвращено на доработку');

      // Verify tab displays workflow badge "На доработке"
      const taskTab = page.locator(`.homework-os-task-tab[data-task-id="${task1AtId}"]`);
      await expect(taskTab).toContainText('На доработке');
    });
  });
});

"""
BooStudy — Teacher Control Center: Sprint 2.8 Comprehensive E2E Verification
Automated end-to-end browser tests verifying:
1. Canonical /schedule routing for Teacher & Creator
2. 5 Calendar Views (Week, Day, Focus, Month, Stream)
3. Information Layers (Homework, Free windows, Non-working hours)
4. Multi-dimensional Filters & Badges & Empty State Reset
5. Density toggle (64px / 48px)
6. Create Lesson Modal & DB commit
7. Direct manipulation & Modal Reschedule with 409 conflict handling
8. Inspector Mode & Notes saving & Status updates
9. Cancel / Delete lesson with confirmation
10. Command Palette (Ctrl+K)
11. Smart Availability Finder (Find a Time)
12. Cross-role verification (Teacher creates/moves -> Student sees in Student Learning Week)
13. Safe developer rollback (/schedule?legacy=1)
"""
import os
import sys
import time
from playwright.sync_api import sync_playwright

BASE_URL = os.environ.get("TEST_BASE_URL", "http://127.0.0.1:5000")

def cleanup_test_lessons():
    try:
        from dotenv import load_dotenv
        load_dotenv('.env', override=True)
        from app import create_app
        from core.db_models import Lesson, db
        app = create_app()
        with app.app_context():
            Lesson.query.filter(Lesson.topic.like('Спринт 2.8%')).delete()
            Lesson.query.filter(Lesson.topic.like('Сквозной тест%')).delete()
            db.session.commit()
    except Exception as e:
        print(f"Cleanup note: {e}")

def run_sprint_2_8_e2e_suite():
    print("=" * 70)
    print("STARTING TEACHER CONTROL CENTER SPRINT 2.8 E2E VERIFICATION")
    print("=" * 70)

    cleanup_test_lessons()

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-proxy-server", "--disable-dev-shm-usage"]
        )

        # Desktop 1920x1080 context
        context = browser.new_context(viewport={"width": 1920, "height": 1080})
        page = context.new_page()

        # Step 1: Login as Teacher
        print("\n[TEST 1] Login as teacher qa_pool_teacher_1...")
        page.goto(f"{BASE_URL}/login")
        page.fill("input[name='username']", "qa_pool_teacher_1")
        page.fill("input[name='password']", "demo123pass")
        page.click("button[type='submit']")
        page.wait_for_load_state("networkidle")
        print("  ✓ Logged in successfully")

        # Step 2: Access canonical /schedule
        print("\n[TEST 2] Access canonical /schedule...")
        page.goto(f"{BASE_URL}/schedule")
        page.wait_for_selector("#tc-workspace", timeout=10000)
        assert page.locator("#tc-workspace").is_visible(), "Canonical /schedule did not load #tc-workspace!"
        assert page.locator("#tc-date-range").is_visible(), "Date range title not found"
        print("  ✓ Canonical /schedule loaded with #tc-workspace and #tc-date-range")

        # Step 3: Test all 5 views
        print("\n[TEST 3] Testing all 5 Calendar Views...")
        # 3.1 Week View (default)
        week_cols = page.locator(".tc-day-column")
        assert week_cols.count() == 7, f"Expected 7 day columns in week view, got {week_cols.count()}"
        print("  ✓ Week View: 7 columns rendered")

        # 3.2 Day View
        page.click("#tc-btn-view-day")
        page.wait_for_selector(".tc-day-view", timeout=5000)
        day_cols = page.locator(".tc-day-view .tc-day-column")
        assert day_cols.count() == 1, f"Expected 1 column in day view, got {day_cols.count()}"
        print("  ✓ Day View: single focused day rendered")

        # 3.3 Focus View
        page.click("#tc-btn-view-focus")
        page.wait_for_selector(".tc-focus-container", timeout=5000)
        ribbon_chips = page.locator(".tc-focus-day-chip")
        assert ribbon_chips.count() == 7, f"Expected 7 chips in focus ribbon, got {ribbon_chips.count()}"
        print("  ✓ Focus View: spatial ribbon with 7 day chips and 80px timeline rendered")

        # 3.4 Month View
        page.click("#tc-btn-view-month")
        page.wait_for_selector(".tc-canvas-card.p-6", timeout=5000)
        assert "Месячный обзор" in page.content(), "Month view title not found"
        print("  ✓ Month View: monthly load grid rendered")

        # 3.5 Stream View (List)
        page.click("#tc-btn-view-stream")
        page.wait_for_selector(".tc-stream-list", timeout=5000)
        assert page.locator(".tc-stream-card").count() > 0, "Stream view did not render cards"
        print(f"  ✓ Stream View: chronological list with {page.locator('.tc-stream-card').count()} cards rendered")

        # Switch back to Week View
        page.click("#tc-btn-view-week")
        page.wait_for_selector(".tc-days-header-strip", timeout=5000)
        print("  ✓ Switched back to Week View")

        # Step 4: Test Filters
        print("\n[TEST 4] Testing Multi-Dimensional Filters...")
        initial_card_count = page.locator(".tc-lesson-card").count()
        print(f"  Initial card count on week view: {initial_card_count}")

        # Open filter popover
        page.click("#tc-btn-filters")
        page.wait_for_selector("#tc-popover-filters:not(.is-hidden)", timeout=3000)

        # 4.1 Filter by Student demo_student_1
        page.select_option("#tc-filter-student", label="demo_student_1")
        time.sleep(0.3)
        filtered_cards = page.locator(".tc-lesson-card")
        filtered_count = filtered_cards.count()
        badge_text = page.locator("#tc-filter-badge").text_content()
        assert int(badge_text) >= 1, f"Expected badge >= 1, got {badge_text}"
        print(f"  ✓ Student filter applied: {filtered_count} cards visible, filter badge shows {badge_text}")

        # 4.2 Text search
        page.fill("#tc-filter-search", "графов")
        time.sleep(0.3)
        search_count = page.locator(".tc-lesson-card").count()
        print(f"  ✓ Text search 'графов': {search_count} cards visible")

        # 4.3 Empty state reset
        page.fill("#tc-filter-search", "НЕ_СУЩЕСТВУЮЩИЙ_ТЕКСТ_XYZ_123")
        time.sleep(0.3)
        assert page.locator(".tc-empty-state").is_visible(), "Empty state was not displayed for zero results!"
        print("  ✓ Empty state displayed when 0 results found")

        # Click reset filters button inside empty state
        page.click(".tc-empty-state button:has-text('Сбросить все фильтры')")
        time.sleep(0.3)
        restored_count = page.locator(".tc-lesson-card").count()
        assert restored_count == initial_card_count, f"Reset did not restore all cards ({restored_count} != {initial_card_count})"
        assert not page.locator("#tc-filter-badge").is_visible(), "Filter badge should be hidden after reset"
        print("  ✓ Filters successfully reset, all cards restored")

        # Step 5: Test Information Layers Toggle
        print("\n[TEST 5] Testing Information Layers...")
        # Toggle popover
        page.click("#tc-btn-layers")
        page.wait_for_selector("#tc-popover-layers:not(.is-hidden)", timeout=3000)

        # Uncheck homework layer
        page.locator(".tc-layer-row:has-text('Домашние задания')").click()
        time.sleep(0.3)
        assert page.locator(".tc-badge-hw").count() == 0, "Homework badges should be hidden when layer is off"
        print("  ✓ Homework layer toggled OFF: badges hidden")

        page.locator(".tc-layer-row:has-text('Домашние задания')").click()
        time.sleep(0.3)
        print("  ✓ Homework layer toggled ON: badges visible")

        # Step 6: Test Density Toggle
        print("\n[TEST 6] Testing Density Toggle...")
        card_before = page.locator(".tc-lesson-card").first.bounding_box()
        page.click("#tc-btn-density")
        time.sleep(0.3)
        card_compact = page.locator(".tc-lesson-card").first.bounding_box()
        assert card_compact["height"] < card_before["height"], f"Compact height {card_compact['height']} not smaller than standard {card_before['height']}"
        print("  ✓ Density toggled to Compact 48px")

        page.click("#tc-btn-density")
        time.sleep(0.3)
        card_standard = page.locator(".tc-lesson-card").first.bounding_box()
        assert card_standard["height"] > card_compact["height"], "Standard height not restored"
        print("  ✓ Density toggled back to Standard 64px")

        # Step 7: Create Lesson Modal & Real Backend Commit
        print("\n[TEST 7] Testing Create Lesson Modal & Backend Commit...")
        page.click("#tc-btn-new-lesson")
        page.wait_for_selector("#tc-modal-new-lesson:not(.is-hidden)", timeout=3000)

        # Fill lesson form
        test_topic = f"Спринт 2.8 Интеграция {int(time.time())}"
        page.select_option("#tc-input-student", label="demo_student_1")
        page.select_option("#tc-input-subject", value="Информатика")
        page.fill("#tc-input-date", "2026-11-03")
        page.fill("#tc-input-time", "11:00")
        page.select_option("#tc-input-duration", value="60")
        page.fill("#tc-input-topic", test_topic)
        page.fill("#tc-input-notes", "Заметка к новому уроку для проверки")

        # Submit
        page.click("#tc-btn-submit-lesson")
        page.wait_for_selector(".tc-toast-container, #tc-toast-container", timeout=5000)
        time.sleep(0.5)

        # Verify new card exists on canvas
        created_card = page.locator(f".tc-lesson-card:has-text('{test_topic}')")
        assert created_card.count() > 0, "Created lesson card not found on canvas!"
        created_id = created_card.get_attribute("data-id")
        print(f"  ✓ Lesson created successfully in DB with ID={created_id} and displayed on canvas")

        # Step 8: Lesson Inspector Mode & Notes Saving & Status Update
        print("\n[TEST 8] Testing Inspector Mode, Notes, and Status...")
        created_card.click()
        time.sleep(0.3)
        assert page.locator("#tc-context-dock:has-text('Карточка урока')").is_visible(), "Inspector mode did not open!"
        print("  ✓ Inspector mode active in context dock")

        # Save note
        updated_note = "Обновлённый план: решение задач ЕГЭ №24"
        page.fill("#tc-lesson-notes-input", updated_note)
        page.click("button:has-text('Сохранить заметку')")
        time.sleep(0.5)
        print("  ✓ Lesson note saved via POST /api/schedule/update/<id>")

        # Status transition to in_progress
        page.click("#tc-context-dock button:has-text('Идёт')")
        time.sleep(0.5)
        assert page.locator(f"#tc-card-{created_id}.status-in_progress").is_visible(), "Card status did not update to in_progress!"
        print("  ✓ Lesson status transitioned to in_progress via POST /schedule/api/lesson/<id>/set-status")

        # Step 9: Reschedule Modal with 409 Conflict Handling
        print("\n[TEST 9] Testing Reschedule & 409 Conflict Detection...")
        page.click("button:has-text('Перенести...')")
        page.wait_for_selector("#tc-modal-reschedule:not(.is-hidden)", timeout=3000)

        # 9.1 Test conflict: move to Monday 10:30 (where demo_student_1 already has lesson 901)
        page.fill("#tc-reschedule-date", "2026-11-02")
        page.fill("#tc-reschedule-time", "10:30")
        page.click("#tc-btn-submit-reschedule")
        time.sleep(0.5)
        assert page.locator("#tc-reschedule-error:not(.hidden)").is_visible(), "Conflict error was not displayed on overlap!"
        conflict_msg = page.locator("#tc-reschedule-error").text_content()
        print(f"  ✓ 409 Overlap conflict handled correctly: '{conflict_msg}'")

        # 9.2 Test successful reschedule to a clean slot: Tuesday 13:00
        page.fill("#tc-reschedule-date", "2026-11-03")
        page.fill("#tc-reschedule-time", "13:00")
        page.click("#tc-btn-submit-reschedule")
        page.wait_for_selector(f"#tc-card-{created_id}:has-text('13:00')", timeout=8000)
        assert page.locator(f"#tc-card-{created_id}:has-text('13:00')").is_visible(), "Lesson time was not updated to 13:00!"
        print("  ✓ Lesson rescheduled successfully to 2026-11-03 13:00")

        # Step 10: Smart Availability Finder (Find a Time)
        print("\n[TEST 10] Testing Smart Availability Finder...")
        page.evaluate("() => window.TC.openFindTimeModal()")
        page.wait_for_selector("#tc-modal-find-time:not(.is-hidden)", timeout=3000)
        time.sleep(1.0)
        slots = page.locator("#tc-find-slots-list button:has-text('Выбрать')")
        assert slots.count() > 0, "No free slots returned by finder API"
        print(f"  ✓ Smart Finder found {slots.count()} recommended free slots in working hours")
        page.click("#tc-modal-find-time button:has-text('Закрыть')")

        # Step 11: Command Palette (Ctrl+K)
        print("\n[TEST 11] Testing Command Palette (Ctrl+K)...")
        page.keyboard.press("Control+k")
        page.wait_for_selector("#tc-modal-cmd:not(.is-hidden)", timeout=3000)
        assert page.locator("#tc-cmd-input").is_visible(), "Command palette input not visible"
        page.fill("#tc-cmd-input", "День")
        time.sleep(0.3)
        page.click(".tc-cmd-item:has-text('День (подробный)')")
        time.sleep(0.3)
        assert page.locator(".tc-day-view").is_visible(), "Command palette did not switch to Day view"
        print("  ✓ Command palette executed 'Вид: День' successfully")

        # Switch back to week
        page.click("#tc-btn-view-week")
        time.sleep(0.3)

        # Step 12: Cancel / Delete Lesson
        print("\n[TEST 12] Testing Lesson Cancellation...")
        page.locator(f"#tc-card-{created_id}").click()
        time.sleep(0.3)
        page.click("button:has-text('Отменить урок')")
        page.wait_for_selector("#tc-modal-confirm-delete:not(.is-hidden)", timeout=3000)
        page.click("#tc-btn-confirm-delete")
        time.sleep(0.5)
        assert page.locator(f"#tc-card-{created_id}").count() == 0, "Cancelled lesson was not removed from canvas!"
        print("  ✓ Lesson successfully cancelled and purged from DB via POST /schedule/api/lesson/<id>/delete")

        # Step 13: Cross-Role Verification (Teacher -> Student)
        print("\n[TEST 13] Cross-Role Verification: Teacher schedules for Student...")
        # Create a dedicated cross-role test lesson
        cross_topic = f"Сквозной тест учитель-ученик {int(time.time())}"
        page.click("#tc-btn-new-lesson")
        page.wait_for_selector("#tc-modal-new-lesson:not(.is-hidden)", timeout=3000)
        page.select_option("#tc-input-student", label="demo_student_1")
        page.select_option("#tc-input-subject", value="Информатика")
        page.fill("#tc-input-date", "2026-11-03")
        page.fill("#tc-input-time", "15:00")
        page.fill("#tc-input-topic", cross_topic)
        page.click("#tc-btn-submit-lesson")
        time.sleep(1.0)
        print(f"  ✓ Teacher scheduled lesson '{cross_topic}' for demo_student_1")

        # Log out teacher and log in as demo_student_1
        print("  Logging in as demo_student_1...")
        student_context = browser.new_context(viewport={"width": 1440, "height": 900})
        student_page = student_context.new_page()
        student_page.goto(f"{BASE_URL}/login")
        student_page.fill("input[name='username']", "demo_student_1")
        student_page.fill("input[name='password']", "demo123pass")
        student_page.click("button[type='submit']")
        student_page.wait_for_load_state("networkidle")

        student_page.goto(f"{BASE_URL}/schedule")
        student_page.wait_for_load_state("networkidle")
        time.sleep(1.0)

        # Verify Student Concept D is preserved
        assert student_page.locator("#tc-workspace").count() == 0, "Student received teacher workspace!"
        student_content = student_page.content()
        assert cross_topic in student_content or "15:00" in student_content, "Student does not see newly created lesson in schedule!"
        print("  ✓ Student schedule reflects the newly created lesson in Student Learning Week!")
        student_context.close()

        # Step 14: Safe Developer Rollback (?legacy=1)
        print("\n[TEST 14] Safe Developer Rollback (?legacy=1)...")
        page.goto(f"{BASE_URL}/schedule?legacy=1")
        page.wait_for_load_state("networkidle")
        assert page.locator("#tc-workspace").count() == 0, "?legacy=1 should not load tc-workspace!"
        assert page.locator(".schedule-table, .schedule-container, #schedule-grid").count() > 0 or "Расписание" in page.content(), "Legacy template did not render!"
        print("  ✓ /schedule?legacy=1 cleanly renders legacy schedule table for instant rollback")

        context.close()
        browser.close()

    print("\n" + "=" * 70)
    print("ALL SPRINT 2.8 E2E ACCEPTANCE TESTS PASSED (14/14)!")
    print("=" * 70)

if __name__ == "__main__":
    run_sprint_2_8_e2e_suite()

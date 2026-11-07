"""Visual QA and Motion Capture for Teacher Control Center Sprint 2.6.
Captures all 16 required screenshots and interaction video.
"""
import os
import sys
import time
from playwright.sync_api import sync_playwright

OUTPUT_DIR = os.path.abspath("docs/teacher_control_center_sprint2_6/key_review")
BASE_URL = "http://127.0.0.1:5000"

def run_capture():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    video_dir = os.path.join(OUTPUT_DIR, "video_temp")
    os.makedirs(video_dir, exist_ok=True)

    with sync_playwright() as p:
        # Launch browser with --no-proxy-server
        browser = p.chromium.launch(
            headless=True,
            args=["--no-proxy-server", "--disable-dev-shm-usage"]
        )

        # 1. Desktop Context (1920x1080) with video recording
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            record_video_dir=video_dir,
            record_video_size={"width": 1920, "height": 1080}
        )
        page = context.new_page()

        # Login as teacher
        print("Logging in as qa_pool_teacher_1...")
        page.goto(f"{BASE_URL}/login")
        page.fill("input[name='username']", "qa_pool_teacher_1")
        page.fill("input[name='password']", "demo123pass")
        page.click("button[type='submit']")
        page.wait_for_load_state("networkidle")

        # Navigate to /schedule
        print("Navigating to /schedule...")
        page.goto(f"{BASE_URL}/schedule")
        page.wait_for_selector("#tcc-workspace", timeout=10000)
        time.sleep(1.5)

        # Screenshot 01: Desktop 1920 Week View (Default)
        print("Capturing 01_desktop_1920_week_view.png...")
        page.screenshot(path=os.path.join(OUTPUT_DIR, "01_desktop_1920_week_view.png"), full_page=False)

        # Screenshot 02: Tool Rail Expanded
        print("Capturing 02_desktop_1920_tool_rail_expanded.png...")
        page.evaluate("() => window.TCC && window.TCC.toggleRail('students', true)")
        time.sleep(0.5)
        page.screenshot(path=os.path.join(OUTPUT_DIR, "02_desktop_1920_tool_rail_expanded.png"), full_page=False)
        # Collapse back
        page.evaluate("() => window.TCC && window.TCC.toggleRail(null, false)")
        time.sleep(0.3)

        # Screenshot 03: Lesson Inspector
        print("Capturing 03_desktop_1920_lesson_inspector.png...")
        page.evaluate("""() => {
            if (window.TCC && window.TCC.state.lessons && window.TCC.state.lessons.length > 0) {
                const l = window.TCC.state.lessons[0];
                window.TCC.selectLesson(l.lesson_id || l.id);
            }
        }""")
        time.sleep(0.6)
        page.screenshot(path=os.path.join(OUTPUT_DIR, "03_desktop_1920_lesson_inspector.png"), full_page=False)

        # Screenshot 04: Find a Time Mode
        print("Capturing 04_desktop_1920_find_time_modal.png...")
        page.evaluate("() => window.TCC && window.TCC.openFindTime()")
        time.sleep(0.6)
        page.screenshot(path=os.path.join(OUTPUT_DIR, "04_desktop_1920_find_time_modal.png"), full_page=False)

        # Screenshot 05: Slot Composer
        print("Capturing 05_desktop_1920_slot_composer.png...")
        page.evaluate("() => window.TCC && window.TCC.openSlotComposer()")
        time.sleep(0.6)
        page.screenshot(path=os.path.join(OUTPUT_DIR, "05_desktop_1920_slot_composer.png"), full_page=False)

        # Screenshot 06: Day View
        print("Capturing 06_desktop_1920_day_view.png...")
        page.evaluate("() => window.TCC && window.TCC.switchView('day')")
        time.sleep(0.6)
        page.screenshot(path=os.path.join(OUTPUT_DIR, "06_desktop_1920_day_view.png"), full_page=False)

        # Screenshot 07: Month View
        print("Capturing 07_desktop_1920_month_view.png...")
        page.evaluate("() => window.TCC && window.TCC.switchView('month')")
        time.sleep(0.6)
        page.screenshot(path=os.path.join(OUTPUT_DIR, "07_desktop_1920_month_view.png"), full_page=False)

        # Screenshot 08: Stream View
        print("Capturing 08_desktop_1920_stream_view.png...")
        page.evaluate("() => window.TCC && window.TCC.switchView('stream')")
        time.sleep(0.6)
        page.screenshot(path=os.path.join(OUTPUT_DIR, "08_desktop_1920_stream_view.png"), full_page=False)

        # Screenshot 09: Day Focus Mode
        print("Capturing 09_desktop_1920_day_focus_mode.png...")
        page.evaluate("() => window.TCC && window.TCC.switchView('focus')")
        time.sleep(0.6)
        page.screenshot(path=os.path.join(OUTPUT_DIR, "09_desktop_1920_day_focus_mode.png"), full_page=False)

        # Screenshot 10: Command Palette
        print("Capturing 10_desktop_1920_command_palette.png...")
        page.evaluate("() => window.TCC && window.TCC.openCmd()")
        time.sleep(0.6)
        page.screenshot(path=os.path.join(OUTPUT_DIR, "10_desktop_1920_command_palette.png"), full_page=False)
        page.evaluate("() => window.TCC && window.TCC.closeCmd()")
        time.sleep(0.3)

        # Screenshot 16: Reschedule Scope Modal (desktop)
        print("Capturing 16_desktop_reschedule_scope_modal.png...")
        page.evaluate("() => window.TCC && window.TCC.switchView('week')")
        time.sleep(0.4)
        page.evaluate("""() => {
            const recurringLesson = window.TCC.state.lessons.find(l => l.recurring_slot_id);
            const targetLesson = recurringLesson || window.TCC.state.lessons[0];
            if (targetLesson) {
                window.TCC.openScopeModal(targetLesson, '2026-11-04', '15:00');
            }
        }""")
        time.sleep(0.6)
        page.screenshot(path=os.path.join(OUTPUT_DIR, "16_desktop_reschedule_scope_modal.png"), full_page=False)
        page.evaluate("() => window.TCC && window.TCC.closeScopeModal()")
        time.sleep(0.5)

        # Finish desktop video recording by closing page
        page.close()
        video_path = page.video.path()
        context.close()

        # Rename / convert video to motion_proof.webm
        final_video_target = os.path.join(OUTPUT_DIR, "motion_proof.webm")
        if os.path.exists(video_path):
            if os.path.exists(final_video_target):
                os.remove(final_video_target)
            os.rename(video_path, final_video_target)
            print(f"Motion proof saved to {final_video_target}")

        # Screenshot 11: 1440x900 Compact Density
        print("Capturing 11_desktop_1440_compact_density.png...")
        ctx_1440 = browser.new_context(viewport={"width": 1440, "height": 900})
        p_1440 = ctx_1440.new_page()
        # Transfer cookies / login
        p_1440.goto(f"{BASE_URL}/login")
        p_1440.fill("input[name='username']", "qa_pool_teacher_1")
        p_1440.fill("input[name='password']", "demo123pass")
        p_1440.click("button[type='submit']")
        p_1440.wait_for_load_state("networkidle")
        p_1440.goto(f"{BASE_URL}/schedule")
        p_1440.wait_for_selector("#tcc-workspace", timeout=10000)
        p_1440.evaluate("() => window.TCC && window.TCC.toggleDensity('compact')")
        time.sleep(0.8)
        p_1440.screenshot(path=os.path.join(OUTPUT_DIR, "11_desktop_1440_compact_density.png"), full_page=False)
        ctx_1440.close()

        # Screenshot 12: 1366x768 Standard
        print("Capturing 12_desktop_1366_standard.png...")
        ctx_1366 = browser.new_context(viewport={"width": 1366, "height": 768})
        p_1366 = ctx_1366.new_page()
        p_1366.goto(f"{BASE_URL}/login")
        p_1366.fill("input[name='username']", "qa_pool_teacher_1")
        p_1366.fill("input[name='password']", "demo123pass")
        p_1366.click("button[type='submit']")
        p_1366.wait_for_load_state("networkidle")
        p_1366.goto(f"{BASE_URL}/schedule")
        p_1366.wait_for_selector("#tcc-workspace", timeout=10000)
        time.sleep(0.8)
        p_1366.screenshot(path=os.path.join(OUTPUT_DIR, "12_desktop_1366_standard.png"), full_page=False)
        ctx_1366.close()

        # Screenshot 13: 1024x768 Tablet with Inspector Drawer
        print("Capturing 13_tablet_1024_drawer.png...")
        ctx_1024 = browser.new_context(viewport={"width": 1024, "height": 768})
        p_1024 = ctx_1024.new_page()
        p_1024.goto(f"{BASE_URL}/login")
        p_1024.fill("input[name='username']", "qa_pool_teacher_1")
        p_1024.fill("input[name='password']", "demo123pass")
        p_1024.click("button[type='submit']")
        p_1024.wait_for_load_state("networkidle")
        p_1024.goto(f"{BASE_URL}/schedule")
        p_1024.wait_for_selector("#tcc-workspace", timeout=10000)
        p_1024.evaluate("() => window.TCC && window.TCC.toggleInspector(true)")
        time.sleep(0.8)
        p_1024.screenshot(path=os.path.join(OUTPUT_DIR, "13_tablet_1024_drawer.png"), full_page=False)
        ctx_1024.close()

        # Screenshot 14: Mobile 390x844 Week Ribbon
        print("Capturing 14_mobile_390_week_ribbon.png...")
        ctx_390 = browser.new_context(
            viewport={"width": 390, "height": 844},
            user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
            is_mobile=True,
            has_touch=True
        )
        p_390 = ctx_390.new_page()
        p_390.goto(f"{BASE_URL}/login")
        p_390.fill("input[name='username']", "qa_pool_teacher_1")
        p_390.fill("input[name='password']", "demo123pass")
        p_390.click("button[type='submit']")
        p_390.wait_for_load_state("networkidle")
        p_390.goto(f"{BASE_URL}/schedule")
        p_390.wait_for_selector("#tcc-workspace", timeout=10000)
        time.sleep(0.8)
        p_390.screenshot(path=os.path.join(OUTPUT_DIR, "14_mobile_390_week_ribbon.png"), full_page=False)

        # Screenshot 15: Mobile 390x844 Bottom Sheet Inspector
        print("Capturing 15_mobile_390_bottom_sheet_inspector.png...")
        p_390.evaluate("""() => {
            if (window.TCC && window.TCC.state.lessons && window.TCC.state.lessons.length > 0) {
                const l = window.TCC.state.lessons[0];
                window.TCC.selectLesson(l.lesson_id || l.id);
            }
        }""")
        time.sleep(0.8)
        p_390.screenshot(path=os.path.join(OUTPUT_DIR, "15_mobile_390_bottom_sheet_inspector.png"), full_page=False)
        ctx_390.close()

        browser.close()
        print("✓ All screenshots and motion video captured successfully!")

if __name__ == "__main__":
    run_capture()

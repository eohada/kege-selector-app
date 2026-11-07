#!/usr/bin/env python3
"""
Sprint 2.7 Visual Capture & Acceptance Script for Temporal Canvas
Captures all required deliverables:
1. tc_01_week_view_1920.png
2. tc_02_week_view_1440.png
3. tc_03_dense_week_1920.png
4. tc_04_selected_lesson_inspector_1920.png
5. tc_05_compact_layers_popover.png
6. tc_06_spatial_focus_mode_1920.png
7. motion_proof.webm
"""

import os
import shutil
import time
from playwright.sync_api import sync_playwright

OUT_DIR = "/mnt/Main/projects/kege_selector_app_current/docs/teacher_control_center_sprint2_7/key_review"
ARTIFACT_DIR = "/home/eohada/.gemini/antigravity/brain/8c195796-22fa-44be-89b3-fa1e5aaeb37d"
BASE_URL = "http://127.0.0.1:5000"

os.makedirs(OUT_DIR, exist_ok=True)
os.makedirs(ARTIFACT_DIR, exist_ok=True)


def capture_all():
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-proxy-server", "--disable-dev-shm-usage"]
        )

        # 1. 1920x1080 Session with video recording
        context_video = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            record_video_dir=OUT_DIR,
            record_video_size={"width": 1920, "height": 1080}
        )
        page = context_video.new_page()

        # Login as teacher
        page.goto(f"{BASE_URL}/login")
        page.fill("input[name='username']", "qa_pool_teacher_1")
        page.fill("input[name='password']", "demo123pass")
        page.click("button[type='submit']")
        page.wait_for_load_state("networkidle")

        # Open Temporal Canvas Preview
        page.goto(f"{BASE_URL}/schedule/preview/temporal-canvas")
        page.wait_for_selector(".tc-workspace")
        time.sleep(1.0)

        # 1. Week View 1920
        p1 = os.path.join(OUT_DIR, "tc_01_week_view_1920.png")
        page.screenshot(path=p1)
        shutil.copy(p1, os.path.join(ARTIFACT_DIR, "tc_01_week_view_1920.png"))
        print(f"[OK] Saved {p1}")

        # 3. Dense Week View 1920 (same canvas has 16 lessons across 7 days)
        p3 = os.path.join(OUT_DIR, "tc_03_dense_week_1920.png")
        page.screenshot(path=p3)
        shutil.copy(p3, os.path.join(ARTIFACT_DIR, "tc_03_dense_week_1920.png"))
        print(f"[OK] Saved {p3}")

        # 4. Selected lesson + Context Dock (click first lesson card)
        first_card = page.locator(".tc-lesson-card").first
        first_card.click()
        time.sleep(0.5)
        p4 = os.path.join(OUT_DIR, "tc_04_selected_lesson_inspector_1920.png")
        page.screenshot(path=p4)
        shutil.copy(p4, os.path.join(ARTIFACT_DIR, "tc_04_selected_lesson_inspector_1920.png"))
        print(f"[OK] Saved {p4}")

        # 5. Compact Layers Popover
        layers_btn = page.locator("#tc-btn-layers")
        layers_btn.click()
        time.sleep(0.5)
        p5 = os.path.join(OUT_DIR, "tc_05_compact_layers_popover.png")
        page.screenshot(path=p5)
        shutil.copy(p5, os.path.join(ARTIFACT_DIR, "tc_05_compact_layers_popover.png"))
        print(f"[OK] Saved {p5}")

        # Close popover by clicking outside
        page.keyboard.press("Escape")
        time.sleep(0.3)

        # 6. Spatial Focus Mode
        # Click on Friday header (2026-11-06)
        friday_header = page.locator(".tc-day-header-cell").nth(4)
        friday_header.click()
        time.sleep(0.8)
        p6 = os.path.join(OUT_DIR, "tc_06_spatial_focus_mode_1920.png")
        page.screenshot(path=p6)
        shutil.copy(p6, os.path.join(ARTIFACT_DIR, "tc_06_spatial_focus_mode_1920.png"))
        print(f"[OK] Saved {p6}")

        # Switch day in ribbon: click Saturday (СБ 7)
        page.locator(".tc-focus-day-chip").nth(5).click()
        time.sleep(0.5)

        # Switch back to week
        page.locator(".tc-focus-back-btn").click()
        time.sleep(0.8)

        # Perform drag interaction for video
        drag_card = page.locator(".tc-lesson-card").nth(2)
        box = drag_card.bounding_box()
        if box:
            page.mouse.move(box["x"] + 20, box["y"] + 20)
            page.mouse.down()
            # Move slowly
            for step in range(15):
                page.mouse.move(box["x"] + 20 + step * 10, box["y"] + 20 + step * 8)
                time.sleep(0.04)
            page.mouse.up()
            time.sleep(0.8)

        # Close video context
        video_path = page.video.path()
        context_video.close()
        target_video = os.path.join(OUT_DIR, "motion_proof.webm")
        if os.path.exists(video_path):
            shutil.copy(video_path, target_video)
            shutil.copy(video_path, os.path.join(ARTIFACT_DIR, "motion_proof.webm"))
            print(f"[OK] Saved video: {target_video}")

        # 2. 1440x900 Session
        context_1440 = browser.new_context(viewport={"width": 1440, "height": 900})
        page_1440 = context_1440.new_page()
        page_1440.goto(f"{BASE_URL}/login")
        page_1440.fill("input[name='username']", "qa_pool_teacher_1")
        page_1440.fill("input[name='password']", "demo123pass")
        page_1440.click("button[type='submit']")
        page_1440.wait_for_load_state("networkidle")

        page_1440.goto(f"{BASE_URL}/schedule/preview/temporal-canvas")
        page_1440.wait_for_selector(".tc-workspace")
        time.sleep(1.0)

        p2 = os.path.join(OUT_DIR, "tc_02_week_view_1440.png")
        page_1440.screenshot(path=p2)
        shutil.copy(p2, os.path.join(ARTIFACT_DIR, "tc_02_week_view_1440.png"))
        print(f"[OK] Saved {p2}")

        context_1440.close()
        browser.close()


if __name__ == "__main__":
    capture_all()

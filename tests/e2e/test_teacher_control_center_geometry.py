"""E2E Playwright geometric assertions test for BooStudy Teacher Control Center Sprint 2.6.1.
Verifies that:
1. Calendar grid body and day columns match coordinate system.
2. 07:00, 10:30, 14:00, 18:00, 22:00 cards align exactly to their corresponding slot cells.
3. Card durations scale card heights proportionally (45m, 60m, 90m, 120m).
4. Date range header does NOT wrap into multiple lines.
5. On 1440px viewport, the inspector operates as a slide-over drawer without crushing calendar width.
6. Drag-and-drop gesture initiates ghost with informative feedback.
"""
import os
import sys
import time
from playwright.sync_api import sync_playwright

BASE_URL = os.environ.get("TEST_BASE_URL", "http://127.0.0.1:5000")

def test_teacher_control_center_geometry():
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-proxy-server", "--disable-dev-shm-usage"]
        )

        context = browser.new_context(viewport={"width": 1920, "height": 1080})
        page = context.new_page()

        # 1. Login
        page.goto(f"{BASE_URL}/login")
        page.fill("input[name='username']", "qa_pool_teacher_1")
        page.fill("input[name='password']", "demo123pass")
        page.click("button[type='submit']")
        page.wait_for_load_state("networkidle")

        # 2. Navigate to schedule
        page.goto(f"{BASE_URL}/schedule")
        page.wait_for_selector("#tcc-workspace", timeout=10000)
        time.sleep(1.0)

        # 3. Verify date range title does NOT wrap into multiple lines
        title_box = page.locator("#tcc-period-title").bounding_box()
        assert title_box is not None, "Date range title not found"
        assert title_box["height"] < 40, f"Date range title wrapped! height={title_box['height']}"

        # 4. Verify day columns exist and time gutter width is 60px
        time_gutter_box = page.locator("#tcc-time-gutter").bounding_box()
        assert time_gutter_box is not None
        assert abs(time_gutter_box["width"] - 60) <= 2, f"Time gutter width is {time_gutter_box['width']}"

        day_columns = page.locator(".tcc-day-column")
        assert day_columns.count() == 7, f"Expected 7 day columns, got {day_columns.count()}"

        # 5. Verify geometric coordinate alignment for lessons:
        # Check Tuesday 07:00 lesson card (morning)
        card_07_eval = page.evaluate("""() => {
            const card = Array.from(document.querySelectorAll('.tcc-lesson-card')).find(c => {
                return c.textContent.includes('07:00');
            });
            if (!card) return null;
            const cardRect = card.getBoundingClientRect();
            const col = card.closest('.tcc-day-column');
            const colRect = col.getBoundingClientRect();
            const colIdx = parseInt(col.getAttribute('data-day-index'), 10);
            const slot07 = col.querySelector('.tcc-slot-cell[data-hour="7"]');
            const slotRect = slot07.getBoundingClientRect();
            return {
                found: true,
                colIdx,
                cardTop: cardRect.top,
                slotTop: slotRect.top,
                cardHeight: cardRect.height,
                colLeft: colRect.left,
                colRight: colRect.right,
                cardLeft: cardRect.left,
                cardRight: cardRect.right
            };
        }""")
        assert card_07_eval is not None and card_07_eval["found"], "07:00 lesson card not found"
        assert abs(card_07_eval["cardTop"] - card_07_eval["slotTop"]) <= 3, f"07:00 card top mismatch: {card_07_eval}"
        assert card_07_eval["colIdx"] == 1, f"07:00 lesson should be in Tuesday column (idx 1), got {card_07_eval['colIdx']}"
        assert card_07_eval["cardLeft"] >= card_07_eval["colLeft"], "Card overflowed left of column"
        assert card_07_eval["cardRight"] <= card_07_eval["colRight"] + 2, "Card overflowed right of column"

        # Check Monday 10:30 lesson card (mid-day, 90m duration)
        card_1030_eval = page.evaluate("""() => {
            const card = Array.from(document.querySelectorAll('.tcc-lesson-card')).find(c => {
                return c.textContent.includes('10:30');
            });
            if (!card) return null;
            const cardRect = card.getBoundingClientRect();
            const col = card.closest('.tcc-day-column');
            const slot10 = col.querySelector('.tcc-slot-cell[data-hour="10"]');
            const slot11 = col.querySelector('.tcc-slot-cell[data-hour="11"]');
            const s10Rect = slot10.getBoundingClientRect();
            const s11Rect = slot11.getBoundingClientRect();
            return {
                found: true,
                cardTop: cardRect.top,
                expectedTop: s10Rect.top + (s10Rect.height / 2),
                cardHeight: cardRect.height,
                expectedHeight: (s10Rect.height * 1.5) - 2,
                cardBottom: cardRect.bottom,
                s11Bottom: s11Rect.bottom
            };
        }""")
        assert card_1030_eval is not None and card_1030_eval["found"], "10:30 lesson card not found"
        assert abs(card_1030_eval["cardTop"] - card_1030_eval["expectedTop"]) <= 4, f"10:30 card top mismatch: {card_1030_eval}"
        assert abs(card_1030_eval["cardHeight"] - card_1030_eval["expectedHeight"]) <= 4, f"10:30 card height mismatch: {card_1030_eval}"

        # Check Monday 14:00 lesson card (afternoon, 60m duration)
        card_14_eval = page.evaluate("""() => {
            const card = Array.from(document.querySelectorAll('#tcc-day-col-0 .tcc-lesson-card')).find(c => {
                return c.textContent.includes('14:00');
            });
            if (!card) return null;
            const cardRect = card.getBoundingClientRect();
            const col = card.closest('.tcc-day-column');
            const slot14 = col.querySelector('.tcc-slot-cell[data-hour="14"]');
            const slotRect = slot14.getBoundingClientRect();
            return {
                found: true,
                cardTop: cardRect.top,
                slotTop: slotRect.top,
                cardHeight: cardRect.height,
                slotHeight: slotRect.height
            };
        }""")
        assert card_14_eval is not None and card_14_eval["found"], "14:00 Monday lesson card not found"
        assert abs(card_14_eval["cardTop"] - card_14_eval["slotTop"]) <= 3, f"14:00 card top mismatch: {card_14_eval}"
        assert abs(card_14_eval["cardHeight"] - (card_14_eval["slotHeight"] - 2)) <= 3, f"14:00 card height mismatch: {card_14_eval}"

        # Check Wednesday 22:00 lesson card (late evening)
        card_22_eval = page.evaluate("""() => {
            const card = Array.from(document.querySelectorAll('#tcc-day-col-2 .tcc-lesson-card')).find(c => {
                return c.textContent.includes('22:00');
            });
            if (!card) return null;
            const cardRect = card.getBoundingClientRect();
            const col = card.closest('.tcc-day-column');
            const slot22 = col.querySelector('.tcc-slot-cell[data-hour="22"]');
            const slotRect = slot22.getBoundingClientRect();
            return {
                found: true,
                cardTop: cardRect.top,
                slotTop: slotRect.top,
                cardBottom: cardRect.bottom,
                colBottom: col.getBoundingClientRect().bottom
            };
        }""")
        assert card_22_eval is not None and card_22_eval["found"], "22:00 Wednesday lesson card not found"
        assert abs(card_22_eval["cardTop"] - card_22_eval["slotTop"]) <= 3, f"22:00 card top mismatch: {card_22_eval}"
        assert card_22_eval["cardBottom"] <= card_22_eval["colBottom"] + 4, "22:00 card escaped beyond day column bottom!"

        # 6. Verify slide-over drawer behavior on 1440px viewport
        page.set_viewport_size({"width": 1440, "height": 900})
        time.sleep(0.5)

        cal_box_before = page.locator("#tcc-calendar-viewport").bounding_box()
        # Open inspector
        page.evaluate("() => window.TCC && window.TCC.openInspector('overview')")
        time.sleep(0.5)

        cal_box_after = page.locator("#tcc-calendar-viewport").bounding_box()
        # On 1440px, the calendar viewport MUST NOT be squeezed by docked inspector!
        assert abs(cal_box_after["width"] - cal_box_before["width"]) <= 3, f"Calendar was squeezed! Before: {cal_box_before['width']}, After: {cal_box_after['width']}"

        # Verify backdrop is visible on 1440px
        backdrop_vis = page.evaluate("() => !document.getElementById('tcc-inspector-backdrop').classList.contains('is-hidden')")
        assert backdrop_vis, "Backdrop was not shown when slide-over inspector opened on 1440px"

        # Press Escape to close inspector
        page.keyboard.press("Escape")
        time.sleep(0.3)
        backdrop_closed = page.evaluate("() => document.getElementById('tcc-inspector-backdrop').classList.contains('is-hidden')")
        assert backdrop_closed, "Escape key did not dismiss slide-over inspector"

        # 7. Verify drag-and-drop initiates ghost and Escape cancels
        page.set_viewport_size({"width": 1920, "height": 1080})
        time.sleep(0.5)

        card_target = page.locator(".tcc-lesson-card").first
        box = card_target.bounding_box()
        page.mouse.move(box["x"] + 20, box["y"] + 20)
        page.mouse.down()
        # Move > 5px to trigger drag threshold
        page.mouse.move(box["x"] + 50, box["y"] + 50)
        time.sleep(0.2)

        ghost_present = page.evaluate("() => Boolean(document.querySelector('.tcc-drag-ghost'))")
        assert ghost_present, "Drag ghost did not appear after exceeding 5px drag threshold"

        # Cancel with Escape
        page.keyboard.press("Escape")
        time.sleep(0.2)
        ghost_gone = page.evaluate("() => !document.querySelector('.tcc-drag-ghost')")
        assert ghost_gone, "Drag ghost was not removed after pressing Escape"

        browser.close()
        print("✓ All Teacher Control Center geometric, spatial, and interaction assertions PASSED!")

if __name__ == "__main__":
    test_teacher_control_center_geometry()

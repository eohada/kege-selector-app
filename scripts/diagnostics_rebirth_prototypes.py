"""
BooStudy — Student Schedule: Experience Rebirth (Phase 0 & Phase 0.5)
Automated Playwright Visual & Geometry Capture Runner for Prototypes.
Renders and captures Concepts D (Unified), A, B, and C across 4 viewports and 5 data scenarios.
Outputs structured screenshots into docs/schedule_rebirth_prototypes/:
  - key_review/ (Numbered files 01..12 for 1-click select and copy)
  - viewports/ (All concepts across desktop 1440, 1920, tablet 768, mobile 390)
  - scenarios/ (All edge-case scenarios: single lesson, multi-event, empty week, long titles)
"""
import os
import sys
import time
import shutil
import threading
from werkzeug.serving import make_server
from playwright.sync_api import sync_playwright

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, ROOT_DIR)
os.chdir(ROOT_DIR)

# Force isolated test environment
os.environ['BOOSTUDY_SKIP_DATABASE_BOOTSTRAP'] = '1'
os.environ['BOOSTUDY_BACKGROUND_WORKERS_ENABLED'] = '0'
os.environ['BOOSTUDY_SCHEDULE_PREVIEWS_ENABLED'] = '1'
os.environ['TESTING'] = '1'
os.environ['SECRET_KEY'] = 'test-rebirth-prototypes-key'
os.environ['WTF_CSRF_ENABLED'] = 'false'

OUTPUT_DIR = os.path.join(ROOT_DIR, 'docs', 'schedule_rebirth_prototypes')
KEY_REVIEW_DIR = os.path.join(OUTPUT_DIR, 'key_review')
VIEWPORTS_DIR = os.path.join(OUTPUT_DIR, 'viewports')
SCENARIOS_DIR = os.path.join(OUTPUT_DIR, 'scenarios')

for d in [KEY_REVIEW_DIR, VIEWPORTS_DIR, SCENARIOS_DIR]:
    os.makedirs(d, exist_ok=True)

from app import create_app
app = create_app()

class ServerThread(threading.Thread):
    def __init__(self, flask_app, host='127.0.0.1', port=5099):
        super().__init__()
        self.server = make_server(host, port, flask_app)
        self.port = port

    def run(self):
        self.server.serve_forever()

    def shutdown(self):
        self.server.shutdown()


def run_prototype_diagnostics():
    print(f"Starting isolated prototype server on port 5099...")
    srv = ServerThread(app, port=5099)
    srv.daemon = True
    srv.start()
    time.sleep(1.0)

    base_url = "http://127.0.0.1:5099"
    captured_files = []

    viewports = {
        'desktop_1440x900': {'width': 1440, 'height': 900},
        'desktop_1920x1080': {'width': 1920, 'height': 1080},
        'tablet_768x1024': {'width': 768, 'height': 1024},
        'mobile_390x844': {'width': 390, 'height': 844}
    }

    concepts = {
        'concept_d': {'url': '/schedule/preview/concept-d', 'name': 'Concept D (Unified)'},
        'concept_a': {'url': '/schedule/preview/concept-a', 'name': 'Command Center'},
        'concept_b': {'url': '/schedule/preview/concept-b', 'name': 'Fluid Week'},
        'concept_c': {'url': '/schedule/preview/concept-c', 'name': 'Personal Space'}
    }

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        # 1. VIEWPORT MATRIX (Standard Scenario)
        print("\n--- PHASE 1: CAPTURING VIEWPORT MATRIX (1440, 1920, 768, 390) ---")
        for vp_name, vp_size in viewports.items():
            context = browser.new_context(
                viewport=vp_size,
                device_scale_factor=1,
                is_mobile=('mobile' in vp_name)
            )
            page = context.new_page()

            # Capture Hub
            if vp_name == 'desktop_1440x900':
                page.goto(f"{base_url}/schedule/preview/", wait_until='networkidle')
                page.wait_for_timeout(300)
                hub_shot = os.path.join(VIEWPORTS_DIR, "preview_hub_1440x900.png")
                page.screenshot(path=hub_shot, full_page=True)
                print(f"  [Hub] Captured {hub_shot}")

            for c_key, c_info in concepts.items():
                target_url = f"{base_url}{c_info['url']}?scenario=standard"
                page.goto(target_url, wait_until='networkidle')
                page.wait_for_timeout(400)

                filename = f"{c_key}_{vp_name}.png"
                filepath = os.path.join(VIEWPORTS_DIR, filename)
                page.screenshot(path=filepath, full_page=True)
                captured_files.append(filepath)
                print(f"  [{c_info['name']}] Captured {vp_name} -> {filename}")

                # For Concept D on mobile, also capture pure first screen viewport without toolbar
                if c_key == 'concept_d' and vp_name == 'mobile_390x844':
                    pure_mobile_url = f"{base_url}{c_info['url']}?scenario=standard&hide_toolbar=1"
                    page.goto(pure_mobile_url, wait_until='networkidle')
                    page.wait_for_timeout(300)
                    pure_filename = "concept_d_pure_mobile_first_screen_390x844.png"
                    pure_filepath = os.path.join(VIEWPORTS_DIR, pure_filename)
                    page.screenshot(path=pure_filepath, full_page=False) # exact first screen 390x844
                    captured_files.append(pure_filepath)
                    print(f"  [{c_info['name']}] Captured pure mobile first screen -> {pure_filename}")

            context.close()

        # 2. SCENARIOS MATRIX (on 1440x900 Desktop)
        print("\n--- PHASE 2: CAPTURING SCENARIOS MATRIX ---")
        scenarios = ['single_lesson', 'multi_event', 'empty_week', 'long_titles']
        
        ctx_desk = browser.new_context(viewport=viewports['desktop_1440x900'])
        page_desk = ctx_desk.new_page()

        for sc in scenarios:
            for c_key, c_info in concepts.items():
                target_url = f"{base_url}{c_info['url']}?scenario={sc}"
                page_desk.goto(target_url, wait_until='networkidle')
                page_desk.wait_for_timeout(400)

                filename = f"{c_key}_scenario_{sc}.png"
                filepath = os.path.join(SCENARIOS_DIR, filename)
                page_desk.screenshot(path=filepath, full_page=True)
                print(f"  [{c_info['name']}][{sc}] -> {filename}")

        # 3. INTERACTIVE TESTING (Day Clicking)
        print("\n--- PHASE 3: VERIFYING INTERACTIVE DAY CLICKS ---")
        
        # Concept D: click Wednesday (index 2)
        page_desk.goto(f"{base_url}/schedule/preview/concept-d?scenario=standard", wait_until='networkidle')
        page_desk.click('#unified-tab-2')
        page_desk.wait_for_timeout(300)
        c_d_click_shot = os.path.join(SCENARIOS_DIR, "concept_d_interactive_click_day2.png")
        page_desk.screenshot(path=c_d_click_shot, full_page=True)
        print(f"  [Concept D] Click day 2 verified -> {c_d_click_shot}")

        # Concept A: click Wednesday (index 2)
        page_desk.goto(f"{base_url}/schedule/preview/concept-a?scenario=standard", wait_until='networkidle')
        page_desk.click('#rail-node-2')
        page_desk.wait_for_timeout(300)
        c_a_click_shot = os.path.join(SCENARIOS_DIR, "concept_a_interactive_click_day2.png")
        page_desk.screenshot(path=c_a_click_shot, full_page=True)
        print(f"  [Concept A] Click day 2 verified -> {c_a_click_shot}")

        # Concept B: click Friday (index 4)
        page_desk.goto(f"{base_url}/schedule/preview/concept-b?scenario=standard", wait_until='networkidle')
        page_desk.click('#fluid-pill-4')
        page_desk.wait_for_timeout(300)
        c_b_click_shot = os.path.join(SCENARIOS_DIR, "concept_b_interactive_click_day4.png")
        page_desk.screenshot(path=c_b_click_shot, full_page=True)
        print(f"  [Concept B] Click day 4 verified -> {c_b_click_shot}")

        # Concept C: click Thursday (index 3)
        page_desk.goto(f"{base_url}/schedule/preview/concept-c?scenario=standard", wait_until='networkidle')
        page_desk.click('#spine-node-3')
        page_desk.wait_for_timeout(300)
        c_c_click_shot = os.path.join(SCENARIOS_DIR, "concept_c_interactive_click_day3.png")
        page_desk.screenshot(path=c_c_click_shot, full_page=True)
        print(f"  [Concept C] Click day 3 verified -> {c_c_click_shot}")

        ctx_desk.close()
        browser.close()

    srv.shutdown()

    # 4. POPULATE key_review/ FOR INSTANT 1-CLICK COPYING (Numbered 01..12)
    # Highlight Concept D prominently, and provide D vs A/B/C side-by-side targets
    print("\n--- PHASE 4: POPULATING key_review/ WITH NUMBERED SHOWCASE ASSETS ---")
    key_review_map = [
        # Concept D Showcases (The Hero of Phase 0.5 & Phase 0.6)
        ("concept_d_desktop_1440x900.png", "01_concept_d_unified_desktop_1440x900.png", VIEWPORTS_DIR),
        ("concept_d_mobile_390x844.png", "02_concept_d_unified_mobile_390x844.png", VIEWPORTS_DIR),
        ("concept_d_pure_mobile_first_screen_390x844.png", "02b_concept_d_pure_mobile_first_screen_390x844.png", VIEWPORTS_DIR),
        ("concept_d_tablet_768x1024.png", "03_concept_d_unified_tablet_768x1024.png", VIEWPORTS_DIR),
        ("concept_d_scenario_multi_event.png", "04_concept_d_multi_event_density.png", SCENARIOS_DIR),
        ("concept_d_scenario_single_lesson.png", "05_concept_d_single_lesson_balance.png", SCENARIOS_DIR),
        ("concept_d_scenario_empty_week.png", "06_concept_d_empty_week_with_boo.png", SCENARIOS_DIR),
        
        # Direct Comparison against Base Concepts A, B, C on 1440x900
        ("concept_a_desktop_1440x900.png", "07_compare_concept_a_command_center_1440x900.png", VIEWPORTS_DIR),
        ("concept_b_desktop_1440x900.png", "08_compare_concept_b_fluid_week_1440x900.png", VIEWPORTS_DIR),
        ("concept_c_desktop_1440x900.png", "09_compare_concept_c_personal_space_1440x900.png", VIEWPORTS_DIR),
        
        # Direct Comparison on Mobile 390x844
        ("concept_a_mobile_390x844.png", "10_compare_concept_a_mobile_390x844.png", VIEWPORTS_DIR),
        ("concept_b_mobile_390x844.png", "11_compare_concept_b_mobile_390x844.png", VIEWPORTS_DIR),
        ("concept_c_mobile_390x844.png", "12_compare_concept_c_mobile_390x844.png", VIEWPORTS_DIR),
    ]

    # Clean old items in key_review to avoid stale mix
    for f in os.listdir(KEY_REVIEW_DIR):
        fp = os.path.join(KEY_REVIEW_DIR, f)
        if os.path.isfile(fp):
            os.remove(fp)

    for src_name, dst_name, source_folder in key_review_map:
        src_path = os.path.join(source_folder, src_name)
        dst_path = os.path.join(KEY_REVIEW_DIR, dst_name)
        if os.path.exists(src_path):
            shutil.copyfile(src_path, dst_path)
            print(f"  [key_review] -> {dst_name}")

    # Summary
    print("\nDIAGNOSTICS & SCREENSHOT CAPTURE COMPLETED SUCCESSFULLY!")
    print(f"Root Screenshots Directory: {OUTPUT_DIR}")
    print(f"Key Review Directory (for 1-click copy): {KEY_REVIEW_DIR}")


if __name__ == '__main__':
    run_prototype_diagnostics()

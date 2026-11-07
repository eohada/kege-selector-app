from playwright.sync_api import sync_playwright

def measure():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-proxy-server", "--disable-dev-shm-usage"])
        page = browser.new_page(viewport={"width": 1920, "height": 1080})
        page.goto("http://127.0.0.1:5000/login")
        page.fill("input[name='username']", "qa_pool_teacher_1")
        page.fill("input[name='password']", "demo123pass")
        page.click("button[type='submit']")
        page.wait_for_load_state("networkidle")
        page.goto("http://127.0.0.1:5000/schedule/preview/temporal-canvas")
        page.wait_for_selector(".tc-workspace")

        script = """() => {
            const timeCells = Array.from(document.querySelectorAll('.tc-time-cell')).map(el => ({
                text: el.textContent.trim(),
                y: Math.round(el.getBoundingClientRect().top)
            }));
            const slotCells = Array.from(document.querySelectorAll('.tc-slot-cell')).map(el => ({
                hour: el.dataset.hour,
                y: Math.round(el.getBoundingClientRect().top)
            }));
            const cards = Array.from(document.querySelectorAll('.tc-lesson-card')).map(el => ({
                id: el.dataset.id,
                time: el.querySelector('.tc-card-time') ? el.querySelector('.tc-card-time').textContent : '',
                y: Math.round(el.getBoundingClientRect().top),
                h: Math.round(el.getBoundingClientRect().height)
            }));
            return { timeCells, slotCells, cards };
        }"""
        res = page.evaluate(script)
        
        print("--- TIME CELLS vs SLOT CELLS ---")
        for tc in res["timeCells"]:
            h = tc["text"].split(":")[0]
            matching_slot = next((s for s in res["slotCells"] if s["hour"] == str(int(h))), None)
            slot_y = matching_slot["y"] if matching_slot else "N/A"
            diff = (tc["y"] - slot_y) if matching_slot else "N/A"
            print(f"Hour {tc['text']}: time_cell.y={tc['y']}, slot_cell.y={slot_y}, diff={diff}")

        print("\n--- LESSON CARDS ---")
        for c in res["cards"]:
            print(f"Card ID={c['id']} time={c['time']}: card.y={c['y']} h={c['h']}")

        browser.close()

if __name__ == "__main__":
    measure()

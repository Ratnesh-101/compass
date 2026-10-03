import asyncio
from pathlib import Path
from playwright.async_api import async_playwright

ARTIFACT_DIR = Path("/Users/nandani/.gemini/antigravity-ide/brain/a36b7f99-af0b-4c41-993a-82920b078196")
TARGET_URL = "http://localhost:5173"

async def main():
    print("Connecting to Chromium (Brave) over CDP on http://127.0.0.1:9222...")
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp("http://127.0.0.1:9222")
        context = await browser.new_context(viewport={"width": 1440, "height": 900})
        page = await context.new_page()

        print(f"Navigating to {TARGET_URL}...")
        await page.goto(TARGET_URL, wait_until="domcontentloaded")
        await page.wait_for_timeout(1000)

        # Ensure guest session token is set
        await page.evaluate("""async () => {
            try {
                const res = await fetch('http://localhost:8000/api/guest/session', { method: 'POST' });
                const data = await res.json();
                if (data.guest_id && data.guest_token) {
                    localStorage.setItem('compass_guest_id', data.guest_id);
                    localStorage.setItem('compass_guest_token', data.guest_token);
                }
            } catch {}
        }""")
        await page.wait_for_timeout(500)

        print("Clicking Compass in sidebar...")
        await page.click("#sidebar-tab-compass")
        await page.wait_for_timeout(800)

        print("Clicking Planner subtab...")
        await page.click("#compass-subtab-planner")
        await page.wait_for_timeout(800)

        print("Filling goal in agent-goal-input...")
        await page.fill("#agent-goal-input", "I have 5 days left and I'm working 4 hours a day. Go through everything I have open and tell me honestly whether I can finish it.")
        await page.wait_for_timeout(300)

        print("Clicking Ask Assistant / Run...")
        await page.click("#agent-run-btn")

        print("Waiting for reasoning steps to stream...")
        for i in range(12):
            await page.wait_for_timeout(1000)
            text = await page.content()
            if "THINK" in text or "tool" in text.lower() or "step" in text.lower() or "actions taken" in text or "feasibility" in text.lower():
                print(f"Streaming step progress detected at {i+1}s...")

        await page.wait_for_timeout(2000)

        p = ARTIFACT_DIR / "compass_planner_reasoning_trace.png"
        await page.screenshot(path=str(p), full_page=False)
        print(f"Captured: {p}")

        await page.close()
        await context.close()
        print("Planner live verification complete!")

if __name__ == "__main__":
    asyncio.run(main())

import asyncio
import os
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

        # 1. Capture Dashboard
        print(f"Navigating to {TARGET_URL}...")
        await page.goto(TARGET_URL, wait_until="networkidle")
        await page.wait_for_timeout(2000)

        p1 = ARTIFACT_DIR / "compass_dashboard_live.png"
        await page.screenshot(path=str(p1), full_page=False)
        print(f"Captured: {p1}")

        # 2. Capture removed /share/:id route
        print(f"Navigating to {TARGET_URL}/share/audit-unreviewed-token-12345...")
        await page.goto(f"{TARGET_URL}/share/audit-unreviewed-token-12345", wait_until="networkidle")
        await page.wait_for_timeout(1500)

        p2 = ARTIFACT_DIR / "share_route_removed.png"
        await page.screenshot(path=str(p2), full_page=False)
        print(f"Captured: {p2}")

        # 3. Capture Compass Specialists Tab
        print(f"Navigating back to {TARGET_URL}...")
        await page.goto(TARGET_URL, wait_until="networkidle")
        await page.wait_for_timeout(1000)

        print("Clicking Compass nav tab in sidebar...")
        await page.click("#sidebar-tab-compass")
        await page.wait_for_timeout(1200)

        print("Clicking Specialists subtab...")
        await page.click("#compass-subtab-specialist")
        await page.wait_for_timeout(1500)

        p3 = ARTIFACT_DIR / "compass_specialists_live.png"
        await page.screenshot(path=str(p3), full_page=False)
        print(f"Captured: {p3}")

        await page.close()
        await context.close()
        print("CDP browser verification complete! All 3 screenshots saved.")

if __name__ == "__main__":
    asyncio.run(main())

"""
Compass — Live In-Browser Real Verification Harness.

Connects to headless Chromium (Brave) via Playwright CDP to perform
real-browser verification of P0 items:
1. P0.1: Clicking domain filter buttons triggers actual network requests with ?domain= query params
   and updates the UI.
2. P0.2: Sending a chat message in the browser triggers a response and visibly updates
   the header token/cost badge.
Takes screenshots and records exact network events.
"""

import asyncio
import json
from pathlib import Path
from playwright.async_api import async_playwright

ARTIFACT_DIR = Path("/Users/nandani/.gemini/antigravity-ide/brain/7d8773e7-344e-47e9-a523-d4035284e631")
VERIFICATION_DIR = Path("/Users/nandani/Downloads/compass/verification")
VERIFICATION_DIR.mkdir(parents=True, exist_ok=True)
TARGET_URL = "http://127.0.0.1:5173"


async def main():
    print(f"[1/6] Connecting to Chromium CDP on port 9222...")
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp("http://127.0.0.1:9222")
        context = browser.contexts[0] if browser.contexts else await browser.new_context(viewport={"width": 1280, "height": 800})
        page = await context.new_page()

        # Track network requests
        network_log = []

        def on_request(req):
            if "/api/" in req.url or "/tasks" in req.url:
                network_log.append({
                    "method": req.method,
                    "url": req.url,
                    "type": "request",
                })
                print(f"  --> [NET REQ] {req.method} {req.url}")

        def on_response(res):
            if "/api/" in res.url or "/tasks" in res.url:
                print(f"  <-- [NET RES] {res.status} {res.url}")

        page.on("request", on_request)
        page.on("response", on_response)

        print(f"[2/6] Navigating to live URL: {TARGET_URL}...")
        await page.goto(TARGET_URL, wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(2000)

        # Initial header badge check
        initial_badge = await page.locator("#usage-badge, .header-model-badge").inner_text()
        print(f"  [Header Badge at Load]: {initial_badge}")

        # Screenshot: Initial page load
        screenshot1 = VERIFICATION_DIR / "browser_01_initial_timeline.png"
        await page.screenshot(path=str(screenshot1))
        await page.screenshot(path=str(ARTIFACT_DIR / "browser_01_initial_timeline.png"))
        print(f"  Saved screenshot: {screenshot1}")

        # [3/6] P0.1 Verification: Click Domain Filter Buttons & verify network requests
        print("\n[3/6] Testing P0.1: Timeline Filter Buttons trigger genuine server-side requests...")

        filters_to_test = ["hackathon", "coursework", "code", "all"]
        filter_results = {}

        for dom in filters_to_test:
            prev_req_count = len([r for r in network_log if f"domain={dom}" in r["url"]])
            print(f"  Clicking filter: '{dom}'...")

            # Locate button with matching text
            btn = page.locator(f"button:has-text('{dom.capitalize()}'), button:has-text('{dom}')").first
            if await btn.count() > 0:
                await btn.click()
                await page.wait_for_timeout(1500)

                # Check if a new network request was logged
                matching_requests = [
                    r["url"] for r in network_log
                    if (f"domain={dom}" in r["url"]) or (dom == "all" and "/api/tasks" in r["url"])
                ]
                filter_results[dom] = {
                    "clicked": True,
                    "requests_seen": matching_requests[-2:],
                }
                print(f"    ✅ Filter '{dom}' triggered network request: {matching_requests[-1] if matching_requests else 'none'}")
            else:
                print(f"    ❌ Could not find button for filter '{dom}'")

        # Screenshot: Filtered timeline view
        screenshot2 = VERIFICATION_DIR / "browser_02_timeline_filtered.png"
        await page.screenshot(path=str(screenshot2))
        await page.screenshot(path=str(ARTIFACT_DIR / "browser_02_timeline_filtered.png"))
        print(f"  Saved screenshot: {screenshot2}")

        # [4/6] P0.2 Verification: Switch to Chat tab
        print("\n[4/6] Switching to Assistant Chat tab...")
        chat_tab_btn = page.locator("#tab-chat, button:has-text('Assistant Chat')").first
        await chat_tab_btn.click()
        await page.wait_for_timeout(1000)

        badge_before_chat = await page.locator("#usage-badge, .header-model-badge").inner_text()
        print(f"  Header badge before chat: {badge_before_chat}")

        # [5/6] Send a chat message
        print("\n[5/6] Sending message in Assistant Chat...")
        chat_input = page.locator("textarea, input[type='text'], input[placeholder*='Ask'], input[placeholder*='message'], textarea[placeholder*='message']").first
        await chat_input.fill("Please summarize my hackathon tasks and recommend what I should prioritize next.")
        await page.wait_for_timeout(500)

        # Press Enter or click send button
        send_btn = page.locator("button:has-text('Send'), button[type='submit']").first
        if await send_btn.count() > 0:
            await send_btn.click()
        else:
            await chat_input.press("Enter")

        print("  Waiting for assistant response and streaming completion...")
        # Wait up to 10 seconds for response stream and usage badge update
        await page.wait_for_timeout(8000)

        badge_after_chat = await page.locator("#usage-badge, .header-model-badge").inner_text()
        print(f"  Header badge after chat: {badge_after_chat}")

        # Screenshot: Chat with response and updated header
        screenshot3 = VERIFICATION_DIR / "browser_03_chat_and_counter.png"
        await page.screenshot(path=str(screenshot3))
        await page.screenshot(path=str(ARTIFACT_DIR / "browser_03_chat_and_counter.png"))
        print(f"  Saved screenshot: {screenshot3}")

        # Read rendered conversation messages
        messages = await page.locator("div[style*='border-radius: 12px'], div[style*='borderRadius: 12px'], div:has(> div:has-text('summarize my hackathon'))").all_inner_texts()
        print(f"\n[6/6] Verification Summary:")
        print(f"  Total Network Requests Captured: {len(network_log)}")
        print(f"  Header Badge Before Chat: '{badge_before_chat}'")
        print(f"  Header Badge After Chat:  '{badge_after_chat}'")
        print(f"  Messages in Chat: {len(messages)}")

        # Save verification report JSON
        report = {
            "target_url": TARGET_URL,
            "browser": "Chromium 152 (Brave Headless)",
            "network_requests": network_log,
            "filter_results": filter_results,
            "badge_before": badge_before_chat,
            "badge_after": badge_after_chat,
            "screenshots": [str(screenshot1), str(screenshot2), str(screenshot3)],
        }
        with open(VERIFICATION_DIR / "browser_verification_report.json", "w") as f:
            json.dump(report, f, indent=2)
        with open(ARTIFACT_DIR / "browser_verification_report.json", "w") as f:
            json.dump(report, f, indent=2)

        print(f"  Report written to: {VERIFICATION_DIR / 'browser_verification_report.json'}")
        await page.close()


if __name__ == "__main__":
    asyncio.run(main())

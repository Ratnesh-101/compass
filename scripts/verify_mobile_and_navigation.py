import asyncio
import os
import sys
from playwright.async_api import async_playwright

ARTIFACT_DIR = "/Users/nandani/.gemini/antigravity-ide/brain/a36b7f99-af0b-4c41-993a-82920b078196"

async def run_tests():
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp("http://127.0.0.1:9222")
        context = browser.contexts[0] if browser.contexts else await browser.new_context()
        page = context.pages[0] if context.pages else await context.new_page()

        print("=== PART 1: DESKTOP ROUTING & DOMAIN NAVIGATION ===")
        await page.set_viewport_size({"width": 1440, "height": 900})
        await page.goto("http://localhost:5173", wait_until="domcontentloaded")
        await asyncio.sleep(1)

        # 1. Check initial route
        print("Initial URL:", page.url)
        await page.screenshot(path=os.path.join(ARTIFACT_DIR, "nav_1_desktop_timeline.png"))

        # 2. Click Hackathon in sidebar
        print("Clicking Hackathon domain in sidebar...")
        await page.click("#sidebar-domain-hackathon")
        await asyncio.sleep(0.8)
        print("URL after Hackathon click:", page.url)
        assert "/domain/hackathon" in page.url or "/hackathon" in page.url
        # Check active domain styling
        active_domain = await page.evaluate("""() => {
            const h = document.querySelector('h2');
            const pill = document.querySelector('#filter-pill-hackathon');
            return {
                h2Text: h ? h.innerText : '',
                pillClass: pill ? pill.className : ''
            };
        }""")
        print("Domain view header:", active_domain)
        assert "Hackathon" in active_domain["h2Text"]
        assert "active" in active_domain["pillClass"]
        await page.screenshot(path=os.path.join(ARTIFACT_DIR, "nav_2_hackathon_domain.png"))

        # 3. Click Code domain in sidebar
        print("Clicking Code domain in sidebar...")
        await page.click("#sidebar-domain-code")
        await asyncio.sleep(0.8)
        print("URL after Code click:", page.url)
        assert "/domain/code" in page.url
        code_h2 = await page.evaluate("() => document.querySelector('h2')?.innerText || ''")
        print("Code view header:", code_h2)
        assert "Code" in code_h2
        await page.screenshot(path=os.path.join(ARTIFACT_DIR, "nav_3_code_domain.png"))

        # 4. Click Compass tab in sidebar
        print("Clicking Compass tab in sidebar...")
        await page.click("#sidebar-tab-compass")
        await asyncio.sleep(0.8)
        print("URL after Compass click:", page.url)
        assert "/compass" in page.url
        # Verify Compass Assistant is visible
        has_chat = await page.evaluate("() => Boolean(document.querySelector('#compass-subtab-chat'))")
        assert has_chat
        await page.screenshot(path=os.path.join(ARTIFACT_DIR, "nav_4_compass_view.png"))

        # 5. Click Schedule tab in sidebar
        print("Clicking Schedule tab in sidebar...")
        await page.click("#sidebar-tab-calendar")
        await asyncio.sleep(0.8)
        print("URL after Schedule click:", page.url)
        assert "/schedule" in page.url or "/calendar" in page.url
        await page.screenshot(path=os.path.join(ARTIFACT_DIR, "nav_5_schedule_view.png"))

        # 6. Click Coursework domain from Schedule view
        print("Clicking Coursework domain directly from Schedule view...")
        await page.click("#sidebar-domain-coursework")
        await asyncio.sleep(0.8)
        print("URL after Coursework click from Schedule:", page.url)
        assert "/domain/coursework" in page.url
        coursework_h2 = await page.evaluate("() => document.querySelector('h2')?.innerText || ''")
        print("Coursework view header:", coursework_h2)
        assert "Coursework" in coursework_h2
        await page.screenshot(path=os.path.join(ARTIFACT_DIR, "nav_6_coursework_domain.png"))

        # 7. Test Browser Back and Forward
        print("Testing browser Back...")
        await page.go_back(wait_until="domcontentloaded")
        await asyncio.sleep(0.8)
        print("URL after Back:", page.url)
        assert "/schedule" in page.url or "/calendar" in page.url

        print("Testing browser Forward...")
        await page.go_forward(wait_until="domcontentloaded")
        await asyncio.sleep(0.8)
        print("URL after Forward:", page.url)
        assert "/domain/coursework" in page.url
        await page.screenshot(path=os.path.join(ARTIFACT_DIR, "nav_7_back_forward.png"))

        # 8. Test Direct URL Refresh
        print("Testing direct navigation to /domain/general...")
        await page.goto("http://localhost:5173/domain/general", wait_until="domcontentloaded")
        await asyncio.sleep(1)
        print("URL after direct goto:", page.url)
        assert "/domain/general" in page.url
        general_h2 = await page.evaluate("() => document.querySelector('h2')?.innerText || ''")
        print("Direct general header:", general_h2)
        assert "General" in general_h2
        await page.screenshot(path=os.path.join(ARTIFACT_DIR, "nav_8_direct_general.png"))

        print("\n=== PART 2: MOBILE & TABLET RESPONSIVENESS ===")
        # Test Tablet 768px
        print("Setting viewport to 768px (Tablet)...")
        await page.set_viewport_size({"width": 768, "height": 1024})
        await asyncio.sleep(0.8)
        mobile_header_visible = await page.evaluate("""() => {
            const h = document.querySelector('.mobile-header');
            return h ? window.getComputedStyle(h).display !== 'none' : false;
        }""")
        print("Tablet mobile header visible:", mobile_header_visible)
        assert mobile_header_visible
        await page.screenshot(path=os.path.join(ARTIFACT_DIR, "nav_9_tablet_768px.png"))

        # Test Mobile 480px
        print("Setting viewport to 480px (Mobile)...")
        await page.set_viewport_size({"width": 480, "height": 844})
        await asyncio.sleep(0.8)
        
        # Check no horizontal overflow
        h_scroll = await page.evaluate("""() => {
            return {
                scrollWidth: document.documentElement.scrollWidth,
                clientWidth: document.documentElement.clientWidth,
                hasOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth
            };
        }""")
        print("480px overflow check:", h_scroll)
        assert not h_scroll["hasOverflow"]
        await page.screenshot(path=os.path.join(ARTIFACT_DIR, "nav_10_mobile_480px.png"))

        # Open mobile drawer via hamburger
        print("Clicking mobile hamburger button...")
        await page.click("#mobile-menu-button")
        await asyncio.sleep(0.6)
        drawer_open = await page.evaluate("""() => {
            const aside = document.querySelector('aside.compass-sidebar');
            return aside ? aside.classList.contains('mobile-open') : false;
        }""")
        print("Mobile drawer open class:", drawer_open)
        assert drawer_open
        await page.screenshot(path=os.path.join(ARTIFACT_DIR, "nav_11_mobile_drawer_open.png"))

        # Click Hackathon domain inside mobile drawer
        print("Selecting Hackathon domain in mobile drawer...")
        await page.click("#sidebar-domain-hackathon")
        await asyncio.sleep(1.2)
        # Verify drawer closed automatically
        drawer_closed = await page.evaluate("""() => {
            const aside = document.querySelector('aside.compass-sidebar');
            return aside ? !aside.classList.contains('mobile-open') : true;
        }""")
        print("Mobile drawer auto-closed after selection:", drawer_closed)
        assert drawer_closed
        print("Current URL:", page.url)
        assert "/domain/hackathon" in page.url
        await page.screenshot(path=os.path.join(ARTIFACT_DIR, "nav_12_mobile_domain_selected.png"))

        # Test Mobile 375px (iPhone SE / Standard Mobile)
        print("Setting viewport to 375px (Small Mobile)...")
        await page.set_viewport_size({"width": 375, "height": 667})
        await asyncio.sleep(0.8)
        h_scroll_375 = await page.evaluate("""() => {
            return {
                scrollWidth: document.documentElement.scrollWidth,
                clientWidth: document.documentElement.clientWidth,
                hasOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth
            };
        }""")
        print("375px overflow check:", h_scroll_375)
        assert not h_scroll_375["hasOverflow"]
        await page.screenshot(path=os.path.join(ARTIFACT_DIR, "nav_13_mobile_375px.png"))

        # Switch to Compass view on mobile 375px
        await page.click("#mobile-menu-button")
        await asyncio.sleep(0.6)
        await page.click("#sidebar-tab-compass")
        await asyncio.sleep(0.8)
        print("Mobile 375px Compass URL:", page.url)
        assert "/compass" in page.url
        await page.screenshot(path=os.path.join(ARTIFACT_DIR, "nav_14_mobile_compass_375px.png"))

        print("\nALL VERIFICATION TESTS PASSED SUCCESSFULLY!")

if __name__ == "__main__":
    asyncio.run(run_tests())

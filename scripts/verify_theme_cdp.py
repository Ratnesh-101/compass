import asyncio
import json
import os
import subprocess
import time
import urllib.request
import websockets

CHROME_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
PORT = 9222

async def send_cmd(ws, msg_id, method, params=None):
    payload = {"id": msg_id, "method": method, "params": params or {}}
    await ws.send(json.dumps(payload))
    while True:
        resp = json.loads(await ws.recv())
        if resp.get("id") == msg_id:
            return resp

async def eval_js(ws, msg_id, expr):
    res = await send_cmd(ws, msg_id, "Runtime.evaluate", {"expression": expr, "returnByValue": True})
    return res.get("result", {}).get("result", {}).get("value")

async def main():
    user_data_dir = os.path.abspath("temp_chrome_theme_test")
    os.makedirs(user_data_dir, exist_ok=True)

    proc = subprocess.Popen([
        CHROME_PATH,
        f"--remote-debugging-port={PORT}",
        f"--user-data-dir={user_data_dir}",
        "--headless=new",
        "--disable-gpu",
        "--no-sandbox",
        "--window-size=1280,800",
        "http://127.0.0.1:4173/"
    ])

    print("Chrome launched with PID:", proc.pid)
    time.sleep(2)

    try:
        # Get WebSocket debugger URL
        tabs_url = f"http://127.0.0.1:{PORT}/json"
        req = urllib.request.urlopen(tabs_url)
        tabs = json.loads(req.read().decode())
        ws_url = None
        for t in tabs:
            if t.get("type") == "page":
                ws_url = t.get("webSocketDebuggerUrl")
                break
        
        if not ws_url:
            raise Exception("No page tab found in Chrome")

        print("Connecting to WebSocket:", ws_url)
        async with websockets.connect(ws_url) as ws:
            msg_id = 1
            await send_cmd(ws, msg_id, "Page.enable"); msg_id += 1
            await send_cmd(ws, msg_id, "Runtime.enable"); msg_id += 1

            # Wait for DOM to settle
            await asyncio.sleep(2)

            # Step 1: Initial Theme Check
            initial_theme = await eval_js(ws, msg_id, "document.documentElement.getAttribute('data-theme')"); msg_id += 1
            print("1. Initial data-theme:", initial_theme)
            assert initial_theme in ['light', 'dark'], f"Unexpected initial theme: {initial_theme}"

            # Step 2: Click Sidebar Theme Toggle
            toggle_exists = await eval_js(ws, msg_id, "Boolean(document.getElementById('sidebar-theme-toggle'))"); msg_id += 1
            print("2. Sidebar theme toggle exists:", toggle_exists)
            assert toggle_exists, "sidebar-theme-toggle not found in DOM"

            # Toggle theme
            await eval_js(ws, msg_id, "document.getElementById('sidebar-theme-toggle').click()"); msg_id += 1
            await asyncio.sleep(0.5)

            # Step 3: Check theme switched
            theme_after_toggle = await eval_js(ws, msg_id, "document.documentElement.getAttribute('data-theme')"); msg_id += 1
            stored_theme = await eval_js(ws, msg_id, "localStorage.getItem('compass.theme')"); msg_id += 1
            print("3. Theme after toggle:", theme_after_toggle, "| localStorage:", stored_theme)
            assert theme_after_toggle != initial_theme, "Theme did not change after toggle"
            assert stored_theme == theme_after_toggle, "localStorage theme mismatch"

            # Capture screenshot
            ss_data = await send_cmd(ws, msg_id, "Page.captureScreenshot", {"format": "png"}); msg_id += 1
            import base64
            with open("theme_verification_toggled.png", "wb") as f:
                f.write(base64.b64decode(ss_data["result"]["data"]))
            print("Captured theme_verification_toggled.png")

            # Step 4: Test Header Theme Toggle
            header_toggle_exists = await eval_js(ws, msg_id, "Boolean(document.getElementById('header-theme-toggle'))"); msg_id += 1
            print("4. Header theme toggle exists:", header_toggle_exists)
            if header_toggle_exists:
                await eval_js(ws, msg_id, "document.getElementById('header-theme-toggle').click()"); msg_id += 1
                await asyncio.sleep(0.5)
                theme_after_header_toggle = await eval_js(ws, msg_id, "document.documentElement.getAttribute('data-theme')"); msg_id += 1
                stored_theme_header = await eval_js(ws, msg_id, "localStorage.getItem('compass.theme')"); msg_id += 1
                print("   Theme after header toggle:", theme_after_header_toggle, "| localStorage:", stored_theme_header)
                assert theme_after_header_toggle == initial_theme, "Header toggle did not switch theme back"

            # Step 5: Test Persistence across page reload
            # First set to 'dark'
            await eval_js(ws, msg_id, "document.getElementById('sidebar-theme-toggle').click()"); msg_id += 1
            await asyncio.sleep(0.5)
            active_theme = await eval_js(ws, msg_id, "document.documentElement.getAttribute('data-theme')"); msg_id += 1
            print("5. Set active theme for reload test:", active_theme)

            # Reload page
            print("   Reloading page...")
            await send_cmd(ws, msg_id, "Page.reload"); msg_id += 1
            await asyncio.sleep(2)

            theme_after_reload = await eval_js(ws, msg_id, "document.documentElement.getAttribute('data-theme')"); msg_id += 1
            stored_after_reload = await eval_js(ws, msg_id, "localStorage.getItem('compass.theme')"); msg_id += 1
            print("   Theme after reload:", theme_after_reload, "| localStorage:", stored_after_reload)
            assert theme_after_reload == active_theme, f"Theme failed to persist across reload: got {theme_after_reload}, expected {active_theme}"
            assert stored_after_reload == active_theme, "localStorage corrupted across reload"

            # Step 6: Test Collapsed Sidebar Theme Toggle
            collapse_btn = await eval_js(ws, msg_id, "Boolean(document.getElementById('sidebar-collapse-toggle'))"); msg_id += 1
            print("6. Sidebar collapse toggle exists:", collapse_btn)
            if collapse_btn:
                await eval_js(ws, msg_id, "document.getElementById('sidebar-collapse-toggle').click()"); msg_id += 1
                await asyncio.sleep(0.5)
                is_collapsed = await eval_js(ws, msg_id, "document.querySelector('aside').classList.contains('sidebar-collapsed')"); msg_id += 1
                print("   Sidebar collapsed successfully:", is_collapsed)
                toggle_in_collapsed = await eval_js(ws, msg_id, "Boolean(document.getElementById('sidebar-theme-toggle'))"); msg_id += 1
                print("   Theme toggle available in collapsed sidebar:", toggle_in_collapsed)
                assert toggle_in_collapsed, "Theme toggle not accessible in collapsed sidebar"

            # Final screenshot in dark mode
            ss_data = await send_cmd(ws, msg_id, "Page.captureScreenshot", {"format": "png"}); msg_id += 1
            with open("theme_verification_final.png", "wb") as f:
                f.write(base64.b64decode(ss_data["result"]["data"]))
            print("Captured theme_verification_final.png")

            print("\nALL THEME VERIFICATION TESTS PASSED SUCCESSFULLY!")

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except:
            proc.kill()
        # Clean user-data-dir
        import shutil
        shutil.rmtree(user_data_dir, ignore_errors=True)

if __name__ == "__main__":
    asyncio.run(main())

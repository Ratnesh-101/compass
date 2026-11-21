"""Browser acceptance checks for the Compass boot skeleton (C1) and first paint.

Run against a production build served locally:

    (cd frontend && npx vite build && npx vite preview --port 4173)
    python scripts/skeleton_acceptance.py

or against the live site with --url. Needs only `playwright` (and its Chromium
build). It touches no backend or database and writes screenshots only to --out,
which defaults to a temp directory outside the repo.
"""

import argparse
import os
import sys
import tempfile

from playwright.sync_api import sync_playwright

HEAVY_KBPS = 200

FCP_SCRIPT = """
window.__fcp = null;
new PerformanceObserver((list) => {
  for (const entry of list.getEntries()) {
    if (entry.name === 'first-contentful-paint') {
      window.__fcp = {
        t: entry.startTime,
        skeleton: !!document.getElementById('boot-skeleton'),
        app: !!document.querySelector('.app-shell'),
      };
    }
  }
}).observe({ type: 'paint', buffered: true });
"""

DARK_SCRIPT = "try { localStorage.setItem('compass.theme', 'dark') } catch (e) {}"

RESULTS = []


def report(name, ok, detail=""):
    RESULTS.append(ok)
    print(f"PASS {name}" if ok else f"FAIL {name}: {detail}", flush=True)


def skip(name, why):
    print(f"SKIP {name}: {why}", flush=True)


def throttle(context, page, latency_ms, down_kbps):
    cdp = context.new_cdp_session(page)
    cdp.send("Network.enable")
    cdp.send("Network.setCacheDisabled", {"cacheDisabled": True})
    cdp.send(
        "Network.emulateNetworkConditions",
        {
            "offline": False,
            "latency": latency_ms,
            "downloadThroughput": down_kbps * 1024 / 8,
            "uploadThroughput": 750 * 1024 / 8,
        },
    )
    return cdp


def shot(page, out, name):
    try:
        page.screenshot(path=os.path.join(out, name))
    except Exception as exc:  # screenshots are best effort
        print(f"NOTE screenshot {name} failed: {exc}", flush=True)


def check_desktop(browser, args):
    context = browser.new_context(viewport={"width": 1366, "height": 850})
    try:
        page = context.new_page()
        page.add_init_script(FCP_SCRIPT)
        throttle(context, page, args.latency_ms, args.down_kbps)
        page.goto(args.url, wait_until="commit")
        try:
            # Poll instead of wait_for_function: that helper evaluates a string, which a strict CSP
            # (script-src without 'unsafe-eval', as on the live site) blocks.
            fcp = None
            for _ in range(100):
                fcp = page.evaluate("() => window.__fcp")
                if fcp is not None:
                    break
                page.wait_for_timeout(100)
            if fcp is None:
                raise TimeoutError("no first-contentful-paint entry within 10 s")
            ok = bool(fcp and (fcp["skeleton"] or fcp["app"]))
            report("throttled_first_paint", ok, f"blank first paint: {fcp}")
            if ok:
                print(f"NOTE first-contentful-paint {fcp['t']:.0f} ms", flush=True)
        except Exception as exc:
            report("throttled_first_paint", False, f"no FCP within 10 s: {exc}")

        try:
            page.wait_for_timeout(1000)
            state = page.evaluate(
                """() => {
                  const b = document.getElementById('boot-skeleton');
                  const r = b ? b.getBoundingClientRect() : null;
                  return {
                    boot: !!(r && r.width > 0 && r.height > 0),
                    app: !!document.querySelector('.app-shell'),
                  };
                }"""
            )
            shot(page, args.out, "desktop-1s.png")
            report("not_blank_at_1s", state["boot"] or state["app"], str(state))
        except Exception as exc:
            report("not_blank_at_1s", False, str(exc))

        try:
            page.wait_for_selector("#main-content", timeout=args.load_timeout_s * 1000)
            gone = page.evaluate(
                """() => !document.getElementById('boot-skeleton')
                         && !document.getElementById('boot-seo')"""
            )
            shot(page, args.out, "desktop-loaded.png")
            report("skeleton_replaced_after_load", gone, "boot-skeleton or boot-seo still in DOM")
        except Exception as exc:
            report("skeleton_replaced_after_load", False, str(exc))
    except Exception as exc:
        report("desktop_checks", False, str(exc))
    finally:
        context.close()


def heavy_page(browser, args, **ctx_opts):
    context = browser.new_context(**ctx_opts)
    page = context.new_page()
    return context, page


def check_dark(browser, args):
    context = None
    try:
        context, page = heavy_page(browser, args, color_scheme="dark", viewport={"width": 1366, "height": 850})
        page.add_init_script(DARK_SCRIPT)
        throttle(context, page, args.latency_ms, HEAVY_KBPS)
        page.goto(args.url, wait_until="commit")
        page.wait_for_timeout(800)
        shot(page, args.out, "dark-boot.png")
        color = page.evaluate(
            """() => { const b = document.getElementById('boot-skeleton');
                       return b ? getComputedStyle(b).backgroundColor : null }"""
        )
        if color is None:
            skip("dark_theme_boot", "app mounted first")
        else:
            report("dark_theme_boot", color == "rgb(21, 21, 19)", f"background was {color}")
    except Exception as exc:
        report("dark_theme_boot", False, str(exc))
    finally:
        if context:
            context.close()


def check_reduced_motion(browser, args):
    context = None
    try:
        context, page = heavy_page(
            browser, args, reduced_motion="reduce", viewport={"width": 1366, "height": 850}
        )
        throttle(context, page, args.latency_ms, HEAVY_KBPS)
        page.goto(args.url, wait_until="commit")
        page.wait_for_timeout(800)
        name = page.evaluate(
            """() => { const b = document.querySelector('.boot-block');
                       return b ? getComputedStyle(b).animationName : null }"""
        )
        if name is None:
            skip("reduced_motion", "no .boot-block present (app mounted first)")
        else:
            report("reduced_motion", name == "none", f"animationName was {name}")
    except Exception as exc:
        report("reduced_motion", False, str(exc))
    finally:
        if context:
            context.close()


def check_phone(browser, args):
    context = None
    try:
        context, page = heavy_page(
            browser, args, viewport={"width": 390, "height": 844}, is_mobile=True
        )
        throttle(context, page, args.latency_ms, HEAVY_KBPS)
        page.goto(args.url, wait_until="commit")
        page.wait_for_timeout(800)
        shot(page, args.out, "phone-boot.png")
        d = page.evaluate(
            """() => {
              if (!document.getElementById('boot-skeleton')) return null;
              const disp = (s) => { const e = document.querySelector(s);
                return e ? getComputedStyle(e).display : null };
              return { side: disp('.boot-side'), top: disp('.boot-top') };
            }"""
        )
        if d is None:
            skip("phone_layout", "app mounted first")
        else:
            report("phone_layout", d["side"] == "none" and d["top"] == "flex", str(d))
    except Exception as exc:
        report("phone_layout", False, str(exc))
    finally:
        if context:
            context.close()


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--url", default="http://localhost:4173/")
    ap.add_argument("--out", default=os.path.join(tempfile.gettempdir(), "compass-skeleton-acceptance"))
    ap.add_argument("--latency-ms", type=int, default=150)
    ap.add_argument("--down-kbps", type=int, default=1600)
    ap.add_argument("--load-timeout-s", type=int, default=120)
    ap.add_argument("--headed", action="store_true")
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not args.headed)
        try:
            check_desktop(browser, args)
            check_dark(browser, args)
            check_reduced_motion(browser, args)
            check_phone(browser, args)
        finally:
            browser.close()

    print(f"Screenshots: {args.out}")
    return 0 if all(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())

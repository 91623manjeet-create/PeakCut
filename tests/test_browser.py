"""Checks the real pages in a real browser, because a page can look fine in the source and still break.

    python tests/test_browser.py <base url> [screenshots folder]

This is an extra check: it needs Playwright (pip install playwright, then playwright install chromium). If
Playwright is not installed the check says so and passes, so `python tests/run.py` works on any machine.
Nothing outside this machine is contacted: every request to another address is blocked and counted."""
import sys
import time
from pathlib import Path

BASE = sys.argv[1].rstrip("/")
SHOTS = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("browser-shots")
SHOTS.mkdir(parents=True, exist_ok=True)

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # the browser is optional, so a missing one is not a failure
    print("PASS browser checks skipped: Playwright is not installed")
    sys.exit(0)

fails = []


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"   {detail}"))
    if not ok:
        fails.append(name)


console_errors, page_errors, failed_requests, blocked = [], [], [], []


def watch(page):
    """Remember anything the page complains about, and keep it off the internet."""
    def note_console(m):
        if m.type != "error":
            return
        where = (m.location or {}).get("url", "")
        if "Failed to load resource" in m.text and not where.startswith(BASE):
            return  # an outside font we blocked on purpose: not the app's fault
        console_errors.append(f"{page.url} {m.text}")

    page.on("console", note_console)
    page.on("pageerror", lambda e: page_errors.append(f"{page.url} {e}"))
    # a request the page itself cancelled (a reload, or the long poll for changes) is not a failure
    page.on("requestfailed", lambda r: failed_requests.append(f"{r.url} {r.failure}")
            if r.url.startswith(BASE) and "ERR_ABORTED" not in (r.failure or "") else None)

    def only_here(route, request):
        if request.url.startswith(BASE) or request.url.startswith("data:") or request.url.startswith("blob:"):
            route.continue_()
        else:
            blocked.append(request.url)
            route.abort()

    page.route("**/*", only_here)
    return page


with sync_playwright() as pw:
    try:
        browser = pw.chromium.launch()
    except Exception as e:  # noqa: BLE001 - a missing browser is not a broken app
        print("PASS browser checks skipped: run 'playwright install chromium' first")
        print(str(e).splitlines()[0][:200])
        sys.exit(0)
    context = browser.new_context(viewport={"width": 1440, "height": 900}, device_scale_factor=1)
    page = watch(context.new_page())

    # ---- the front door
    page.goto(BASE + "/", wait_until="domcontentloaded")
    page.wait_for_timeout(600)
    check("the front page opens", "PeakCut" in page.title(), page.title())
    check("the front page has something to read", len(page.locator("body").inner_text()) > 200)
    page.screenshot(path=str(SHOTS / "1-front-page.png"))

    # ---- a brand new person signs up
    page.goto(BASE + "/signup", wait_until="domcontentloaded")
    check("the sign-up page has an email box", page.locator("#email").count() == 1)
    page.fill("#name", "Browser Check")
    page.fill("#email", f"browser-{int(time.time())}@example.com")
    page.fill("#password", "test-pass-123")
    page.click("#go")
    try:
        page.wait_for_url("**/app**", timeout=15000)
        arrived = True
    except Exception:  # noqa: BLE001
        arrived = False
    check("signing up lands in the app", arrived and page.url.startswith(BASE + "/app"),
          f"{page.url} {page.locator('#err').inner_text() if page.locator('#err').count() else ''}")
    try:
        page.wait_for_selector("#nav button.nav-item", timeout=15000)
    except Exception:  # noqa: BLE001
        pass
    check("the menu is there", page.locator("#nav button.nav-item").count() > 0, page.locator("#nav").inner_text()[:120])
    check("the video link box is there", page.locator("#url").count() == 1)
    page.screenshot(path=str(SHOTS / "2-app-home.png"))

    # ---- the guided tour new people get: it must be closable, and closing it must stick
    if page.locator("#tour.on").count():
        page.click('[data-tour="close"]')
        page.wait_for_timeout(400)
    check("the welcome tour closes", page.locator("#tour.on").count() == 0)

    # ---- moving between pages inside the app
    home_text = page.locator("#view").inner_text()
    page.click('#nav button[data-v="library"]')
    page.wait_for_timeout(800)
    check("the All videos page opens", page.locator('#nav button[data-v="library"].on').count() == 1)
    check("the page actually changed", page.locator("#view").inner_text() != home_text)
    page.click('#nav button[data-v="overview"]')
    page.wait_for_timeout(800)
    check("the Home page comes back", page.locator('#nav button[data-v="overview"].on').count() == 1)
    page.screenshot(path=str(SHOTS / "3-app-clean.png"))

    # ---- the app can still hear the server (the page polls /api/sync for changes)
    status = page.evaluate("() => fetch('/api/sync?v=').then(r => r.status).catch(() => 0)")
    check("the app's updates arrive", status == 200, f"got {status}")

    # ---- moving around the app does not throw anything away
    page.reload(wait_until="domcontentloaded")
    try:
        page.wait_for_selector("#nav button.nav-item", timeout=15000)
        drawn = True
    except Exception:  # noqa: BLE001
        drawn = False
    check("a reload stays signed in", page.url.startswith(BASE + "/app"), page.url)
    check("the menu survives a reload", drawn and page.locator("#nav button.nav-item").count() > 0,
          page.locator("#nav").inner_text()[:120])

    # ---- a page for someone who is not signed in
    fresh = watch(context.browser.new_context().new_page())
    fresh.goto(BASE + "/app", wait_until="domcontentloaded")
    fresh.wait_for_timeout(800)
    check("the app sends a stranger to sign in", fresh.url.endswith("/login"), fresh.url)
    fresh.screenshot(path=str(SHOTS / "4-sign-in.png"))
    fresh.context.close()

    context.close()
    browser.close()

check("nothing on the pages crashed", not page_errors, "; ".join(page_errors[:3]))
check("the browser logged no errors", not console_errors, "; ".join(console_errors[:3]))
check("no request failed", not failed_requests, "; ".join(failed_requests[:3]))
print(f"({len(blocked)} outside requests blocked; screenshots in {SHOTS})")
sys.exit(1 if fails else 0)

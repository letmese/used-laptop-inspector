"""Drive Stitch with real input events.

The app renders inside closed shadow roots, so no selector can reach the prompt
box. Synthetic mouse/keyboard events do not care about shadow boundaries - they
go to whatever is focused and painted.
"""
import pathlib
import sys

from playwright.sync_api import sync_playwright

OUT = pathlib.Path(r"G:\AntigravityProjects\used-laptop-inspector\out")
PROMPT = pathlib.Path(
    r"G:\AntigravityProjects\used-laptop-inspector\docs\stitch-prompt-main.txt"
).read_text(encoding="utf-8").strip()


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
        ctx = browser.contexts[0]
        page = ctx.pages[0]
        page.bring_to_front()
        page.goto("https://stitch.withgoogle.com/", wait_until="domcontentloaded",
                  timeout=60000)
        page.wait_for_timeout(5000)

        box = page.viewport_size
        print("viewport:", box)
        page.screenshot(path=str(OUT / "s1_loaded.png"))

        # 1. Web, not App
        page.mouse.click(314, 721)
        page.wait_for_timeout(700)
        page.screenshot(path=str(OUT / "s2_web.png"))
        print("clicked Web")

        # 2. focus the prompt area and type
        page.mouse.click(500, 560)
        page.wait_for_timeout(400)
        page.keyboard.type(PROMPT, delay=1)
        page.wait_for_timeout(800)
        page.screenshot(path=str(OUT / "s3_typed.png"))
        print("typed", len(PROMPT), "chars")

        # 3. send
        page.mouse.click(928, 721)
        page.wait_for_timeout(4000)
        page.screenshot(path=str(OUT / "s4_sent.png"))
        print("clicked send, url:", page.url)
    return 0


if __name__ == "__main__":
    sys.exit(main())

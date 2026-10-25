"""Fill the Stitch prompt box and stop before sending, so the text can be checked."""
import pathlib
import sys

from playwright.sync_api import sync_playwright

OUT = pathlib.Path(r"G:\AntigravityProjects\used-laptop-inspector\out")
PROMPT = pathlib.Path(
    r"G:\AntigravityProjects\used-laptop-inspector\docs\stitch-prompt-main.txt"
).read_text(encoding="utf-8").strip()


def main():
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
        page = next(pg for pg in browser.contexts[0].pages
                    if "stitch.withgoogle" in pg.url)
        page.bring_to_front()
        page.wait_for_timeout(800)

        # switch the generator from mobile to web
        try:
            web = page.get_by_role("button", name="Web", exact=True)
            if web.count():
                web.first.click()
                page.wait_for_timeout(500)
                print("clicked Web")
        except Exception as exc:
            print("web toggle:", exc)

        # find the prompt input
        target = None
        for sel in ("textarea", "[contenteditable='true']", "div[role='textbox']"):
            loc = page.locator(sel)
            if loc.count():
                target = loc.first
                print(f"input via {sel}, count={loc.count()}")
                break
        if target is None:
            print("NO INPUT FOUND")
            return

        target.click()
        page.wait_for_timeout(200)
        target.fill(PROMPT)
        page.wait_for_timeout(600)

        got = target.input_value() if target.evaluate("e => 'value' in e") else \
            target.inner_text()
        print("chars in box:", len(got))
        print("first 120:", got[:120].replace("\n", " "))
        print("last 80:", got[-80:].replace("\n", " "))
        page.screenshot(path=str(OUT / "stitch_02_filled.png"))
        print("screenshot saved")


if __name__ == "__main__":
    sys.exit(main())

"""Attach to the running Chrome over CDP and report what Stitch looks like."""
import sys
from playwright.sync_api import sync_playwright

OUT = r"G:\AntigravityProjects\used-laptop-inspector\out"


def main():
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
        print("connected:", browser.version)
        ctx = browser.contexts[0]
        print("pages:", len(ctx.pages))
        page = None
        for pg in ctx.pages:
            print("  -", pg.url[:90], "|", pg.title()[:50])
            if "stitch" in pg.url.lower():
                page = pg
        if page is None:
            page = ctx.new_page()
            page.goto("https://stitch.withgoogle.com/", wait_until="domcontentloaded")
        page.bring_to_front()
        page.wait_for_timeout(2500)
        print("target:", page.url)
        print("title:", page.title())
        page.screenshot(path=OUT + r"\stitch_01.png")
        # a little text to see whether we are signed in
        try:
            body = page.inner_text("body")[:600]
            print("--- visible text ---")
            print(body)
        except Exception as exc:
            print("no body text:", exc)


if __name__ == "__main__":
    main()

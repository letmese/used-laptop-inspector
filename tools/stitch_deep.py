"""Walk shadow roots to find where Stitch actually renders."""
from playwright.sync_api import sync_playwright

JS = """
() => {
  const report = {htmlLen: document.body ? document.body.innerHTML.length : -1,
                  shadowHosts: [], deepEditables: [], buttons: []};

  function walk(root, depth, path) {
    if (!root || depth > 6) return;
    const kids = root.querySelectorAll ? root.querySelectorAll('*') : [];
    for (const el of kids) {
      if (el.shadowRoot) {
        report.shadowHosts.push({path: path, tag: el.tagName,
          cls: (el.className||'').toString().slice(0,50),
          htmlLen: el.shadowRoot.innerHTML.length});
        const eds = el.shadowRoot.querySelectorAll('[contenteditable], textarea, input');
        eds.forEach(e => report.deepEditables.push({host: el.tagName,
          tag: e.tagName, ce: e.getAttribute('contenteditable'),
          ph: e.placeholder || '', cls: (e.className||'').toString().slice(0,50)}));
        walk(el.shadowRoot, depth + 1, path + '>' + el.tagName);
      }
    }
  }
  walk(document, 0, 'doc');

  document.querySelectorAll('button, [role=button]').forEach(b => {
    const t = (b.innerText || b.getAttribute('aria-label') || '').trim().slice(0, 30);
    if (t) report.buttons.push(t);
  });
  return report;
}
"""


def main():
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
        page = next(pg for pg in browser.contexts[0].pages
                    if "stitch.withgoogle" in pg.url)
        page.bring_to_front()
        page.wait_for_timeout(800)
        r = page.evaluate(JS)
        print("body htmlLen:", r["htmlLen"])
        print("shadow hosts:", len(r["shadowHosts"]))
        for h in r["shadowHosts"][:10]:
            print("   ", h)
        print("deep editables:", len(r["deepEditables"]))
        for e in r["deepEditables"][:10]:
            print("   ", e)
        print("buttons:", r["buttons"][:20])
        print("frames:", [f.url[:70] for f in page.frames])


if __name__ == "__main__":
    main()

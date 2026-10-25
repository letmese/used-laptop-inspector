"""Find the Stitch prompt input: dump iframes, editables and likely containers."""
from playwright.sync_api import sync_playwright

JS = """
() => {
  const out = {iframes: [], editables: [], inputs: [], candidates: []};
  document.querySelectorAll('iframe').forEach((f, i) => out.iframes.push(
    {i, src: (f.src||'').slice(0,80), id: f.id, cls: (f.className||'').toString().slice(0,60)}));
  document.querySelectorAll('[contenteditable]').forEach(e => out.editables.push(
    {tag: e.tagName, ce: e.getAttribute('contenteditable'),
     cls: (e.className||'').toString().slice(0,90),
     aria: e.getAttribute('aria-label'), text: (e.innerText||'').slice(0,40)}));
  document.querySelectorAll('input, textarea').forEach(e => out.inputs.push(
    {tag: e.tagName, type: e.type, ph: e.placeholder, cls: (e.className||'').toString().slice(0,60)}));
  document.querySelectorAll('*').forEach(e => {
    const a = (e.getAttribute && e.getAttribute('aria-label')) || '';
    const r = (e.getAttribute && e.getAttribute('role')) || '';
    if ((a && /prompt|describe|design|ask/i.test(a)) || r === 'textbox')
      out.candidates.push({tag: e.tagName, aria: a, role: r,
        cls: (e.className||'').toString().slice(0,70)});
  });
  return out;
}
"""


def main():
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
        page = next(pg for pg in browser.contexts[0].pages
                    if "stitch.withgoogle" in pg.url)
        page.bring_to_front()
        page.wait_for_timeout(1000)
        info = page.evaluate(JS)
        for key, val in info.items():
            print(f"--- {key} ({len(val)}) ---")
            for item in val[:12]:
                print("   ", item)
        # what does the main frame body look like right now
        print("--- body text (first 300) ---")
        print((page.inner_text("body") or "")[:300])


if __name__ == "__main__":
    main()

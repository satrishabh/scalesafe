"""Compliance additions on top of the live site: accessibility statement, EU/UK/US privacy supplement,
footer links to both on every page, and Global Privacy Control confirmation.

Run by tools/sync_from_live.py after the fixes and /insights, so every page (including generated
briefings) gets the links. Idempotent: safe to run again on an already patched tree.

Standalone, to patch site-deploy/ in place:
    python tools/compliance.py site-deploy

Content lives in tools/patches/compliance/*.main.html (the <main> body only); the page chrome
(head, header, footer, styles) is taken from the live Cookie & Storage Notice, so the new pages
always match the rest of the legal pages.
"""
import html
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "patches", "compliance")
BASE = "https://scalesafe.co.in/"
TEMPLATE = "cookie-notice/index.html"
GPC_ASSET = "assets/privacy/gpc.js"
GPC_TAG = '<script src="/assets/privacy/gpc.js" defer></script>'

PAGES = {
    "accessibility/index.html": {
        "src": "accessibility.main.html",
        "title": "Accessibility Statement | ScaleSafe",
        "description": "How ScaleSafe makes scalesafe.co.in and its platform accessible: standards for India (RPwD Act, IS 17802, SEBI), the EU (EAA, EN 301 549) and the US (ADA), known limitations and how to give feedback.",
    },
    "privacy-notice/regional/index.html": {
        "src": "regional.main.html",
        "title": "Privacy: EU, UK and US supplement | ScaleSafe",
        "description": "GDPR and UK GDPR rights and legal bases, US state privacy rights, Global Privacy Control, and how ScaleSafe handles data it processes for clients.",
    },
}
# Links added next to every "Cookie & Storage Notice" link, in this order.
LINKS = [("/privacy-notice/regional/", "EU/UK &amp; US privacy"), ("/accessibility/", "Accessibility Statement")]


class ComplianceError(Exception):
    pass


def _read(p):
    with open(p, encoding="utf-8") as f:
        return f.read()


def _write(p, t):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8", newline="") as f:
        f.write(t)


def build_pages(root):
    notes = []
    tpl_path = os.path.join(root, TEMPLATE)
    if not os.path.exists(tpl_path):
        raise ComplianceError(f"{TEMPLATE} not found: cannot build compliance pages")
    tpl = _read(tpl_path)
    if not re.search(r'<main id="main">.*?</main>', tpl, re.S):
        raise ComplianceError(f"{TEMPLATE}: <main id=\"main\"> not found")
    for rel, page in PAGES.items():
        url = BASE + rel[: -len("index.html")]
        title = html.escape(page["title"], quote=False)
        desc = html.escape(page["description"])
        body = _read(os.path.join(SRC, page["src"])).strip()
        t = re.sub(r"<title>.*?</title>", f"<title>{title}</title>", tpl, count=1, flags=re.S)
        t = re.sub(r'<meta name="description" content="[^"]*">', f'<meta name="description" content="{desc}">', t, count=1)
        t = re.sub(r'<meta property="og:title" content="[^"]*">', f'<meta property="og:title" content="{title}">', t, count=1)
        t = re.sub(r'<meta property="og:description" content="[^"]*">', f'<meta property="og:description" content="{desc}">', t, count=1)
        t = re.sub(r'<link rel="canonical" href="[^"]*">', f'<link rel="canonical" href="{url}">', t, count=1)
        t = re.sub(r'<meta property="og:url" content="[^"]*">', f'<meta property="og:url" content="{url}">', t, count=1)
        t = re.sub(r'<main id="main">.*?</main>', lambda _m: f'<main id="main">\n{body}\n</main>', t, count=1, flags=re.S)
        _write(os.path.join(root, rel), t)
        notes.append(f"{rel}: built")
    return notes


def _link_markup(anchor_attrs, wrapper):
    if wrapper == "li":
        return "".join(f'<li><a href="{h}">{label}</a></li>' for h, label in LINKS)
    if wrapper == "class":
        return "".join(f'<a{anchor_attrs} href="{h}">{label}</a>' for h, label in LINKS)
    return "".join(f' ·\n    <a href="{h}">{label}</a>' for h, label in LINKS)


COOKIE_LINK = re.compile(r'<a((?:\s+class="[^"]*")?)\s+href="/cookie-notice/">Cookie &amp; Storage Notice</a>(</li>)?')


FOOTER_REGIONS = re.compile(r'<footer\b.*?</footer>|<p class="ss-nav"[^>]*>.*?</p>', re.S)


def _inject(m):
    attrs, li = m.group(1), m.group(2)
    if li:
        return m.group(0) + _link_markup("", "li")
    if attrs:
        return m.group(0) + _link_markup(attrs, "class")
    return m.group(0) + _link_markup("", "inline")


def add_links_and_gpc(root):
    """Footer links next to the Cookie & Storage Notice link (only inside footers, never in page text),
    and the GPC script before </body>."""
    linked = scripted = 0
    for d, _, fs in os.walk(root):
        for f in fs:
            if not f.endswith(".html"):
                continue
            p = os.path.join(d, f)
            t = _read(p)
            orig = t
            if 'href="/privacy-notice/regional/">EU/UK' not in t:
                t, n = FOOTER_REGIONS.subn(lambda r: COOKIE_LINK.sub(_inject, r.group(0)), t)
                if t != orig:
                    linked += 1
            if GPC_TAG not in t and "</body>" in t:
                t = t.replace("</body>", GPC_TAG + "\n</body>", 1)
                scripted += 1
            if t != orig:
                _write(p, t)
    return [f"footer links added on {linked} page(s); GPC script on {scripted} page(s)"]


def copy_gpc(root):
    _write(os.path.join(root, GPC_ASSET), _read(os.path.join(SRC, "gpc.js")))
    return [f"{GPC_ASSET}: written"]


def add_to_sitemap(root):
    p = os.path.join(root, "sitemap.xml")
    if not os.path.exists(p):
        return ["sitemap.xml: not found, skipped"]
    t = _read(p)
    added = 0
    for rel in PAGES:
        loc = BASE + rel[: -len("index.html")]
        if f"<loc>{loc}</loc>" in t:
            continue
        t = t.replace("</urlset>", f"  <url><loc>{loc}</loc><lastmod>2026-11-16</lastmod></url>\n</urlset>", 1)
        added += 1
    _write(p, t)
    return [f"sitemap.xml: {added} compliance page(s) added"]


def focusable_tables(root):
    """Legal and briefing tables scroll sideways on phones (display:block; overflow-x:auto), so keyboard users
    must be able to focus them (WCAG 2.1.1, axe scrollable-region-focusable)."""
    changed = 0
    for d, _, fs in os.walk(root):
        for f in fs:
            if not f.endswith(".html"):
                continue
            p = os.path.join(d, f)
            t = _read(p)
            t2, n = re.subn(r"<table>", '<table tabindex="0">', t)
            if n:
                _write(p, t2)
                changed += n
    return [f"{changed} table(s) made keyboard-focusable"]


def apply(root):
    notes = build_pages(root)
    notes += focusable_tables(root)
    notes += add_links_and_gpc(root)
    notes += copy_gpc(root)
    notes += add_to_sitemap(root)
    return notes


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(HERE), "site-deploy")
    for n in apply(target):
        print(f"- {n}")

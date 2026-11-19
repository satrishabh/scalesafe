"""Bring changes from the live site (scalesafe.co.in) into site-deploy/, re-applying our fixes.

Usage (from the repo root):
    python tools/sync_from_live.py            # crawl, patch, update site-deploy/, print a summary
    python tools/sync_from_live.py --dry-run  # crawl and patch into .sync/, leave site-deploy/ untouched

Workflow: change the live site as usual -> run this -> review `git diff site-deploy` -> commit ->
tools/release.sh to build on AIO and update the preview.

After the fixes below, tools/insights.py regenerates /insights (one page per article on the home
page, listing, sitemap entries, home-page links). If it cannot extract the articles, the sync stops
with exit code 2 and site-deploy/ is left as it was. Then tools/compliance.py adds the
accessibility statement, the EU/UK/US privacy supplement, their footer links and the Global
Privacy Control confirmation script.

Standard library only. Polite crawl: honours robots.txt, same host only, rate-limited.
"""
import argparse
import datetime as dt
import filecmp
import os
import re
import shutil
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from collections import deque

sys.dont_write_bytecode = True  # no tools/__pycache__ in the repo
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import insights  # noqa: E402  (tools/insights.py: generates /insights from the home page articles)
import compliance  # noqa: E402  (tools/compliance.py: accessibility statement, EU/UK/US privacy, GPC)
import solutions  # noqa: E402  (tools/solutions.py: /solutions/ page)
import forms  # noqa: E402  (tools/forms.py: forms post to the ScaleSafe API on Azure; no Turnstile/formsubmit.co)

HOST = "scalesafe.co.in"
BASE = f"https://{HOST}/"
UA = "Mozilla/5.0 (compatible; scalesafe-site-sync/1.0)"
DELAY = 0.3
MAX_FILES = 800
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE = os.path.join(REPO, "site-deploy")
PATCHES = os.path.join(REPO, "tools", "patches")
# Files we add that do not exist on the live site; carried over from site-deploy/ as-is.
OVERLAY = ["llms.txt", "_headers"]
CSS_MARKER = "/* --- audit fixes (2026-11-14) --- */"
# Design pass (client feedback 2026-11-17): one type system on every device and every page.
DESIGN_CSS = "design-system.css"   # home page (and so /insights, which reuses its CSS) + investor desk
LEGAL_CSS = "legal-brand.css"      # pages on the plain legal template (privacy, terms, cookies, 404, ...)
LEGAL_TEMPLATE_SIGN = '<header class="site">'
FONT_PRELOADS = (
    '<link rel="preload" href="/assets/fonts/inter-latin-var.woff2" as="font" type="font/woff2" crossorigin>\n'
    '<link rel="preload" href="/assets/fonts/source-serif-4-latin-var.woff2" as="font" type="font/woff2" crossorigin>\n'
)


NAV_MARKER = "<!-- ss-nav: solutions + phone menu -->"
SOLUTIONS_LINK = '<a class="nav-link nav-solutions" href="/solutions/">Solutions</a>'
PHONE_MENU = NAV_MARKER + """
      <details class="mobile-menu">
        <summary aria-label="Menu"><span class="mm-bars" aria-hidden="true"></span><span class="mm-label">Menu</span></summary>
        <nav class="mobile-menu-panel" aria-label="Site sections">
          <a href="/solutions/">Solutions</a>
          <a href="/#platform">Platform</a>
          <a href="/#registrations">Registrations</a>
          <a href="/#services">Services</a>
          <a href="/insights/">Resources</a>
          <a class="mm-cta" href="/#contact">Book a walkthrough</a>
        </nav>
      </details>
      <script src="/assets/site/menu-v1.js" defer></script>"""


def add_nav(text):
    """Solutions link first in the header section links, and the phone menu after the header actions. Idempotent."""
    if NAV_MARKER in text:
        return text, "home: Solutions link and phone menu already present"
    links = re.search(r'(<div class="links">\s*)', text)
    actions = re.search(r'<div class="actions"><button class="btn primary nav-link" data-go="contact">Book a walkthrough</button></div>', text)
    if not links or not actions:
        return text, "home: header links/actions block not found; Solutions link and phone menu not added"
    text = text[:actions.end()] + "\n      " + PHONE_MENU + text[actions.end():]
    text = text[:links.end()] + SOLUTIONS_LINK + "\n        " + text[links.end():]
    return text, "home: Solutions link and phone menu added"


SKIP_LINK = '<a class="skip-link" href="#main">Skip to content</a>'


def add_skip_link(text, page):
    """WCAG 2.4.1: a skip link first in <body> and a <main id="main"> target (the desk had no <main>). Idempotent."""
    if SKIP_LINK in text:
        return text, f"{page}: skip link already present"
    body = re.search(r"<body[^>]*>", text)
    if not body:
        return None, f"{page}: no <body>; skip link not added"
    if re.search(r'<main[^>]*\bid="main"', text):
        pass
    elif re.search(r"<main>", text):
        text = text.replace("<main>", '<main id="main" tabindex="-1">', 1)
    elif '<article class="article">' in text and text.count("</article>") == 1:
        text = text.replace('<article class="article">', '<main id="main" tabindex="-1">\n<article class="article">', 1)
        text = text.replace("</article>", "</article>\n</main>", 1)
    else:
        return None, f"{page}: no <main> or single <article> to target; skip link not added"
    body = re.search(r"<body[^>]*>", text)
    return text[:body.end()] + "\n" + SKIP_LINK + text[body.end():], f"{page}: skip link and main landmark added"


def inject_style(text, css_name):
    """Add tools/patches/<css_name> as the last <style> in <head>, plus font preloads. Idempotent.
    Returns (text, note) or (None, error)."""
    css = read(os.path.join(PATCHES, css_name))
    marker = css.splitlines()[0]
    if marker in text:
        return text, "already present"
    if "</head>" not in text:
        return None, "no </head> found"
    if "inter-latin-var.woff2\" as=\"font\"" not in text:
        text = text.replace("<style", FONT_PRELOADS + "<style", 1) if "<style" in text else text.replace("</head>", FONT_PRELOADS + "</head>", 1)
    return text.replace("</head>", "<style>\n" + css + "</style>\n</head>", 1), "added"


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.headers.get("Content-Type", ""), r.read(), r.geturl()
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Content-Type", ""), e.read(), url


def local_path(root, url):
    p = urllib.parse.urlsplit(url)
    path = p.path or "/"
    if path.endswith("/"):
        path += "index.html"
    elif not os.path.splitext(path)[1]:
        path += "/index.html"
    return os.path.join(root, path.lstrip("/").replace("/", os.sep))


URL_RE = re.compile(r"""(?:href|src|poster|data-src)\s*=\s*["']([^"'#>]+)["']""", re.I)
SRCSET_RE = re.compile(r"""srcset\s*=\s*["']([^"']+)["']""", re.I)
CSS_URL_RE = re.compile(r"""url\(\s*["']?([^"')]+)["']?\s*\)""", re.I)
JS_PATH_RE = re.compile(r"""["'](/[A-Za-z0-9_\-./]+\.(?:css|js|json|png|jpe?g|webp|svg|ico|woff2?|pdf|xml|txt|webmanifest))["']""")


def links(base_url, body, ctype):
    text = body.decode("utf-8", errors="ignore")
    cands = []
    if "css" in ctype:
        cands = CSS_URL_RE.findall(text)
    elif "html" in ctype or "xml" in ctype or "json" in ctype or "javascript" in ctype:
        cands = URL_RE.findall(text) + CSS_URL_RE.findall(text) + JS_PATH_RE.findall(text)
        for ss in SRCSET_RE.findall(text):
            cands += [part.strip().split(" ")[0] for part in ss.split(",") if part.strip()]
        # Article images are built in JavaScript from data-article slugs.
        for slug in set(re.findall(r'data-article="([^"]+)"', text)):
            cands.append(f"/img/articles/{slug}.jpg")
            cands += [f"/img/articles/webp/{slug}-{w}.webp" for w in (480, 800, 1200)]
    out = []
    for c in cands:
        c = c.strip()
        if not c or c.startswith(("data:", "mailto:", "tel:", "javascript:")):
            continue
        # Skip JavaScript fragments the regexes pick up: member expressions such as
        # `location.href`, and bare directory prefixes such as '/img/articles/'+slug.
        if re.fullmatch(r"[A-Za-z_$][\w$]*(\.[A-Za-z_$][\w$]*)+", c) or c.rstrip("/") in ("/img/articles", "/img/articles/webp"):
            continue
        u = urllib.parse.urldefrag(urllib.parse.urljoin(base_url, c))[0]
        if urllib.parse.urlsplit(u).netloc == HOST:
            out.append(u.split("?")[0])
    return out


def crawl(dest):
    rp = urllib.robotparser.RobotFileParser()
    status, _, body, _ = fetch(BASE + "robots.txt")
    if status != 200:
        sys.exit(f"robots.txt returned {status}; stopping")
    rp.parse(body.decode("utf-8", errors="ignore").splitlines())

    seen, queue, saved, problems = set(), deque(), 0, []
    for start in ["", "sitemap.xml", "robots.txt", "favicon.ico", "site.webmanifest"]:
        queue.append(BASE + start)
        seen.add(BASE + start)
    # Every sitemap URL, so new pages are picked up.
    status, _, sm, _ = fetch(BASE + "sitemap.xml")
    for loc in re.findall(r"<loc>([^<]+)</loc>", sm.decode("utf-8", errors="ignore")):
        if loc not in seen:
            seen.add(loc)
            queue.append(loc)

    while queue and saved < MAX_FILES:
        url = queue.popleft()
        if not rp.can_fetch(UA, url):
            continue
        status, ctype, body, final = fetch(url)
        time.sleep(DELAY)
        if status != 200:
            problems.append(f"{status} {url}")
            continue
        path = local_path(dest, final)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(body)
        saved += 1
        for link in links(final, body, ctype):
            if link not in seen:
                seen.add(link)
                queue.append(link)

    # The 404 page is only reachable as an error response.
    status, _, body, _ = fetch(BASE + "this-page-does-not-exist-sync-check/")
    if status == 404:
        with open(os.path.join(dest, "404.html"), "wb") as f:
            f.write(body)
        saved += 1
    else:
        problems.append(f"404 page check returned {status}")
    return saved, problems


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def write(path, text):
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)


# Applied in order: darken the muted grey first, then move the lighter grey onto the old muted value.
CONTRAST = [("#68737B", "#5F6A72"), ("#8A949A", "#68737B")]


def contrast_fix(text):
    """Darken the home page's low-contrast greys (case-insensitive). Idempotent."""
    total = 0
    for old, new in CONTRAST:
        text, n = re.subn(re.escape(old), new, text, flags=re.I)
        total += n
    return text, total


def patch(root):
    """Re-apply our fixes. Each step is idempotent and reports what it did."""
    notes, errors = [], []

    # 0. Cloudflare injects its Web Analytics beacon into HTML at the edge; it is not part of the
    #    site source. Strip it so preview visits are not counted as scalesafe.co.in traffic.
    #    Served through Cloudflare with analytics on, the real domain gets it injected again.
    beacon = re.compile(r'[ \t]*<script[^>]*static\.cloudflareinsights\.com/beacon\.min\.js[^>]*>\s*</script>[ \t]*\r?\n?', re.I)
    stripped = 0
    for d, _, fs in os.walk(root):
        for f in fs:
            if f.endswith(".html"):
                p = os.path.join(d, f)
                t = read(p)
                t2, n = beacon.subn("", t)
                if n:
                    write(p, t2)
                    stripped += n
    notes.append(f"Cloudflare analytics beacon removed from {stripped} place(s)")

    # 1. Home page: one H1 (hero). Other bare <h1> headings become <h2 class="h1-as-h2">.
    #    <h1 id="articleTitle"> (the hidden article view) is left alone.
    home = os.path.join(root, "index.html")
    h = read(home)
    count = {"n": 0}

    def demote(m):
        count["n"] += 1
        return m.group(0) if count["n"] == 1 else f'<h2 class="h1-as-h2">{m.group(1)}</h2>'

    h_new = re.sub(r"<h1>(.*?)</h1>", demote, h, flags=re.S)
    demoted = max(count["n"] - 1, 0)
    notes.append(f"home: {demoted} section heading(s) h1 -> h2")

    # 2. Home page: design-correction CSS before </head>.
    css = read(os.path.join(PATCHES, "home-fixes.css"))
    if CSS_MARKER in h_new:
        notes.append("home: CSS fixes already present")
    elif "</head>" in h_new:
        h_new = h_new.replace("</head>", "<style>\n" + css + "</style>\n</head>", 1)
        notes.append("home: CSS fixes added")
    else:
        errors.append("home: no </head> found; CSS fixes not applied")
    # 2b. Home page: WCAG 2.1 AA text contrast. Muted grey #68737B is 4.24:1 on the mint and 4.49:1 on the
    #     cream sections, and #8A949A is 3.09:1 on white; AA needs 4.5:1. /insights inherits this CSS.
    h_new, n_contrast = contrast_fix(h_new)
    notes.append(f"home: {n_contrast} low-contrast colour(s) darkened")
    # 2c. Home page: design system pass, after every other style so it wins the cascade.
    h_out, note = inject_style(h_new, DESIGN_CSS)
    if h_out is None:
        errors.append(f"home: {DESIGN_CSS} not applied ({note})")
    else:
        h_new = h_out
        notes.append(f"home: {DESIGN_CSS} {note}")
    # 2d. Home header: a Solutions link (/solutions/, built by tools/solutions.py) and a phone menu.
    #     The live header hides its section buttons at <=800px and has no menu, so phones could only
    #     reach Platform/Registrations/Services/Resources from the footer. /insights and /solutions
    #     reuse this header, so they get both too.
    # 2e. Legal footer: readable line length (tools/patches/footer-layout.css). /insights and /solutions reuse it.
    h_out, note = inject_style(h_new, "footer-layout.css")
    if h_out is None:
        errors.append(f"home: footer-layout.css not applied ({note})")
    else:
        h_new = h_out
        notes.append(f"home: footer-layout.css {note}")
    h_new, note = add_nav(h_new)
    (notes if "not found" not in note else errors).append(note)
    h_out, note = add_skip_link(h_new, "home")
    if h_out is None:
        errors.append(note)
    else:
        h_new = h_out
        notes.append(note)
    h1_left = len(re.findall(r"<h1[ >]", h_new))
    if h1_left > 2:
        errors.append(f"home: {h1_left} <h1> tags remain (expected 2: hero + article view)")
    if 'class="footer-legal"' not in h_new:
        errors.append("home: footer-legal block not found; footer CSS fix may no longer apply")
    write(home, h_new)

    # 3. Canonical on pages that lack one (live site misses it on the investor desk).
    for rel in ["accredited-investor-desk/index.html"]:
        p = os.path.join(root, rel)
        if not os.path.exists(p):
            notes.append(f"{rel}: not on the live site any more")
            continue
        t = read(p)
        if 'rel="canonical"' in t:
            notes.append(f"{rel}: canonical already present")
        else:
            url = BASE + rel[: -len("index.html")]
            t = t.replace("</head>", f'<link rel="canonical" href="{url}">\n</head>', 1)
            write(p, t)
            notes.append(f"{rel}: canonical added")

    # 4. 404 page must not declare a canonical.
    p404 = os.path.join(root, "404.html")
    if os.path.exists(p404):
        t = read(p404)
        t2 = re.sub(r'\s*<link rel="canonical" href="[^"]*404\.html"\s*/?>', "", t, count=1)
        if t2 != t:
            write(p404, t2)
            notes.append("404.html: bogus canonical removed")

    # 4b. Same type system on the other pages: brand fonts on the legal template (it asked for Inter,
    #     which is never loaded, so every device showed its own system font), design pass on the desk.
    #     Runs before compliance.py, which builds its pages from the (now patched) cookie-notice template.
    styled = {"legal": 0, "desk": 0}
    for d, _, fs in os.walk(root):
        for f in fs:
            if not f.endswith(".html"):
                continue
            p = os.path.join(d, f)
            rel = os.path.relpath(p, root).replace(os.sep, "/")
            if rel == "index.html":
                continue
            t = read(p)
            if LEGAL_TEMPLATE_SIGN in t:
                kind, css_name = "legal", LEGAL_CSS
            elif rel == "accredited-investor-desk/index.html":
                kind, css_name = "desk", DESIGN_CSS
            else:
                continue
            t2, note = inject_style(t, css_name)
            if t2 is not None and kind == "desk":
                t3, skip_note = add_skip_link(t2, rel)
                if t3 is None:
                    errors.append(skip_note)
                else:
                    t2 = t3
            if t2 is None:
                errors.append(f"{rel}: {css_name} not applied ({note})")
            elif t2 != t:
                write(p, t2)
                styled[kind] += 1
    notes.append(f"brand type added to {styled['legal']} legal page(s) and {styled['desk']} desk page(s)")

    # 4c. Phone-menu script (external: /insights forbids inline scripts in the header it reuses).
    os.makedirs(os.path.join(root, "assets", "site"), exist_ok=True)
    shutil.copy2(os.path.join(PATCHES, "menu.js"), os.path.join(root, "assets", "site", "menu-v1.js"))
    notes.append("assets/site/menu-v1.js: written")

    # 5. Files we add on top of the live site.
    for name in OVERLAY:
        src = os.path.join(SITE, name)
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(root, name))
            notes.append(f"{name}: carried over")
    return notes, errors


def mirror_into(src, dst):
    """Make dst match src: copy new/changed files, delete files that are gone. Returns a change list."""
    changes = []
    src_files = {os.path.relpath(os.path.join(d, f), src) for d, _, fs in os.walk(src) for f in fs}
    dst_files = {os.path.relpath(os.path.join(d, f), dst) for d, _, fs in os.walk(dst) for f in fs}
    for rel in sorted(src_files):
        s, d = os.path.join(src, rel), os.path.join(dst, rel)
        if rel not in dst_files:
            changes.append(f"added    {rel}")
        elif not same_content(s, d):
            changes.append(f"changed  {rel}")
        else:
            continue
        os.makedirs(os.path.dirname(d), exist_ok=True)
        shutil.copy2(s, d)
    for rel in sorted(dst_files - src_files):
        os.remove(os.path.join(dst, rel))
        changes.append(f"removed  {rel}")
    return changes


def same_content(a, b):
    """Compare ignoring CRLF vs LF, which git normalises anyway."""
    if filecmp.cmp(a, b, shallow=False):
        return True
    with open(a, "rb") as fa, open(b, "rb") as fb:
        return fa.read().replace(b"\r\n", b"\n") == fb.read().replace(b"\r\n", b"\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="do not modify site-deploy/")
    args = ap.parse_args()

    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    work = os.path.join(REPO, ".sync", f"live-{stamp}")
    os.makedirs(work)
    print(f"Crawling {BASE} into {os.path.relpath(work, REPO)} ...")
    saved, problems = crawl(work)
    print(f"  {saved} files fetched")
    for p in problems:
        print(f"  ! {p}")

    notes, errors = patch(work)
    print("Fixes:")
    for n in notes:
        print(f"  - {n}")
    if errors:
        print("Problems (site-deploy/ NOT updated):")
        for e in errors:
            print(f"  ! {e}")
        sys.exit(2)

    # /insights is rebuilt from the freshly crawled and patched home page on every sync.
    # Any extraction problem stops the sync here, before site-deploy/ is touched.
    print("Insights:")
    try:
        for n in insights.generate(work):
            print(f"  - {n}")
    except insights.InsightsError as e:
        print("Problems (site-deploy/ NOT updated):")
        print(f"  ! insights: {e}")
        sys.exit(2)

    # /solutions/ reuses the home header/footer and the /insights stylesheet, so it is built after /insights.
    print("Solutions:")
    try:
        for n in solutions.generate(work):
            print(f"  - {n}")
    except insights.InsightsError as e:
        print("Problems (site-deploy/ NOT updated):")
        print(f"  ! solutions: {e}")
        sys.exit(2)

    # Accessibility statement, EU/UK/US privacy supplement, footer links and GPC confirmation,
    # added after /insights so the generated briefings get them too.
    print("Compliance:")
    try:
        for n in compliance.apply(work):
            print(f"  - {n}")
    except compliance.ComplianceError as e:
        print("Problems (site-deploy/ NOT updated):")
        print(f"  ! compliance: {e}")
        sys.exit(2)

    # Forms on Azure (tools/forms.py): no Turnstile/formsubmit.co, forms post to the ScaleSafe API, notices updated.
    print("Forms:")
    try:
        for n in forms.apply(work):
            print(f"  - {n}")
    except forms.FormsError as e:
        print("Problems (site-deploy/ NOT updated):")
        print(f"  ! forms: {e}")
        sys.exit(2)

    if args.dry_run:
        print(f"Dry run: patched copy left in {os.path.relpath(work, REPO)}; site-deploy/ untouched.")
        return

    changes = mirror_into(work, SITE)
    if changes:
        print(f"site-deploy/: {len(changes)} change(s)")
        for c in changes:
            print(f"  {c}")
        print("Next: review `git diff --stat site-deploy`, commit, then run tools/release.sh.")
    else:
        print("site-deploy/: already up to date with the live site.")
    shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()

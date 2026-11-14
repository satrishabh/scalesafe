"""Bring changes from the live site (scalesafe.co.in) into site-deploy/, re-applying our fixes.

Usage (from the repo root):
    python tools/sync_from_live.py            # crawl, patch, update site-deploy/, print a summary
    python tools/sync_from_live.py --dry-run  # crawl and patch into .sync/, leave site-deploy/ untouched

Workflow: change the live site as usual -> run this -> review `git diff site-deploy` -> commit ->
tools/release.sh to build on AIO and update the preview.

After the fixes below, tools/insights.py regenerates /insights (one page per article on the home
page, listing, sitemap entries, home-page links). If it cannot extract the articles, the sync stops
with exit code 2 and site-deploy/ is left as it was.

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

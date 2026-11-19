"""Generate the crawlable /insights section from the articles embedded in the home page.

The live home page is a single-page app: its 47+ regulatory briefings live in a JavaScript
object `const ARTICLES={...}` (JSON: cat, title, intro, date, dateISO, meta, read, body, source,
sourceUrl, keywords, status?, updated?, updatedISO?), with image alt text in
`const ARTICLE_HEADER_ALTS={...}` and the listing cards (`<article class="blog-card blog-item">`,
whose `data-cat`/`data-tags` carry the IA/RA/PMS/AIF registration types) in `#blogGrid`.
`openArticle(id)` renders one of them into the hidden `#article` view.

This script turns that into real pages:
    insights/index.html           listing, newest first, filter by IA / RA / PMS / AIF
    insights/<slug>/index.html    one page per article
    assets/insights/insights-<hash>.css|js   shared stylesheet (the home page's own CSS) and script
and updates sitemap.xml, llms.txt and the home page links (idempotently).

Usage:
    python tools/insights.py                  # regenerate inside site-deploy/
    python tools/insights.py --root .sync/x   # regenerate inside another copy of the site
tools/sync_from_live.py calls generate() after its own patches, on every sync.

Fails loudly: if extraction finds no articles or a required field is missing, it raises
InsightsError (exit code 2 when run alone) and writes nothing.
Standard library only.
"""
import argparse
import datetime as dt
import hashlib
import html
import json
import os
import re
import shutil
import sys
from html.parser import HTMLParser

ORIGIN = "https://scalesafe.co.in"
SECTION = "/insights/"
DEFAULT_ENDPOINT = "https://api.scalesafe.co.in/partners/api/v1/public/subscriptions"
REG_TYPES = ["IA", "RA", "PMS", "AIF"]
REQUIRED = ["title", "cat", "intro", "date", "dateISO", "read", "body", "source", "sourceUrl"]
HOME_LINK_MARKER = "<!-- insights-link -->"
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE = os.path.join(REPO, "site-deploy")


class InsightsError(Exception):
    pass


def esc(s):
    return html.escape(s or "", quote=True)


def strip_tags(s):
    return html.unescape(re.sub(r"<[^>]+>", " ", s or "")).strip()


def squash(s):
    return re.sub(r"\s+", " ", s or "").strip()


def clip(s, n=158):
    s = squash(s)
    if len(s) <= n:
        return s
    cut = s[: n - 1].rsplit(" ", 1)[0].rstrip(",;:·—-– ")
    return cut + "…"


def json_ld(obj):
    return json.dumps(obj, ensure_ascii=False, indent=1).replace("</", "<\\/")


# --------------------------------------------------------------------------- extraction

def js_object(text, name):
    m = re.search(r"\bconst\s+" + re.escape(name) + r"\s*=\s*", text)
    if not m:
        raise InsightsError(f"home page: `const {name}=` not found")
    try:
        obj, _ = json.JSONDecoder().raw_decode(text, m.end())
    except ValueError as e:
        raise InsightsError(f"home page: {name} is not parseable JSON ({e})")
    if not isinstance(obj, dict):
        raise InsightsError(f"home page: {name} is not an object")
    return obj


def parse_date(s):
    for fmt in ("%d %b %Y", "%d %B %Y"):
        try:
            return dt.datetime.strptime(squash(s), fmt).date().isoformat()
        except ValueError:
            pass
    return ""


def types_from(*texts):
    found = set()
    for t in texts:
        t = (t or "").lower()
        if re.match(r"\s*all\b", t):  # "ALL REs · ...", "ALL INTERMEDIARIES · ..."
            found.update(x.lower() for x in REG_TYPES)
        found.update(re.findall(r"(?<![a-z0-9])(ia|ra|pms|aif)(?![a-z0-9])", t))
    return [x for x in REG_TYPES if x.lower() in found]


def cards(home):
    """Listing cards in #blogGrid: {slug: {...}} for articles, plus link-out cards (no slug)."""
    by_slug, extras = {}, []
    for m in re.finditer(r'<article class="blog-card blog-item"([^>]*)>(.*?)</article>', home, re.S):
        attrs, inner = m.group(1), m.group(2)
        a = dict(re.findall(r'(data-[a-z]+)="([^"]*)"', attrs))
        p = re.search(r"<p>(.*?)</p>", inner, re.S)
        card = {"dcat": html.unescape(a.get("data-cat", "") + " " + a.get("data-tags", "")),
                "summary": squash(strip_tags(p.group(1))) if p else ""}
        sm = re.search(r'data-article="([^"]+)"', inner)
        if sm:
            by_slug.setdefault(sm.group(1), card)
            continue
        href = re.search(r'<a [^>]*href="(/[^"#]+)"', inner)
        h3 = re.search(r"<h3>(.*?)</h3>", inner, re.S)
        badge = re.search(r'<span class="badge">(.*?)</span>', inner, re.S)
        date = a.get("data-date") or ""
        if href and h3 and parse_date(date):
            status = re.search(r'<span class="status-pill">(.*?)</span>', inner, re.S)
            read = re.search(r"<span>(\d+ min read)</span>", inner)
            extras.append({"href": href.group(1), "title": squash(strip_tags(h3.group(1))),
                           "cat": squash(strip_tags(badge.group(1))) if badge else "",
                           "date": date, "dateISO": parse_date(date),
                           "status": squash(strip_tags(status.group(1))) if status else "",
                           "read": read.group(1) if read else "",
                           "summary": card["summary"], "types": types_from(badge.group(1) if badge else "", card["dcat"])})
    return by_slug, extras


def extract(home):
    raw = js_object(home, "ARTICLES")
    alts = js_object(home, "ARTICLE_HEADER_ALTS")
    if not raw:
        raise InsightsError("home page: ARTICLES is empty; refusing to publish an empty /insights")
    card_by_slug, extras = cards(home)
    problems, arts = [], []
    for order, (slug, a) in enumerate(raw.items()):
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", slug):
            problems.append(f"{slug!r}: slug is not URL-safe")
            continue
        if not isinstance(a, dict):
            problems.append(f"{slug}: not an object")
            continue
        missing = [k for k in REQUIRED if not isinstance(a.get(k), str) or not a[k].strip()]
        if not alts.get(slug):
            missing.append("image alt (ARTICLE_HEADER_ALTS)")
        if missing:
            problems.append(f"{slug}: missing {', '.join(missing)}")
            continue
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", a["dateISO"]):
            problems.append(f"{slug}: dateISO {a['dateISO']!r} is not YYYY-MM-DD")
            continue
        if not re.match(r"https?://", a["sourceUrl"]):
            problems.append(f"{slug}: sourceUrl {a['sourceUrl']!r} is not http(s)")
            continue
        upd = a.get("updatedISO") or ""
        if upd and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", upd):
            upd = ""
        card = card_by_slug.get(slug, {"dcat": "", "summary": ""})
        arts.append({
            "slug": slug, "order": order,
            "title": squash(a["title"]), "cat": squash(a["cat"]), "intro": squash(a["intro"]),
            "date": squash(a["date"]), "dateISO": a["dateISO"],
            "updated": squash(a.get("updated") or ""), "updatedISO": upd,
            "status": squash(a.get("status") or ""), "meta": squash(a.get("meta") or ""),
            "read": squash(a["read"]), "body": a["body"],
            "source": squash(a["source"]), "sourceUrl": a["sourceUrl"].strip(),
            "keywords": squash(a.get("keywords") or ""), "alt": squash(alts[slug]),
            "summary": card["summary"] or squash(a["intro"]),
            "types": types_from(a["cat"], a.get("meta") or "", card["dcat"]),
        })
    if problems:
        raise InsightsError("article extraction failed:\n    " + "\n    ".join(problems))
    arts.sort(key=lambda x: (x["dateISO"], -x["order"]), reverse=True)
    return arts, extras


# --------------------------------------------------------------------------- sanitising

ALLOWED = {"p", "ul", "ol", "li", "b", "strong", "i", "em", "a", "span", "div", "br", "code",
           "blockquote", "sup", "sub", "small", "table", "thead", "tbody", "tr", "th", "td", "hr"}
RENAME = {"h2": "h2", "h3": "h2", "h4": "h3", "h5": "h4"}   # page has the h1; body starts at h2
DROP_WITH_CONTENT = {"script", "style", "iframe", "object", "embed", "template", "noscript",
                     "svg", "math", "form", "select", "textarea", "head", "title", "frame", "frameset"}
VOID = {"br", "hr"}


class Sanitizer(HTMLParser):
    """Rebuilds article HTML from an allowlist. In-page reader buttons become real links."""

    def __init__(self, slugs):
        super().__init__(convert_charrefs=True)
        self.slugs, self.out, self.stack, self.skip = slugs, [], [], 0
        self.links = []          # (href, text) of external links, for JSON-LD citations
        self._link = None

    def handle_starttag(self, tag, attrs):
        if tag in DROP_WITH_CONTENT:
            self.skip += 1
            return
        if self.skip or tag in VOID and tag not in ALLOWED:
            return
        a = {k.lower(): (v or "") for k, v in attrs}
        out_tag, out_attrs = None, []
        cls = " ".join(c for c in a.get("class", "").split() if re.fullmatch(r"[A-Za-z0-9_-]+", c))
        if tag == "button" and a.get("data-article") in self.slugs:
            out_tag = "a"
            out_attrs.append(("href", f"{SECTION}{a['data-article']}/"))
        elif tag == "button":
            out_tag = "span"
        elif tag in RENAME:
            out_tag = RENAME[tag]
        elif tag in ALLOWED:
            out_tag = tag
        if out_tag is None:
            if tag not in ("img", "input", "meta", "link", "source", "wbr", "col", "area", "base", "param", "track"):
                self.stack.append((tag, None))
            return
        if cls:
            out_attrs.insert(0, ("class", cls))
        if a.get("aria-label"):
            out_attrs.append(("aria-label", a["aria-label"]))
        if tag == "a":
            href = a.get("href", "").strip()
            if re.match(r"https?://", href, re.I):
                out_attrs += [("href", href), ("target", "_blank"), ("rel", "noopener noreferrer")]
                self._link = [href, ""]
            elif re.match(r"(/(?!/)|#)", href):
                out_attrs.append(("href", href))
            elif re.match(r"mailto:[^\s\"'<>]+$", href, re.I):
                out_attrs.append(("href", href))
        if tag in ("th", "td"):
            for k in ("colspan", "rowspan"):
                if a.get(k, "").isdigit():
                    out_attrs.append((k, a[k]))
        if out_tag in VOID:
            self.out.append(f"<{out_tag}>")
            return
        self.stack.append((tag, out_tag))
        self.out.append(f"<{out_tag}" + "".join(f' {k}="{esc(v)}"' for k, v in out_attrs) + ">")

    def handle_startendtag(self, tag, attrs):
        if tag in VOID and not self.skip:
            self.out.append(f"<{tag}>")

    def handle_endtag(self, tag):
        if tag in DROP_WITH_CONTENT:
            self.skip = max(self.skip - 1, 0)
            return
        if self.skip or tag in VOID or not any(src == tag for src, _ in self.stack):
            return
        while self.stack:   # close everything opened since the matching start tag
            src, out_tag = self.stack.pop()
            if out_tag:
                self.out.append(f"</{out_tag}>")
            if out_tag == "a" and self._link:
                self.links.append((self._link[0], squash(self._link[1])))
                self._link = None
            if src == tag:
                break

    def handle_data(self, data):
        if self.skip:
            return
        if self._link is not None:
            self._link[1] += data
        self.out.append(html.escape(data, quote=False))

    def result(self):
        while self.stack:
            _, t = self.stack.pop()
            if t:
                self.out.append(f"</{t}>")
        return "".join(self.out).strip()


def sanitize(body, slugs):
    s = Sanitizer(slugs)
    s.feed(body)
    s.close()
    out = s.result()
    if re.search(r"<script|\son[a-z]+\s*=|javascript:", out, re.I):
        raise InsightsError("sanitiser let unsafe markup through")
    return out, s.links


# --------------------------------------------------------------------------- page chrome

def chrome(home):
    """Head assets, header and footer taken from the home page, with SPA buttons made into links."""
    head = re.search(r"<head>(.*?)</head>", home, re.S)
    header = re.search(r'<header class="site-header">.*?</header>', home, re.S)
    footer = re.search(r'<footer class="footer">.*?</footer>', home, re.S)
    if not (head and header and footer):
        raise InsightsError("home page: <head>, <header class=\"site-header\"> or <footer class=\"footer\"> not found")
    css = "\n".join(m.group(1) for m in re.finditer(r"<style[^>]*>(.*?)</style>", head.group(1), re.S))
    if "@font-face" not in css or "--brand-deep" not in css:
        raise InsightsError("home page: brand CSS (fonts / --brand-deep) not found in <head>")
    icons = "\n".join(re.findall(r'<link rel="(?:icon|apple-touch-icon|manifest)"[^>]*>', head.group(1)))

    def linkify(block):
        def rep(m):
            attrs, target, rest, label = m.group(1), m.group(2), m.group(3), m.group(4)
            href = {"home": "/", "resources": SECTION}.get(target, f"/#{target}")
            attrs = re.sub(r'\s*type="button"', "", attrs + rest)
            if target == "resources" and "nav-link" in attrs:
                attrs = attrs.replace('class="', 'class="current ', 1)
                return f'<a{attrs} href="{href}" aria-current="page">{label}</a>'
            return f'<a{attrs} href="{href}">{label}</a>'
        return re.sub(r'<button([^>]*?)\sdata-go="([^"]+)"([^>]*)>(.*?)</button>', rep, block, flags=re.S)

    return {"css": css, "icons": icons, "header": linkify(header.group(0)), "footer": linkify(footer.group(0))}


EXTRA_CSS = r"""
/* --- /insights pages (generated by tools/insights.py) --- */
.skip-link{position:absolute;left:-9999px;top:8px;z-index:100;background:#fff;color:var(--brand-deep);padding:10px 14px;border-radius:8px;font-weight:700}
.skip-link:focus{left:12px}
a:focus-visible,button:focus-visible,input:focus-visible{outline:3px solid var(--brand-sage);outline-offset:2px}
.breadcrumb ol{list-style:none;display:flex;flex-wrap:wrap;gap:6px;margin:0;padding:0}
.breadcrumb li+li::before{content:"/";margin-right:6px;color:#9AA5A0}
.breadcrumb a{color:var(--brand-deep);text-decoration:underline;text-underline-offset:2px}
.insights-main .page-intro h1{overflow-wrap:break-word}
.insights-main .page-intro .article-meta{display:flex;gap:10px 14px;color:#5F6A72;font-size:12.5px;margin-top:18px}
.insights-toolbar{display:flex;gap:14px;align-items:center;justify-content:space-between;flex-wrap:wrap;border-bottom:1px solid var(--brand-mist);padding-bottom:18px;margin-bottom:26px}
.insights-toolbar .blog-filter[aria-pressed=true]{background:var(--brand-deep);border-color:var(--brand-deep);color:#fff}
.insights-toolbar .blog-filter .n{margin-left:4px}  /* no opacity: 2.9:1 contrast at .7 */
.insights-count{font-family:var(--mono);font-size:12px;color:#5F6A72;margin:0}
.insights-grid .blog-card{position:relative}
.insights-grid .blog-card h3 a::after{content:"";position:absolute;inset:0;border-radius:inherit}
.insights-grid .blog-card h3 a:hover{text-decoration:underline;text-underline-offset:3px}
.insights-grid .blog-card:focus-within{outline:3px solid var(--brand-sage);outline-offset:2px}
.insights-grid .blog-card h3 a:focus-visible{outline:none}
.insights-grid .article-bottom .more{color:var(--brand-deep);font-weight:700}
.insights-grid .blog-card[hidden]{display:none}
.insights-empty{padding:24px;border:1px dashed var(--brand-mist);border-radius:12px;color:#5F6A72}
.insights-list-head{margin:0 0 18px}
.insights-list-head h2{font-family:var(--display);font-weight:500;font-size:clamp(24px,3vw,32px);letter-spacing:-.02em;color:var(--brand-deep);margin:0}
.insight-hero{display:block;width:100%;margin:0 0 28px;border-radius:var(--radius,14px);overflow:hidden;background:#E8EEE9;aspect-ratio:16/9}
.insight-hero img{display:block;width:100%;height:100%;object-fit:cover}
.article-body h2{font-family:var(--display);font-weight:500;font-size:24px;letter-spacing:-.02em;line-height:1.25;color:var(--brand-deep);margin:34px 0 9px}
.article-body h3.sub{font-size:18px}
.article-body ol{padding-left:20px;color:#57646C}
.article-body a:not(.btn):not(.text-link):not(.text-btn){color:var(--brand-deep);text-decoration:underline;text-underline-offset:2px;overflow-wrap:anywhere}
.article-body .text-btn{text-decoration:underline;text-underline-offset:2px}
.article-body table{border-collapse:collapse;width:100%;font-size:14px;margin:18px 0;display:block;overflow-x:auto}
.article-body th,.article-body td{border:1px solid var(--brand-mist);padding:8px 10px;text-align:left;vertical-align:top}
.insight-related{margin:28px 0;padding:20px;border:1px solid var(--brand-mist);border-radius:12px;background:#F3F5F0}
.insight-related h2{font-family:var(--font);font-size:15px;font-weight:700;letter-spacing:0;margin:0 0 12px;color:var(--brand-deep)}
.insight-related ul{list-style:none;padding:0;margin:0;display:grid;gap:12px}
.insight-related li{margin:0;line-height:1.45}
.insight-related a{font-weight:700;color:var(--brand-deep);text-decoration:underline;text-underline-offset:2px}
.insight-related small{display:block;font-family:var(--mono);font-size:12px;color:#5F6A72;letter-spacing:.04em;margin-top:2px}
.insight-back{margin:30px 0 0}
.newsletter{margin:40px 0 0;padding:28px;border-radius:16px;background:var(--brand-deep);color:#E8EFEA}
.newsletter h2{font-family:var(--display);font-weight:500;font-size:clamp(22px,2.6vw,28px);letter-spacing:-.02em;line-height:1.2;color:#fff;margin:0 0 8px}
.newsletter>p{color:#C9D8D1!important;font-size:15px!important;line-height:1.6!important;margin:0 0 18px;max-width:640px}
.newsletter form[data-ss-form] label{color:#E8EFEA}
.newsletter .nl-row{display:flex;gap:10px;flex-wrap:wrap;align-items:stretch}
.newsletter .nl-row input[type=email]{flex:1 1 240px;min-width:0}
.newsletter form[data-ss-form] button[type=submit]{width:auto;background:var(--brand-sage);color:var(--brand-deep);font-weight:700;flex:0 0 auto}
.newsletter form[data-ss-form] button[type=submit]:hover{background:#B9D66E}
.newsletter fieldset{border:0;padding:0;margin:16px 0 4px;min-width:0}
.newsletter legend{font-family:var(--mono);font-size:12px;letter-spacing:.06em;color:#C9D8D1;margin-bottom:8px;padding:0}
.newsletter .chips{display:flex;flex-wrap:wrap;gap:8px}
.newsletter .chip{position:relative;display:inline-flex!important;margin:0!important;font-family:var(--mono)!important;font-weight:500!important}
.newsletter .chip input{position:absolute;opacity:0;width:1px;height:1px}
.newsletter .chip span{display:inline-block;padding:7px 14px;border:1px solid rgba(255,255,255,.35);border-radius:999px;font-size:12px;color:#fff;cursor:pointer;min-width:44px;text-align:center}
.newsletter .chip input:checked+span{background:var(--brand-sage);border-color:var(--brand-sage);color:var(--brand-deep)}
.newsletter .chip input:focus-visible+span{outline:3px solid var(--brand-sage);outline-offset:2px}
.newsletter form[data-ss-form] .check{color:#C9D8D1;font-family:var(--font);font-weight:400;font-size:13px;line-height:1.55;margin-top:14px}
.newsletter a,.article-body .newsletter a:not(.btn){color:#fff;text-decoration:underline;text-underline-offset:2px}
.newsletter .ss-status{min-height:0;margin:0;font-size:14px;line-height:1.5}
.newsletter .ss-status:not(:empty){margin-top:12px}
.newsletter legend{float:left;width:100%}
.newsletter .chips{clear:both}
.newsletter .ss-status[data-kind=ok]{color:var(--brand-sage)}
.newsletter .ss-status[data-kind=error]{color:#FFD2CC}
.newsletter .nl-fallback{font-size:13px;color:#C9D8D1}
.newsletter .nl-fallback a{color:#fff;text-decoration:underline}
@media(max-width:560px){
  .newsletter{padding:22px 18px}
  .newsletter .nl-row button{flex:1 1 100%!important}
  .insights-main .page-intro h1{font-size:32px}
  .insights-toolbar{gap:10px}
}
"""

SCRIPT = r"""/* /insights: registration-type filter and newsletter sign-up. Generated by tools/insights.py. */
(function () {
  'use strict';
  // ---- filters (listing page) ----
  var bar = document.querySelector('[data-insights-filters]');
  if (bar) {
    var items = Array.prototype.slice.call(document.querySelectorAll('[data-insight-types]'));
    var count = document.getElementById('insightsCount');
    var empty = document.getElementById('insightsEmpty');
    var buttons = Array.prototype.slice.call(bar.querySelectorAll('button[data-filter]'));
    var apply = function (f, push) {
      var shown = 0;
      items.forEach(function (it) {
        var ok = f === 'all' || (' ' + it.getAttribute('data-insight-types') + ' ').indexOf(' ' + f + ' ') >= 0;
        it.hidden = !ok; if (ok) shown++;
      });
      buttons.forEach(function (b) { b.setAttribute('aria-pressed', b.getAttribute('data-filter') === f ? 'true' : 'false'); });
      if (count) count.textContent = shown + (shown === 1 ? ' briefing' : ' briefings') + (f === 'all' ? '' : ' for ' + f.toUpperCase());
      if (empty) empty.hidden = shown !== 0;
      if (push) {
        var u = new URL(location.href);
        if (f === 'all') u.searchParams.delete('type'); else u.searchParams.set('type', f);
        history.replaceState(null, '', u.pathname + u.search + u.hash);
      }
    };
    bar.addEventListener('click', function (e) {
      var b = e.target.closest('button[data-filter]');
      if (b) apply(b.getAttribute('data-filter'), true);
    });
    var t = (new URLSearchParams(location.search).get('type') || '').toLowerCase();
    if (buttons.some(function (b) { return b.getAttribute('data-filter') === t; })) apply(t, false);
  }

  // ---- newsletter ----
  Array.prototype.forEach.call(document.querySelectorAll('form[data-newsletter]'), function (form) {
    form.hidden = false;
    var fb = form.parentNode.querySelector('.nl-fallback'); if (fb) fb.hidden = true;
    var email = form.querySelector('input[type=email]');
    var consent = form.querySelector('input[name=consent]');
    var btn = form.querySelector('button[type=submit]');
    var ok = form.querySelector('[role=status]');
    var err = form.querySelector('[role=alert]');
    var say = function (okMsg, errMsg) {
      ok.textContent = okMsg || ''; ok.setAttribute('data-kind', okMsg ? 'ok' : '');
      err.textContent = errMsg || ''; err.setAttribute('data-kind', errMsg ? 'error' : '');
    };
    var MAIL = 'If this keeps happening, email hello@scalesafe.co.in with "Subscribe" in the subject.';
    form.addEventListener('submit', function (e) {
      e.preventDefault();
      say('', '');
      email.removeAttribute('aria-invalid'); consent.removeAttribute('aria-invalid');
      var value = (email.value || '').trim();
      if (!value || !email.checkValidity()) {
        email.setAttribute('aria-invalid', 'true'); say('', 'Enter a valid email address.'); email.focus(); return;
      }
      if (!consent.checked) {
        consent.setAttribute('aria-invalid', 'true'); say('', 'Please tick the consent box so we can email you.'); consent.focus(); return;
      }
      var topics = Array.prototype.map.call(form.querySelectorAll('input[name=topics]:checked'), function (c) { return c.value; });
      var body = { email: value, consent: true };
      if (topics.length) body.topics = topics;
      var endpoint = form.getAttribute('data-endpoint');
      var ctrl = 'AbortController' in window ? new AbortController() : null;
      var timer = ctrl ? setTimeout(function () { ctrl.abort(); }, 12000) : null;
      btn.disabled = true; btn.setAttribute('aria-busy', 'true');
      fetch(endpoint, {
        method: 'POST', mode: 'cors', credentials: 'omit',
        headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
        body: JSON.stringify(body), signal: ctrl ? ctrl.signal : undefined
      }).then(function (r) {
        if (r.status === 202 || r.status === 200 || r.status === 201) {
          form.reset();
          say('Almost done: check your inbox and click the confirmation link to start receiving briefings.', '');
        } else if (r.status === 400 || r.status === 422) {
          say('', 'We could not accept that address. Please check it and try again.');
        } else if (r.status === 429) {
          say('', 'Too many attempts from this connection. Please wait a minute and try again.');
        } else {
          say('', 'Sign-up is not available right now (error ' + r.status + '). ' + MAIL);
        }
      }).catch(function () {
        say('', 'We could not reach the subscription service. Please check your connection and try again later. ' + MAIL);
      }).then(function () {
        if (timer) clearTimeout(timer);
        btn.disabled = false; btn.removeAttribute('aria-busy');
      });
    });
  });
})();
"""


def newsletter(endpoint, uid):
    chips = "".join(f'<label class="chip"><input type="checkbox" name="topics" value="{t}"><span>{t}</span></label>'
                    for t in REG_TYPES)
    return f"""<section class="newsletter" id="newsletter" aria-labelledby="nl-title-{uid}">
  <h2 id="nl-title-{uid}">Get new SEBI briefings by email</h2>
  <p>One email when we publish a new primary-source briefing. Choose the registration types you care about, or leave them all unticked for everything. Unsubscribe at any time.</p>
  <form data-newsletter data-ss-form data-endpoint="{esc(endpoint)}" novalidate hidden>
    <label for="nl-email-{uid}">Work email</label>
    <div class="nl-row">
      <input type="email" id="nl-email-{uid}" name="email" autocomplete="email" inputmode="email" required placeholder="you@firm.in">
      <button type="submit">Subscribe</button>
    </div>
    <fieldset>
      <legend>Topics (optional)</legend>
      <div class="chips">{chips}</div>
    </fieldset>
    <label class="check"><input type="checkbox" name="consent" required> <span>I agree to receive ScaleSafe regulatory briefings by email. ScaleSafe will use my email address only for this, as described in the <a href="/privacy-notice/">Privacy Notice</a>.</span></label>
    <p class="ss-status" role="status" aria-live="polite"></p>
    <p class="ss-status" role="alert"></p>
  </form>
  <p class="nl-fallback">To subscribe, email <a href="mailto:hello@scalesafe.co.in?subject=Subscribe%20to%20briefings">hello@scalesafe.co.in</a> with &ldquo;Subscribe&rdquo; in the subject.</p>
</section>"""


def page(c, assets, *, title, description, canonical, og_type, image, image_alt, extra_meta, ld, main):
    return f"""<!doctype html>
<html lang="en-IN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>{esc(title)}</title>
<meta name="description" content="{esc(description)}">
<meta name="robots" content="index,follow,max-image-preview:large,max-snippet:-1,max-video-preview:-1">
<link rel="canonical" href="{esc(canonical)}">
<meta property="og:type" content="{og_type}">
<meta property="og:site_name" content="ScaleSafe">
<meta property="og:locale" content="en_IN">
<meta property="og:url" content="{esc(canonical)}">
<meta property="og:title" content="{esc(title)}">
<meta property="og:description" content="{esc(description)}">
<meta property="og:image" content="{esc(image[0])}">
<meta property="og:image:width" content="{image[1]}">
<meta property="og:image:height" content="{image[2]}">
<meta property="og:image:alt" content="{esc(image_alt)}">
{extra_meta}<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{esc(title)}">
<meta name="twitter:description" content="{esc(description)}">
<meta name="twitter:image" content="{esc(image[0])}">
<meta name="twitter:image:alt" content="{esc(image_alt)}">
<meta name="theme-color" content="#0F3D32">
<meta name="color-scheme" content="light">
{c['icons']}
<link rel="preload" href="/assets/fonts/source-serif-4-latin-var.woff2" as="font" type="font/woff2" crossorigin>
<link rel="preload" href="/assets/fonts/inter-latin-var.woff2" as="font" type="font/woff2" crossorigin>
<link rel="stylesheet" href="{assets['css']}">
<script type="application/ld+json">
{ld}
</script>
<script src="{assets['js']}" defer></script>
</head>
<body>
<a class="skip-link" href="#main">Skip to content</a>
{c['header']}
<main id="main" class="insights-main">
{main}
</main>
{c['footer']}
</body>
</html>
"""


def breadcrumb_ld(items):
    return {"@type": "BreadcrumbList", "itemListElement": [
        {"@type": "ListItem", "position": i + 1, "name": n, "item": u} for i, (n, u) in enumerate(items)]}


def time_tag(iso, text):
    return f'<time datetime="{esc(iso)}">{esc(text)}</time>'


def picture(slug, alt, sizes, eager, have_webp):
    load = 'loading="eager" fetchpriority="high"' if eager else 'loading="lazy"'
    src = ""
    if have_webp:
        src = (f'<source type="image/webp" sizes="{sizes}" srcset="/img/articles/webp/{slug}-480.webp 480w, '
               f'/img/articles/webp/{slug}-800.webp 800w, /img/articles/webp/{slug}-1200.webp 1200w">')
    return (f'{src}<img src="/img/articles/{slug}.jpg" alt="{esc(alt)}" width="1200" height="675" '
            f'{load} decoding="async">')


def related(art, arts, n=3):
    def score(o):
        s = 2 * len(set(o["types"]) & set(art["types"]))
        if o["cat"].split("·")[0].strip() == art["cat"].split("·")[0].strip():
            s += 3
        return s
    pool = [o for o in arts if o["slug"] != art["slug"]]
    pool.sort(key=lambda o: (score(o), o["dateISO"]), reverse=True)
    return pool[:n]


def article_page(art, arts, c, assets, endpoint, have_webp):
    slug = art["slug"]
    url = f"{ORIGIN}{SECTION}{slug}/"
    body, links = sanitize(art["body"], {a["slug"] for a in arts})
    title = f"{art['title']} | ScaleSafe Insights"
    desc = clip(art["summary"])
    modified = art["updatedISO"] or art["dateISO"]
    img = f"{ORIGIN}/img/articles/{slug}.jpg"
    cites = [art["sourceUrl"]] + [h for h, _ in links if h != art["sourceUrl"]]
    cites = list(dict.fromkeys(cites))
    minutes = re.match(r"\d+", art["read"])
    article_ld = {
        "@type": "Article", "@id": url + "#article", "headline": art["title"][:110], "name": art["title"],
        "description": art["intro"], "datePublished": art["dateISO"], "dateModified": modified,
        "image": {"@type": "ImageObject", "url": img, "width": 1200, "height": 675, "caption": art["alt"]},
        "articleSection": art["cat"], "keywords": art["keywords"],
        "inLanguage": "en-IN", "isAccessibleForFree": True,
        "author": {"@type": "Organization", "name": "ScaleSafe Regulatory Desk", "url": ORIGIN + SECTION},
        "publisher": {"@id": ORIGIN + "/#organization", "@type": "Organization", "name": "ScaleSafe",
                      "logo": {"@type": "ImageObject", "url": ORIGIN + "/android-chrome-512x512.png"}},
        "mainEntityOfPage": url, "url": url,
        "citation": [{"@type": "CreativeWork", "url": u} for u in cites]}
    if minutes:
        article_ld["timeRequired"] = f"PT{minutes.group(0)}M"
    ld = json_ld({"@context": "https://schema.org", "@graph": [
        article_ld,
        breadcrumb_ld([("Home", ORIGIN + "/"), ("Insights", ORIGIN + SECTION), (art["title"], url)]),
    ]})
    meta_bits = []
    if art["status"]:
        meta_bits.append(f'<span class="status-pill">{esc(art["status"])}</span>')
    meta_bits.append(f"<span>Published {time_tag(art['dateISO'], art['date'])}</span>")
    if art["updated"]:
        meta_bits.append(f"<span>Updated {time_tag(modified, art['updated'])}</span>")
    if art["meta"]:
        meta_bits.append(f"<span>{esc(art['meta'])}</span>")
    meta_bits.append(f"<span>{esc(art['read'])}</span>")
    seg = art["types"][0] if len(art["types"]) == 1 else ""
    more = (f'<a class="text-link" href="{SECTION}?type={seg.lower()}">More {seg} briefings</a>' if seg
            else f'<a class="text-link" href="{SECTION}">More briefings</a>')
    rel = "".join(f'<li><a href="{SECTION}{o["slug"]}/">{esc(o["title"])}</a>'
                  f'<small>{esc(o["cat"])} · {time_tag(o["dateISO"], o["date"])}</small></li>'
                  for o in related(art, arts))
    main = f"""<article>
<div class="page-intro">
  <div class="wrap">
    <nav class="breadcrumb" aria-label="Breadcrumb"><ol><li><a href="/">Home</a></li><li><a href="{SECTION}">Insights</a></li><li><span aria-current="page">Briefing</span></li></ol></nav>
    <div class="eyebrow">{esc(art['cat'])}</div>
    <h1>{esc(art['title'])}</h1>
    <p>{esc(art['intro'])}</p>
    <div class="article-meta">{''.join(meta_bits)}</div>
  </div>
</div>
<section class="section white">
  <div class="wrap article-body">
    <picture class="insight-hero">{picture(slug, art['alt'], '(max-width: 840px) 92vw, 800px', True, have_webp)}</picture>
    <div class="article-content">
{body}
    </div>
    <div class="source-box"><b>Primary source</b><p><a href="{esc(art['sourceUrl'])}" target="_blank" rel="noopener noreferrer">{esc(art['source'])}</a></p><p class="source-note">ScaleSafe's analysis is educational compliance content. The underlying SEBI circular, regulation, order or government notification remains the authoritative source and should be checked for the latest applicable position.</p></div>
    <div class="article-cta">
      <a class="btn primary" href="/#contact">Talk to us about implementing this</a>
      {more}
    </div>
    <nav class="insight-related" aria-labelledby="rel-{slug}"><h2 id="rel-{slug}">Related briefings</h2><ul>{rel}</ul></nav>
    {newsletter(endpoint, 'a')}
    <p class="insight-back"><a class="btn secondary" href="{SECTION}">&larr; All briefings</a></p>
  </div>
</section>
</article>"""
    return page(c, assets, title=title, description=desc, canonical=url, og_type="article",
                image=(img, 1200, 675), image_alt=art["alt"],
                extra_meta=(f'<meta property="article:published_time" content="{art["dateISO"]}">\n'
                            f'<meta property="article:modified_time" content="{modified}">\n'
                            f'<meta property="article:section" content="{esc(art["cat"])}">\n'),
                ld=ld, main=main)


def listing_page(arts, extras, c, assets, endpoint, have_webp):
    url = ORIGIN + SECTION
    items = [dict(a, href=f"{SECTION}{a['slug']}/", own=True) for a in arts]
    items += [dict(e, own=False, slug="") for e in extras]
    items.sort(key=lambda x: x["dateISO"], reverse=True)
    counts = {t: sum(1 for i in items if t in i["types"]) for t in REG_TYPES}
    filters = [f'<button type="button" class="blog-filter" data-filter="all" aria-pressed="true">All<span class="n">{len(items)}</span></button>']
    filters += [f'<button type="button" class="blog-filter" data-filter="{t.lower()}" aria-pressed="false">{t}<span class="n">{counts[t]}</span></button>'
                for t in REG_TYPES]
    cards_html = []
    for n, it in enumerate(items):
        thumb = (f'<picture class="blog-card-thumb-pic">{picture(it["slug"], "", "(max-width: 640px) 92vw, 380px", n < 3, have_webp)}</picture>'
                 if it["own"] else "")
        meta = f'<span class="badge">{esc(it["cat"])}</span><span>{time_tag(it["dateISO"], it["date"])}</span>'
        if it.get("status"):
            meta += f'<span class="status-pill">{esc(it["status"])}</span>'
        cards_html.append(
            f'<article class="blog-card{" has-thumb" if it["own"] else ""}" data-insight-types="{" ".join(t.lower() for t in it["types"])}">'
            f'{thumb}<div class="article-meta">{meta}</div>'
            f'<h3><a href="{esc(it["href"])}">{esc(it["title"])}</a></h3>'
            f'<p>{esc(clip(it["summary"], 240))}</p>'
            f'<div class="article-bottom"><span>{esc(it.get("read", ""))}</span><span class="more" aria-hidden="true">Read &rarr;</span></div></article>')
    newest = max(max(a["dateISO"], a["updatedISO"]) for a in arts)
    ld = json_ld({"@context": "https://schema.org", "@graph": [
        {"@type": "CollectionPage", "@id": url, "url": url, "name": "ScaleSafe Insights",
         "description": "Primary-source SEBI compliance briefings for Investment Advisers, Research Analysts, Portfolio Managers and AIFs.",
         "dateModified": newest, "inLanguage": "en-IN",
         "publisher": {"@id": ORIGIN + "/#organization", "@type": "Organization", "name": "ScaleSafe"},
         "mainEntity": {"@type": "ItemList", "numberOfItems": len(arts), "itemListElement": [
             {"@type": "ListItem", "position": i + 1, "url": f"{ORIGIN}{SECTION}{a['slug']}/", "name": a["title"]}
             for i, a in enumerate(arts)]}},
        breadcrumb_ld([("Home", ORIGIN + "/"), ("Insights", url)]),
    ]})
    main = f"""<div class="page-intro">
  <div class="wrap">
    <nav class="breadcrumb" aria-label="Breadcrumb"><ol><li><a href="/">Home</a></li><li><span aria-current="page">Insights</span></li></ol></nav>
    <div class="eyebrow">ScaleSafe Regulatory Intelligence</div>
    <h1>SEBI compliance briefings, explained for the people who implement them.</h1>
    <p>Primary-source analysis for Investment Advisers, Research Analysts, Portfolio Managers and AIFs: what changed, who is affected, what to review and what evidence to keep.</p>
  </div>
</div>
<section class="section white">
  <div class="wrap">
    <div class="insights-toolbar">
      <div class="blog-tabs" role="group" aria-label="Filter by registration type" data-insights-filters>{''.join(filters)}</div>
      <p class="insights-count" id="insightsCount" role="status" aria-live="polite">{len(items)} briefings</p>
    </div>
    <div class="insights-list-head"><h2>Latest briefings</h2></div>
    <div class="blog-grid insights-grid">
{chr(10).join(cards_html)}
    </div>
    <p class="insights-empty" id="insightsEmpty" hidden>No briefings for this registration type yet.</p>
    {newsletter(endpoint, 'l')}
  </div>
</section>"""
    return page(c, assets, title="SEBI compliance insights for IA, RA, PMS and AIF | ScaleSafe",
                description=clip("Primary-source SEBI compliance briefings for Investment Advisers, Research Analysts, "
                                 "Portfolio Managers and AIFs: what changed, who is affected and what to do."),
                canonical=url, og_type="website", image=(ORIGIN + "/og-image.png", 1200, 630),
                image_alt="ScaleSafe Insights: SEBI compliance briefings", extra_meta="", ld=ld, main=main)


# --------------------------------------------------------------------------- other files

def patch_home(home, slugs):
    notes = []

    def card_link(m):
        slug = m.group(2)
        if slug not in slugs:
            return m.group(0)
        return f'<a class="text-btn" href="{SECTION}{slug}/" data-article="{slug}"{m.group(3)}>{m.group(4)}</a>'
    home2, n = re.subn(r'<button class="text-btn"(\s)data-article="([^"]+)"([^>]*)>(.*?)</button>',
                       lambda m: card_link(m), home, flags=re.S)
    linked = len(re.findall(r'<a class="text-btn" href="/insights/[^"]+/" data-article=', home2))
    notes.append(f"home: {n} article read button(s) given /insights/ links ({linked} linked in total)")
    home2, v = re.subn(r'<button class="text-link" data-go="resources">(View all[^<]*briefings[^<]*)</button>',
                       rf'<a class="text-link" href="{SECTION}">\1</a>', home2)
    notes.append(f"home: 'View all ... briefings' -> {SECTION} ({v} changed)")
    if HOME_LINK_MARKER not in home2:
        anchor = '<div class="blog-grid" id="blogGrid">'
        if anchor in home2:
            home2 = home2.replace(anchor, f'{HOME_LINK_MARKER}<p style="margin:0 0 18px"><a class="text-link" href="{SECTION}">'
                                          f'Browse every briefing as its own page &rarr;</a></p>\n      {anchor}', 1)
            notes.append("home: 'Browse every briefing' link added to Regulatory Intelligence")
        else:
            notes.append("home: #blogGrid not found; resources link not added")
    if f'href="{SECTION}"' not in home2:
        raise InsightsError("home page: could not add any link to /insights/")
    return home2, notes


def update_sitemap(text, arts):
    if "</urlset>" not in text:
        raise InsightsError("sitemap.xml has no </urlset>")
    text = re.sub(r"[ \t]*<url><loc>" + re.escape(ORIGIN + SECTION) + r"[^<]*</loc>.*?</url>\r?\n?", "", text, flags=re.S)
    newest = max(max(a["dateISO"], a["updatedISO"]) for a in arts)
    rows = [f"  <url><loc>{ORIGIN}{SECTION}</loc><lastmod>{newest}</lastmod></url>"]
    rows += [f"  <url><loc>{ORIGIN}{SECTION}{a['slug']}/</loc><lastmod>{max(a['dateISO'], a['updatedISO'])}</lastmod></url>"
             for a in arts]
    return text.replace("</urlset>", "\n".join(rows) + "\n</urlset>", 1)


def update_llms(text):
    line = f"- [Insights]({ORIGIN}{SECTION}): SEBI compliance briefings for IA, RA, PMS and AIF, one page per article"
    if f"({ORIGIN}{SECTION})" in text:
        return text
    home_line = re.search(r"^- \[Home\]\([^)]*\).*$", text, re.M)
    if home_line:
        return text[: home_line.end()] + "\n" + line + text[home_line.end():]
    return text.rstrip("\n") + "\n" + line + "\n"


# --------------------------------------------------------------------------- driver

def read(p):
    with open(p, encoding="utf-8") as f:
        return f.read()


def build(root, endpoint=DEFAULT_ENDPOINT):
    """Everything in memory: returns ({relpath: text}, notes). Raises InsightsError on any problem."""
    home_path = os.path.join(root, "index.html")
    if not os.path.exists(home_path):
        raise InsightsError(f"{home_path} not found")
    home = read(home_path)
    arts, extras = extract(home)
    missing_img = [a["slug"] for a in arts if not os.path.exists(os.path.join(root, "img", "articles", a["slug"] + ".jpg"))]
    if missing_img:
        raise InsightsError("article images missing: " + ", ".join(missing_img))
    have_webp = all(os.path.exists(os.path.join(root, "img", "articles", "webp", f"{a['slug']}-{w}.webp"))
                    for a in arts for w in (480, 800, 1200))
    c = chrome(home)
    css = "/* Generated by tools/insights.py from the home page's own styles. Do not edit. */\n" + c["css"] + EXTRA_CSS
    h_css = hashlib.sha256(css.encode()).hexdigest()[:10]
    h_js = hashlib.sha256(SCRIPT.encode()).hexdigest()[:10]
    assets = {"css": f"/assets/insights/insights-{h_css}.css", "js": f"/assets/insights/insights-{h_js}.js"}
    out = {assets["css"].lstrip("/"): css, assets["js"].lstrip("/"): SCRIPT}
    out["insights/index.html"] = listing_page(arts, extras, c, assets, endpoint, have_webp)
    for a in arts:
        out[f"insights/{a['slug']}/index.html"] = article_page(a, arts, c, assets, endpoint, have_webp)
    for rel, text in out.items():
        if rel.endswith(".html"):
            if len(re.findall(r"<h1[\s>]", text)) != 1:
                raise InsightsError(f"{rel}: expected exactly one <h1>")
            # Only JSON-LD and first-party script files (ours: /assets/insights/, /assets/site/ for the phone menu).
            if re.search(r"<script(?![^>]*(?:application/ld\+json|src=\"/assets/(?:insights|site)/))", text):
                raise InsightsError(f"{rel}: unexpected inline script")
    home2, notes = patch_home(home, {a["slug"] for a in arts})
    out["index.html"] = home2
    sm = os.path.join(root, "sitemap.xml")
    if not os.path.exists(sm):
        raise InsightsError("sitemap.xml not found")
    out["sitemap.xml"] = update_sitemap(read(sm), arts)
    llms = os.path.join(root, "llms.txt")
    if os.path.exists(llms):
        out["llms.txt"] = update_llms(read(llms))
    notes.insert(0, f"insights: {len(arts)} article page(s) + listing ({len(extras)} link-out card(s))"
                    f"{'' if have_webp else '; webp variants missing, jpg only'}")
    notes.append(f"sitemap.xml: {len(arts) + 1} /insights/ URL(s)")
    return out, notes


def generate(root, endpoint=DEFAULT_ENDPOINT):
    out, notes = build(root, endpoint)
    # Only now touch the disk: drop the previous generation, then write the new one.
    for d in ("insights", os.path.join("assets", "insights")):
        shutil.rmtree(os.path.join(root, d), ignore_errors=True)
    for rel, text in out.items():
        p = os.path.join(root, rel.replace("/", os.sep))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8", newline="") as f:
            f.write(text)
    return notes


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=SITE, help="site directory to regenerate in (default: site-deploy/)")
    ap.add_argument("--endpoint", default=DEFAULT_ENDPOINT, help="newsletter subscription endpoint")
    args = ap.parse_args()
    try:
        notes = generate(os.path.abspath(args.root), args.endpoint)
    except InsightsError as e:
        print(f"insights: FAILED, nothing written: {e}", file=sys.stderr)
        sys.exit(2)
    for n in notes:
        print(f"  - {n}")


if __name__ == "__main__":
    main()

"""Website forms on Azure: no Cloudflare Turnstile, no formsubmit.co.

Owner's decision (2026-11-19): the site and everything behind it run on Microsoft Azure (South India). The live
snapshot's walkthrough form posted to formsubmit.co (forwarded to Gmail) behind a Cloudflare Turnstile check that
was only enforced in the browser, and its privacy-request form sent nothing ("Demo request created"). This step:

- home page: removes Turnstile and the formsubmit.co plumbing; the walkthrough form posts JSON to the ScaleSafe
  platform (partner-service `POST /partners/api/v1/public/leads`) and the privacy-request form to
  `POST /partners/api/v1/public/privacy-requests`, through /assets/site/forms-v1.js (tools/patches/forms.js);
  a hidden `website` field is the honeypot, the API rate-limits per IP;
- every page: newsletter endpoint `/clients/api/...` -> `/partners/api/...` (partner-model rename);
- privacy and cookie notices: Cloudflare (hosting, Turnstile, analytics, form processing) -> Microsoft Azure India;
  Turnstile and Cloudflare cookies removed; privacy requests can be made through the form.

Endpoints are written with the production API host (https://api.scalesafe.co.in); nginx rewrites it per host
(nginx/default.conf, map $api_origin), so scalesafe.capital uses https://api.scalesafe.capital.

Run by tools/sync_from_live.py after compliance.py. Idempotent. Standalone: python tools/forms.py site-deploy
Notice text changes are factual corrections pending legal review (AUDIT-ACTIONS.md).
"""
import os
import re
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
API = "https://api.scalesafe.co.in/partners/api/v1/public"
JS_ASSET = "assets/site/forms-v1.js"
JS_TAG = '<script src="/assets/site/forms-v1.js" defer></script>'
UPDATED = "19 November 2026"
HONEYPOT = ('<div class="ss-hp" aria-hidden="true" style="position:absolute;left:-10000px;width:1px;height:1px;overflow:hidden">'
            '<label>Leave this field empty<input type="text" name="website" tabindex="-1" autocomplete="off"></label></div>')


class FormsError(Exception):
    pass


def _read(p):
    with open(p, encoding="utf-8", newline="") as f:
        return f.read()


def _write(p, t):
    with open(p, "w", encoding="utf-8", newline="") as f:
        f.write(t)


def _sub(text, pattern, repl, what, notes, done_marker=None, flags=re.S):
    """Replace exactly one match; fine if done_marker shows it was already applied; else FormsError."""
    new, n = re.subn(pattern, repl, text, count=1, flags=flags)
    if n:
        notes.append(what)
        return new
    if done_marker is not None and done_marker in text:
        return text
    raise FormsError(f"{what}: pattern not found (the live page changed; update tools/forms.py)")


def home(root, notes):
    p = os.path.join(root, "index.html")
    t = _read(p)
    t = _sub(t, r'[ \t]*<script src="https://challenges\.cloudflare\.com/turnstile/v0/api\.js"[^>]*></script>\r?\n',
             "", "home: Turnstile script removed", notes, done_marker=JS_TAG)
    t = _sub(t, r'<form class="form" id="contactForm" action="https://formsubmit\.co/[^"]*" method="POST">',
             f'<form class="form" id="contactForm" data-endpoint="{API}/leads">',
             "home: walkthrough form posts to the ScaleSafe API", notes, done_marker=f'data-endpoint="{API}/leads"')
    t = _sub(t, r'(<form class="form" id="contactForm"[^>]*>)\s*(?:<input type="hidden" name="(?:_subject|_template|_captcha|source|_replyto)"[^>]*>\s*)+'
                r'<input type="text" name="_honey"[^>]*>',
             lambda m: m.group(1) + "\n        " + HONEYPOT,
             "home: formsubmit.co fields replaced by a honeypot", notes, done_marker='name="website"')
    t = _sub(t, r'\s*<div class="field">\s*<div class="cf-turnstile"[^>]*></div>\s*</div>',
             "", "home: Turnstile widget removed", notes, done_marker=JS_TAG)
    t = _sub(t, r'Your enquiry will be emailed to (<a href="mailto:hello@scalesafe\.co\.in">hello@scalesafe\.co\.in</a>)\.',
             r'Your enquiry is sent securely to ScaleSafe and stored encrypted on Microsoft Azure in India. You can also write to \1.',
             "home: form note says where the enquiry goes", notes, done_marker="stored encrypted on Microsoft Azure in India")
    t = _sub(t, r'<form class="form" id="rightsForm">',
             f'<form class="form" id="rightsForm" data-endpoint="{API}/privacy-requests">\n{HONEYPOT}',
             "home: privacy-request form posts to the ScaleSafe API", notes, done_marker=f'{API}/privacy-requests')
    t = _sub(t, r'<script id="scalesafe-contact-enhancement">.*?</script>\s*',
             "", "home: formsubmit reply-to script removed", notes, done_marker=JS_TAG)
    t = _sub(t, r"document\.getElementById\('contactForm'\)\?\.addEventListener\('submit',\(e\)=>\{\s*if \(!window\.turnstile.*?\}\s*\}\);\s*",
             "", "home: Turnstile submit guard removed", notes, done_marker=JS_TAG)
    t = _sub(t, r"document\.getElementById\('rightsForm'\)\?\.addEventListener\('submit',e=>\{.*?Demo request created.*?\}\);\s*",
             "", "home: demo privacy-request handler removed", notes, done_marker=JS_TAG)
    if JS_TAG not in t:
        t = _sub(t, r"</body>", JS_TAG + "\n</body>", "home: forms script added", notes)
    if re.search(r"turnstile|formsubmit", t, re.I):
        raise FormsError("home: Turnstile or formsubmit.co is still referenced after patching")
    _write(p, t)
    os.makedirs(os.path.join(root, "assets", "site"), exist_ok=True)
    shutil.copy2(os.path.join(HERE, "patches", "forms.js"), os.path.join(root, *JS_ASSET.split("/")))


def newsletter(root, notes):
    n = 0
    for d, _, fs in os.walk(root):
        for f in fs:
            if f.endswith(".html"):
                p = os.path.join(d, f)
                t = _read(p)
                t2 = t.replace("/clients/api/v1/public/", "/partners/api/v1/public/")
                if t2 != t:
                    _write(p, t2)
                    n += 1
    notes.append(f"newsletter endpoint -> /partners on {n} page(s)")


AZURE_ROW = ("<tr>\n<td>Microsoft Corporation (India) Private Limited (Microsoft Azure)</td>\n"
             "<td>Hosting of the Website and the ScaleSafe platform, including processing and encrypted storage of form "
             "submissions, consent and request records</td>\n<td>India (Azure South India region)</td>\n</tr>")


def notices(root, notes):
    p = os.path.join(root, "privacy-notice", "index.html")
    t = _read(p)
    t = _sub(t, r"<tr>\s*<td>Cloudflare, Inc\.</td>.*?</tr>", AZURE_ROW,
             "privacy notice: Cloudflare replaced by Microsoft Azure (India)", notes, done_marker="Azure South India region")
    # Form notifications never went through Zoho (formsubmit.co -> Gmail, now the platform); owner removed the row.
    t = _sub(t, r"<tr>\s*<td>Zoho Corporation Private Limited[^<]*</td>.*?</tr>\s*", "",
             "privacy notice: Zoho row removed", notes, done_marker="Azure South India region")
    t = _sub(t, r"<td>You, by email to our Grievance Officer</td>",
             "<td>You, through the privacy request form on the Website or by email to our Grievance Officer</td>",
             "privacy notice: privacy requests through the form", notes, done_marker="through the privacy request form")
    t = re.sub(r"(<strong>Last updated:</strong> )\d{1,2} \w+ \d{4}", r"\g<1>" + UPDATED, t, count=1)
    _write(p, t)

    p = os.path.join(root, "cookie-notice", "index.html")
    t = _read(p)
    for name in ("__cf_bm", "cf_clearance"):
        t = _sub(t, r'<tr>\s*<td><code class="mono">' + name + r"</code></td>.*?</tr>\s*", "",
                 f"cookie notice: {name} removed", notes, done_marker="We do not use analytics on this Website")
    t = _sub(t, r"<tr>\s*<td>Cloudflare Turnstile</td>.*?</tr>\s*", "",
             "cookie notice: Turnstile removed", notes, done_marker="We do not use analytics on this Website")
    t = _sub(t, r"Our analytics \(Cloudflare Web Analytics\) are <strong>cookieless</strong>:[^<]*",
             "We do not use analytics on this Website, and our forms use no third-party security checks.",
             "cookie notice: no analytics, no third-party checks", notes, done_marker="We do not use analytics on this Website")
    t = re.sub(r"(<strong>Last updated:</strong> )\d{1,2} \w+ \d{4}", r"\g<1>" + UPDATED, t, count=1)
    if re.search(r"cloudflare", t, re.I):
        raise FormsError("cookie notice: Cloudflare is still mentioned after patching")
    _write(p, t)


def apply(root):
    notes = []
    home(root, notes)
    newsletter(root, notes)
    notices(root, notes)
    return notes


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(HERE), "site-deploy")
    try:
        for n in apply(target):
            print(" -", n)
    except FormsError as e:
        sys.exit(f"forms: {e}")

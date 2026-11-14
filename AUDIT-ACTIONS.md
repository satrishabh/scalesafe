# scalesafe.co.in: audit findings and what can be done

Written for: the ScaleSafe site owners and whoever works on the site next.
Audit date: 2026-11-14. Snapshot of the site in `website-download/`.

## 1. Fix now (high impact, small effort)

1. ~~**Phone layout overflows at 390px.**~~ **Withdrawn: not a real issue.** Headless Chrome cannot render narrower than about 500px, so the earlier screenshots were cropped and misleading. Measured in a true 390px iframe, the original page has scrollWidth 375 (no horizontal overflow). Lesson: check phone layout with a real device or a 390px iframe, not a cropped screenshot.

2. **Home page has 11 `<h1>` tags.**
   - *Do:* Keep one `<h1>` (the hero heading). Change the other section titles to `<h2>`, and card titles to `<h3>`.

3. **Contact form goes to a Gmail address.** The `formsubmit.co` action points at `compliance.scalesafe@gmail.com`, which is visible in the page source.
   - *Do:* Confirm this is intended. If not, point it at a company-domain mailbox (e.g. `hello@scalesafe.co.in`) and verify the formsubmit activation for that address.

## 2. Fix next (SEO and hygiene)

4. **`/accredited-investor-desk/` has no canonical tag.** Add `<link rel="canonical" href="https://scalesafe.co.in/accredited-investor-desk/">`.
5. **404 page sets `canonical=/404.html`.** Remove the canonical tag from the 404 template. `/404.html` is not a real page.
6. **`/llms.txt` returns 404.** Optional. Add one that lists the key pages and the site's content policy. robots.txt already allows AI answer crawlers.
7. **Article pages are client-side.** Article views use `#article/<slug>` in the URL, so search engines see only the home page for those articles. There are 47 articles.
   - *Do:* Give each article its own URL (e.g. `/articles/<slug>/`), with its own title, meta description, canonical and sitemap entry. Or pre-render them.
   - *Check:* Add the article URLs to `sitemap.xml`. Right now the sitemap lists only 5 URLs.

## 3. Security and privacy

8. **CSP is report-only.** Turn it into an enforced policy once the reports are clean. Check the reports first; the current policy allows `'unsafe-inline'` for scripts and styles.
9. **Privacy notice and cookie notice.** The site uses Cloudflare Turnstile and the Cloudflare Insights beacon. Make sure the cookie notice names them.
10. **Rights-request form** (`/privacy-notice/#rights-request`) has no visible submit endpoint in the home page. Verify where it posts and that the data goes somewhere the company controls.

## 4. External sources (not verified)

11. **89 SEBI links cited on the home page are unverified.** Locally they fail with a certificate error (the local trust store lacks SEBI's chain). Re-run the check from a machine that trusts SEBI's certificate. Expect some circulars and orders to have moved; update any that return 404 or redirect.

## 5. Nice to have

12. **Performance.** The home page HTML is about 520KB, mostly inline data and CSS/JS. Measure with Lighthouse, then consider moving the article data into a separate JSON file loaded on demand.
13. **Accessibility.** Run an automated scanner (axe or Lighthouse) and a keyboard-only pass on the nav, the filter links and the forms. Check colour contrast of the small mono labels (e.g. "COMPLIANCE OPERATING LAYER", "ACTIVE").
14. **Navigation.** The Platform / Registrations / Services / Resources menus were not clicked through in this audit. Check their dropdowns and link targets.

## What already works (keep it)

- All 68 reachable home-page links and 47 images returned 200.
- All five sitemap pages return 200 with a title, meta description and H1.
- HSTS, `X-Frame-Options: DENY`, `nosniff`, referrer and permissions policies are set.
- robots.txt blocks AI-training crawlers and allows search and answer engines.
- The contact form is protected by Turnstile, has a honeypot and explicit consent checkboxes.

## What was not covered

- Forms were not submitted.
- The article pages' JS-driven behaviour was not tested in a browser.
- No Lighthouse, accessibility scanner or load testing was run.
- `/skill-doctor` was not run; no such skill exists in this session.

## Snapshot

- Folder: `website-download/`
- Files: 211 (about 10 MB), including pages, fonts, favicons, the 47 article images in JPG and three WebP widths each, and `_mirror_log.txt`.
- Pages captured: home, accredited-investor-desk, privacy-notice, terms, cookie-notice, sitemap, robots.txt, manifest.
- Limitation: the crawler only follows links present in HTML and JS strings. Client-side article views aren't separate files, and the `/?reg=` filter variants share the home-page HTML.

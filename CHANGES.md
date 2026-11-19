# Changes in site-improved (from the 2026-11-14 snapshot)

Working copy only. The live site is unchanged.

## Applied
- **Forms on Azure (2026-11-19, `tools/forms.py`, owner's decision: everything runs on Microsoft Azure):**
  - Walkthrough form posted to formsubmit.co (forwarded to Gmail) behind a Cloudflare Turnstile check enforced only in the browser. It now posts to the ScaleSafe platform (`POST /partners/api/v1/public/leads`): validated, consent-checked, rate-limited per IP, stored encrypted per person, visible to ops in the admin console. Bots: hidden honeypot field.
  - Privacy-request form only showed "Demo request created" and sent nothing. It now posts to `POST /partners/api/v1/public/privacy-requests` (platform branch feat/privacy-requests); until that is deployed, it tells the visitor to email privacy@scalesafe.co.in.
  - Turnstile script and widget, formsubmit.co fields and their inline scripts removed; `/assets/site/forms-v1.js` added; CSP no longer allows challenges.cloudflare.com, cloudflareinsights.com or formsubmit.co.
  - Newsletter endpoint `/clients/...` -> `/partners/...` (platform partner-model rename).
  - Privacy Notice: Cloudflare recipient row replaced by Microsoft Azure (India, South India region); Zoho row removed (form notifications never went through Zoho); privacy requests can be made through the form. Cookie Notice: `__cf_bm`, `cf_clearance` and Turnstile rows removed; "we do not use analytics". Accessibility statement: no Turnstile. Both notices dated 19 November 2026. **Pending legal review.**
- **Heading structure (home page):** 9 section and legal headings changed from `<h1>` to `<h2 class="h1-as-h2">`. The hero `<h1>` is kept, so the home page has one H1. Styles copied from the original H1 rules so the look is unchanged; a desktop screenshot is pixel-identical to the original.
- **Canonical tag:** added to `accredited-investor-desk/index.html`.
- **llms.txt:** added at the site root, listing key pages and the content policy from robots.txt.

- **Design corrections (home page), checked in a true 390px frame and at 1440px:**
  - Footer legal links were `display:block`, stacking one per line with stranded `·` separators. Now inline.
  - Footer ™ dropped to its own line under the logo. Now beside the wordmark.
  - Header ™ sat about 13px from the wordmark. Now 3px.
  - Top bar wrapped to two lines on phones. Now one line, ellipsis if the screen is narrower.
  - Hero "Book a 30-minute walkthrough" wrapped inside the pill on phones. Now one line, with "See how it works" below.
  - Blog card meta split the date and status pill across lines. Now items wrap whole.

- **Design pass after client feedback (2026-11-17): same type and structure on every page and device.** CSS only, in `tools/patches/design-system.css` (home, so also /insights, and the investor desk) and `tools/patches/legal-brand.css` (privacy, regional supplement, cookies, accessibility, terms, 404). `sync_from_live.py` re-applies both on every sync. Checked at 360, 390, 820, 1366 and 1920px; axe WCAG 2.1 AA clean on all ten pages.
  - **Words ran together.** Plus Jakarta Sans and Fraunces have a narrow space (0.17em; Arial's is 0.28em), and the site added up to −0.065em tracking on top: "Makecompliance", "+917061710422". Word spacing restored and headline tracking eased.
  - **Legal pages looked like another website.** They asked for Inter, which is never loaded, so each device showed its own system font (Segoe UI, San Francisco, Roboto) on white. They now use the brand fonts, cream background, serif headings and the home page's pill button.
  - **Text too small.** Status pills were 9px, labels and footer headings 10px. Nothing that carries meaning is under 10.5px now; body labels 12px and up.
  - **Navigation** in the text face at 14px instead of 11px uppercase mono.
  - **Phones:** steps as compact rows, brand card shorter, contact buttons full width, footer in two columns with 40px+ link rows, photo on the lead briefing only on the home page (all photos stay on /insights). Legal header: logo and button on one row.
  - **Tablets:** two-column sections stack below 900px (registration cards were squeezed to about 170px).
  - Brand fonts preloaded on the home and legal pages.

- **Typefaces, Solutions, phone menu and WCAG 2.2 (2026-11-18).**
  - **Fonts:** Source Serif 4 (headlines) + Inter (text), chosen from a four-way specimen; both SIL OFL and self-hosted in `assets/fonts/`. They replace Fraunces + Plus Jakarta Sans everywhere (home, /insights, /solutions, legal pages, investor desk). IBM Plex Mono stays for labels. Preloads updated.
  - **Solutions** (`/solutions/`, built by `tools/solutions.py` after /insights): by registration (IA, RA, PMS, AIF, other) and by job (get registered, monthly compliance, inspection readiness, regulatory change, policies and cyber), each pairing platform capabilities with services. All copy restates the home page's Platform, Registrations and Services sections; the SEBI outsourcing disclaimer is kept. Added to the header, sitemap and llms.txt.
  - **Phone menu:** the live header hid its section buttons at <=800px with no menu, so phones could not reach Platform/Registrations/Services/Resources. A `<details>` menu (keyboard, Escape to close; script `assets/site/menu-v1.js`).
  - **WCAG 2.2 AA:** skip link + main landmark on home and the desk (2.4.1), visible focus ring on every focusable element (2.4.7), scroll padding under the sticky header (2.4.11), no horizontal scroll at 320px on any page (1.4.10). axe (WCAG 2.0/2.1/2.2 A+AA) plus scripted keyboard/reflow checks: 27/27 page-width combinations clean.
  - **Accessibility statement:** WCAG 2.2 wording, the audit-date placeholder replaced, fixed limitations removed, test method described; owner set the commitment to acknowledge in 2 and resolve in 15 working days.

## Not applied (need a decision or the source)
- **Contact form destination:** the form posts to `formsubmit.co` with a Gmail address. Change to a company mailbox only once you confirm which address to use.
- **404 page canonical:** the 404 template is not in the snapshot. Remove its canonical to `/404.html` in the source.
- **Article URLs:** articles are client-side (`#article/<slug>`). Giving each its own URL, and listing them in the sitemap, needs the source site.
- **CSP:** still report-only. Enforce once reports are clean.
- **SEBI links:** 89 links remain unverified (certificate issue in this environment).

## Checked and not changed
- **Phone layout:** no horizontal overflow at 390px in a true 390px frame. An earlier finding was a screenshot artifact and is withdrawn.

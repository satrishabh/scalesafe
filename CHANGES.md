# Changes in site-improved (from the 2026-11-14 snapshot)

Working copy only. The live site is unchanged.

## Applied
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

## Not applied (need a decision or the source)
- **Contact form destination:** the form posts to `formsubmit.co` with a Gmail address. Change to a company mailbox only once you confirm which address to use.
- **404 page canonical:** the 404 template is not in the snapshot. Remove its canonical to `/404.html` in the source.
- **Article URLs:** articles are client-side (`#article/<slug>`). Giving each its own URL, and listing them in the sitemap, needs the source site.
- **CSP:** still report-only. Enforce once reports are clean.
- **SEBI links:** 89 links remain unverified (certificate issue in this environment).

## Checked and not changed
- **Phone layout:** no horizontal overflow at 390px in a true 390px frame. An earlier finding was a screenshot artifact and is withdrawn.

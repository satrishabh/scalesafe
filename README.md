# scalesafe.co.in

Static marketing site for ScaleSafe.

| Path | What it is |
|---|---|
| `site-deploy/` | The site: static files, `404.html`, and `_headers` (Cloudflare Pages only). |
| `Dockerfile`, `nginx/` | Container for AIO: unprivileged nginx on 8080, `/health`, live-site headers and cache rules. |
| `deploy/` | AIO onboarding request, dev values, Argo CD app and a build-only pipeline run. See `deploy/README.md`. |
| `tools/` | `sync_from_live.py` (bring live-site changes in, re-apply fixes), `insights.py` (generate `/insights` from the home-page articles), `release.sh` (build on AIO, roll out the preview), `verify.sh` (check a deployment). |
| `CHANGES.md` | Changes made on top of the 2026-11-14 live snapshot. |
| `AUDIT-ACTIONS.md` | Audit findings and remaining actions. |
| `DEPLOY.md` | Deploy checklist and the subdomain plan (blog/newsletter, onboarding, profile). |

Note: `site-deploy/` was rebuilt from the live site, not from the original source project. See `DEPLOY.md` before replacing an existing deployment.

## Workflow: live site → preview

scalesafe.co.in stays the live site. The AIO preview (https://scalesafe-site-dev.52.140.55.184.nip.io) is the test copy, and it is kept out of search engines (`X-Robots-Tag: noindex` and a disallow-all robots.txt on any host other than scalesafe.co.in).

1. Change the live site as usual.
2. `python tools/sync_from_live.py` re-crawls it and re-applies our fixes into `site-deploy/`. It stops without changing anything if a fix no longer fits the live page.
3. Review with `git diff site-deploy`, then commit and push.
4. `tools/release.sh` builds on AIO, scans, pins the image in GitOps, syncs Argo CD and runs `tools/verify.sh`.

To try a change on the preview before it goes live, edit `site-deploy/` directly and run steps 3–4. The next sync from live replaces those edits unless the same change has been made on the live site, or added as a fix in `tools/sync_from_live.py`.

## /insights (one page per briefing)

The briefings live only inside the home page (`const ARTICLES={...}` and `ARTICLE_HEADER_ALTS` in its script, cards in `#blogGrid`). `tools/insights.py` turns them into crawlable pages:

- `site-deploy/insights/index.html`: listing, newest first, filter by IA / RA / PMS / AIF (from the card categories), newsletter sign-up.
- `site-deploy/insights/<slug>/index.html`: one page per article with canonical, Open Graph/Twitter tags, JSON-LD `Article` + `BreadcrumbList`, hero image (webp srcset), sanitised body (allowlisted tags only, no scripts or event handlers), primary source, related briefings and the newsletter form.
- `site-deploy/assets/insights/insights-<hash>.css|js`: the home page's own CSS plus the section's styles, and the filter/newsletter script (hashed names, so the 30-day `/assets/` cache is safe).
- It also adds `/insights/` and every article (lastmod = updated or published date) to `sitemap.xml`, adds an Insights line to `llms.txt`, and gives the home-page "Read" buttons and "View all … briefings" real `/insights/…` links (the in-page reader still opens on click).

`sync_from_live.py` runs it on every sync, after its own fixes, so `/insights` always matches the articles on the live home page. If no articles are found or one lacks a required field (title, category, intro, date, reading time, body, source, image alt, image file), it exits 2 and `site-deploy/` is left untouched. To regenerate without crawling: `python tools/insights.py`. Do not edit files under `site-deploy/insights/` by hand; change the article on the live site, or the generator.

The newsletter form POSTs `{email, topics?, consent: true}` as JSON to the `data-endpoint` on the form (default `https://api.scalesafe.co.in/clients/api/v1/public/subscriptions`, override with `--endpoint`); it expects `202 {"status":"pending-confirmation"}` and shows an inline message otherwise. CSP `connect-src`/`form-action` allow `https://api.scalesafe.co.in` (`nginx/security-headers.conf` and `site-deploy/_headers`).

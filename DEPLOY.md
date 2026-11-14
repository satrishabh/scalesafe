# Deploying the corrected site, and planning the subdomains

Written for: whoever deploys scalesafe.co.in and sets up the new subdomains.
Prepared 2026-11-14.

## What is ready

`site-deploy/` (213 files, about 10 MB) is the corrected site, ready to upload as a static site:

- Home page design corrections: footer legal links, header and footer ™ placement, top bar on phones, hero buttons on phones, blog card tags.
- Heading structure: one H1 on the home page; the other nine headings are H2 with an identical look.
- Canonical tag added to `/accredited-investor-desk/`.
- `404.html` included, with the incorrect `/404.html` canonical removed.
- `llms.txt` added.
- `_headers` reproduces the live security headers and cache rules (Cloudflare Pages format).

Snapshot-only files (rendered views, crawl log, notes) are excluded.

## Check before deploying

1. **Use the source if it exists.** `site-deploy/` is rebuilt from the live pages, not from the original project. If the original source or repo exists, apply the same changes there instead. The CSS block is at the end of `<head>` in `index.html`, marked "Design corrections" and "Section headings". Anything the crawl could not see (redirect rules, Pages Functions, `/api/` routes) exists only in the source.
2. **Confirm the host.** The site is served through Cloudflare, most likely Cloudflare Pages (the per-path cache headers point that way). Confirm the Pages project name.
3. **Headers in one place.** If the security headers are set as zone-level Transform Rules, delete `_headers` before deploying so they are not sent twice.
4. **Analytics beacon.** The HTML contains the Cloudflare Web Analytics script. If Web Analytics is set to automatic injection on the zone, remove the script from the HTML to avoid double counting.
5. **Contact form.** It still posts to `formsubmit.co` with a Gmail address. Change it now if it should go to a company mailbox.

## Deploy steps (Cloudflare Pages)

```sh
npx wrangler login
# 1. Preview first. This does not touch the live site.
npx wrangler pages deploy site-deploy --project-name <pages-project> --branch preview
# 2. Check the preview URL on a phone and a desktop. Submit the contact form once.
# 3. Promote to production.
npx wrangler pages deploy site-deploy --project-name <pages-project> --branch main
```

Rollback: Cloudflare dashboard → Pages → the project → Deployments → the previous deployment → Rollback.

After deploying, check:
- `curl -sI https://scalesafe.co.in/` shows the security headers once each.
- `https://scalesafe.co.in/llms.txt` returns 200.
- A random path returns the 404 page with status 404.

## Subdomains: blog/newsletter, onboarding, profile

### Must do

- **HTTPS from day one.** The live site sends `Strict-Transport-Security: max-age=31536000; includeSubDomains`. Browsers that have visited scalesafe.co.in will refuse plain HTTP on every subdomain. Create each subdomain as a proxied (orange-cloud) record so Cloudflare's certificate covers it before it is linked anywhere.
- **Keep app cookies off the marketing site.** Onboarding and profile will hold login sessions and personal data. Set cookies host-only (no `Domain=.scalesafe.co.in`) unless you deliberately want shared sign-in across subdomains.
- **Keep app pages out of search.** Give onboarding and profile `robots.txt` with `Disallow: /` and `X-Robots-Tag: noindex`.
- **Update the privacy and cookie notices.** They currently describe scalesafe.co.in only and say the site sets no cookies. Profile and onboarding will process personal data under DPDP, so the notices must cover them before launch.

### Recommendations

- **Combine onboarding and profile into one app subdomain.** For example, `app.scalesafe.co.in/onboarding` and `app.scalesafe.co.in/profile`. One login cookie, one CSP, one deployment and one certificate, instead of two apps that must share sessions.
- **Blog with real article URLs.** Today the 47 articles live inside the home page (`#article/<slug>`), so search engines cannot index them one by one. Moving them to the blog with one URL per article fixes that.
  - A subdomain (`blog.scalesafe.co.in`) is simpler to deploy separately.
  - A path (`scalesafe.co.in/blog/`) keeps search ranking with the main domain. If organic search matters, prefer the path.
- **Newsletter sign-up.** If the form posts to a provider (Mailchimp, Buttondown, Substack and so on), add that domain to `form-action`, and to `connect-src` if it uses JavaScript.
- **One Pages project per subdomain,** each with its own `_headers`, `robots.txt` and `sitemap.xml`. List the blog sitemap in the main `robots.txt`.
- **Shared look.** Reuse the main site's header, footer and fonts. The legal pages and the investor-desk page already use different templates, and the investor-desk page has no site header at all.

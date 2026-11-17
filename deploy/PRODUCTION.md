# Production: scalesafe.co.in on AIO

Status: **prepared, not executed** (2026-11-18). Nothing in this file has been applied. The live site stays on
Cloudflare until the owner gives the go decision. Do not start the cutover without it.

Staging today: https://scalesafe.capital (AIO, namespace `dev`, auto-sync; scaled to 0 from 23:00 to 08:00 IST).
Production target: AIO namespace `app-prod`, Argo CD application for env `prod`, **manual sync** (approval gate).

## 1. Corporate site (scalesafe.co.in)

### Gates (all must be true)

| # | Gate | Owner | How to check |
|---|---|---|---|
| 1 | The build to promote has been reviewed on scalesafe.capital (home, /solutions, /insights, legal pages) | Owner | Sign-off in writing |
| 2 | Accessibility statement: acknowledge/resolve days filled in (today `[2]` / `[15]`) | Owner | `grep -c "\[2\]" site-deploy/accessibility/index.html` returns 0 |
| 3 | Newsletter form target exists, **or** the form is hidden. On scalesafe.co.in it posts to `https://api.scalesafe.co.in/clients/...`, which only exists once the platform runs in production (section 2) | Owner + platform | `curl -i https://api.scalesafe.co.in/clients/api/v1/public/subscriptions` answers (not DNS failure) |
| 4 | Contact form destination decided (today formsubmit.co with a Gmail address; see CHANGES.md "Not applied") | Owner | Decision recorded |
| 5 | `tools/sync_from_live.py` run on the day, so the live content is current, then committed | Engineer | Clean `git status` |
| 6 | Current Cloudflare DNS records for `scalesafe.co.in` and `www` exported (the rollback) | Owner | Screenshot/export saved |

### DNS: choose one

- **A. Keep Cloudflare in front (recommended).** Cloudflare stays as proxy/CDN/WAF; only the origin changes to the
  AIO ingress (52.140.55.184). Set SSL mode to Full (strict) once the origin certificate is issued. Watch out:
  Let's Encrypt HTTP-01 must reach `/.well-known/acme-challenge/` on the origin; make sure no Cloudflare page rule,
  redirect or "Always Use HTTPS" setting blocks it during issuance (check the cert-manager Certificate status).
- **B. DNS straight to AIO.** Grey-cloud (DNS only) A records to 52.140.55.184. Simpler path, loses Cloudflare
  caching and WAF.

### Steps (when the go decision is given)

1. Pick the image: the `image.tag` in `apps/scalesafe-site/values-dev.yaml` (aio-gitops) that passed gate 1.
2. In aio-gitops, replace `apps/scalesafe-site/values-prod.yaml` with `deploy/values-prod.yaml`, setting
   `image.tag` to that value. Commit and push. Nothing deploys yet (prod is manual sync).
3. In the AIO portal, Domains tab, prod environment: add `scalesafe.co.in` with www redirect.
4. Sync the prod Argo CD application, pinned to the commit from step 2. Wait for 2/2 ready.
5. Test the origin before DNS: `curl --resolve scalesafe.co.in:443:52.140.55.184 -kI https://scalesafe.co.in/`
   (expect 200, no `X-Robots-Tag: noindex`). `-k` only until the certificate exists.
6. Change DNS (option A or B). Wait for the certificate to be Ready.
7. Verify: `sh tools/verify.sh https://scalesafe.co.in`, then the browser checks (axe WCAG 2.2 AA, phone menu,
   /solutions, /insights, legal pages, newsletter and contact forms).
8. Search: submit `https://scalesafe.co.in/sitemap.xml` in Google Search Console.

### Rollback

Restore the DNS records saved for gate 6. The Cloudflare-hosted site keeps running untouched until DNS moves,
so rollback is only a DNS change. Then scale the prod app to 0 in aio-gitops.

## 2. Platform (app., admin., api., id.scalesafe.co.in): blocked

Do not start until every blocker is cleared. Each is outside the code.

| Blocker | Why | Who provides |
|---|---|---|
| Real PAN, KRA, AML/PEP and bank-verification providers | verification-service refuses to start in live mode without real adapters (no sandbox in production) | Owner: contracts + credentials |
| SMTP token (ZeptoMail) for no-reply@scalesafe.co.in | Email verification for registered users (`deploy/infra/configure_email.py`); the `scalesafe-smtp` secret does not exist yet | Owner creates the secret |
| SMS provider with TRAI DLT entity, sender id and OTP template | Phone OTP in production (sandbox OTP is dev only) | Owner: DLT registration |
| Azure Key Vault + key, managed identity / RBAC | Per-person encryption keys (crypto-shredding) for DPDP erasure | Owner/infra |
| Retention periods confirmed by counsel (PMLA, SEBI) | Legal hold on erasure | Counsel |
| Independent IAAP accessibility audit | SEBI digital-accessibility expectations for client-facing journeys | Owner commissions |

When cleared: production values per service mirror `deploy/<service>/values-dev.yaml` with `scalesafe.co.in`
hosts (see scalesafe-platform `deploy/README.md`), Keycloak gets its own production database and realm import
with the `scalesafe` sign-in theme, and the same manual-sync gate applies.

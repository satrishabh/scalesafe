# scalesafe.co.in

Static marketing site for ScaleSafe.

| Path | What it is |
|---|---|
| `site-deploy/` | The site: static files, `404.html`, and `_headers` (Cloudflare Pages only). |
| `Dockerfile`, `nginx/` | Container for AIO: unprivileged nginx on 8080, `/health`, live-site headers and cache rules. |
| `deploy/` | AIO onboarding request, dev values and a build-only pipeline run. See `deploy/README.md`. |
| `CHANGES.md` | Changes made on top of the 2026-11-14 live snapshot. |
| `AUDIT-ACTIONS.md` | Audit findings and remaining actions. |
| `DEPLOY.md` | Deploy checklist and the subdomain plan (blog/newsletter, onboarding, profile). |

Note: `site-deploy/` was rebuilt from the live site, not from the original source project. See `DEPLOY.md` before replacing an existing deployment.

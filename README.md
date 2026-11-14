# scalesafe.co.in

Static marketing site for ScaleSafe.

| Path | What it is |
|---|---|
| `site-deploy/` | The site: static files, `404.html`, and `_headers` (Cloudflare Pages only). |
| `Dockerfile`, `nginx/` | Container for AIO: unprivileged nginx on 8080, `/health`, live-site headers and cache rules. |
| `deploy/` | AIO onboarding request, dev values, Argo CD app and a build-only pipeline run. See `deploy/README.md`. |
| `tools/` | `sync_from_live.py` (bring live-site changes in, re-apply fixes), `release.sh` (build on AIO, roll out the preview), `verify.sh` (check a deployment). |

## Workflow: live site → preview

scalesafe.co.in stays the live site. The AIO preview (https://scalesafe-site-dev.52.140.55.184.nip.io) is the test copy, and it is kept out of search engines (`X-Robots-Tag: noindex` and a disallow-all robots.txt on any host other than scalesafe.co.in).

1. Change the live site as usual.
2. `python tools/sync_from_live.py` re-crawls it and re-applies our fixes into `site-deploy/`. It stops without changing anything if a fix no longer fits the live page.
3. Review with `git diff site-deploy`, then commit and push.
4. `tools/release.sh` builds on AIO, scans, pins the image in GitOps, syncs Argo CD and runs `tools/verify.sh`.

To try a change on the preview before it goes live, edit `site-deploy/` directly and run steps 3–4. The next sync from live replaces those edits unless the same change has been made on the live site, or added as a fix in `tools/sync_from_live.py`.
| `CHANGES.md` | Changes made on top of the 2026-11-14 live snapshot. |
| `AUDIT-ACTIONS.md` | Audit findings and remaining actions. |
| `DEPLOY.md` | Deploy checklist and the subdomain plan (blog/newsletter, onboarding, profile). |

Note: `site-deploy/` was rebuilt from the live site, not from the original source project. See `DEPLOY.md` before replacing an existing deployment.

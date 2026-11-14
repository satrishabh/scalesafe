# Deploying scalesafe-site with AIO

The site is a container: `nginxinc/nginx-unprivileged` serving `site-deploy/` on port 8080 as uid 101, with `/health` for probes. Security headers and cache rules live in `nginx/` and match the live site.

Local check:

```sh
docker build -t scalesafe-site:local .
docker run --rm -p 127.0.0.1:18080:8080 scalesafe-site:local
curl -sI http://127.0.0.1:18080/
```

## Onboarding

1. **AIO portal (preferred).** Create the project with `deploy/aio-project.json`. This registers the webhook, so every push to `main` is built, scanned and deployed to dev.
2. **GitOps values.** Add `deploy/values-dev.yaml` as `apps/scalesafe-site/values-dev.yaml` in `satrishabh/aio-gitops`, unless the portal creates it.
3. **Manual build only.** `kubectl create -f deploy/pipeline-run.yaml` on the cluster running AIO's Tekton. It sets `deploy=false`, so it builds, pushes and scans without writing GitOps.

## Before pointing scalesafe.co.in at AIO

- DNS for scalesafe.co.in is on Cloudflare today. Add the commented `routes` entry in `values-dev.yaml` only when you are ready to move the record, because the certificate is issued only after DNS points at the AIO ingress.
- With Cloudflare proxying (orange cloud) in front of AIO, set SSL mode to Full (strict) and keep only one source of security headers. nginx sends them now; remove any duplicate Cloudflare Transform Rules.
- Check the preview first: all pages, the contact form, and `curl -sI` headers.

# scalesafe.co.in: static site served by unprivileged nginx on 8080 (AIO static-site convention).
# Alpine's own nginx package (2026-11-19): the nginxinc/nginx-unprivileged image still shipped nginx 1.30.6
# with 5 HIGH CVEs fixed in Alpine's 1.30.7-r0, and AIO's Trivy gate (HIGH/CRITICAL) blocked the release.
# The pod runs as uid 101 (runAsUser in the chart) with no volumes; nginx writes only to /tmp (nginx/nginx.conf).
FROM alpine:3.24

# Changes daily (set by AIO CI) so this layer is never served stale from the build cache.
ARG AIO_PATCH_DATE
RUN apk upgrade --no-cache \
 && apk add --no-cache nginx \
 && rm -rf /etc/nginx/http.d \
 && mkdir -p /etc/nginx/conf.d /etc/nginx/snippets /usr/share/nginx/html
COPY nginx/nginx.conf /etc/nginx/nginx.conf
COPY nginx/default.conf /etc/nginx/conf.d/default.conf
COPY nginx/security-headers.conf /etc/nginx/snippets/security-headers.conf
COPY site-deploy/ /usr/share/nginx/html/
# _headers is a Cloudflare Pages file; nginx sets the same headers itself.
RUN rm -f /usr/share/nginx/html/_headers
USER 101
# No build-time `nginx -t`: under AIO's kaniko build the runtime user and paths differ. nginx validates the
# config at startup, and the /health readiness probe keeps a bad config from receiving traffic.

EXPOSE 8080
CMD ["nginx", "-e", "/dev/stderr", "-g", "daemon off;"]

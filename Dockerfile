# scalesafe.co.in: static site served by unprivileged nginx on 8080 (AIO static-site convention).
FROM nginxinc/nginx-unprivileged:stable-alpine

USER root
RUN apk upgrade --no-cache && mkdir -p /etc/nginx/snippets
COPY nginx/default.conf /etc/nginx/conf.d/default.conf
COPY nginx/security-headers.conf /etc/nginx/snippets/security-headers.conf
COPY site-deploy/ /usr/share/nginx/html/
# _headers is a Cloudflare Pages file; nginx sets the same headers itself.
RUN rm -f /usr/share/nginx/html/_headers
USER 101
# Validate as the runtime user: testing as root leaves a root-owned /tmp/nginx.pid
# that stops nginx from starting as uid 101.
RUN nginx -t && rm -f /tmp/nginx.pid

EXPOSE 8080

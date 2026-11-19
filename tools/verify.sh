#!/bin/sh
# Check a deployed copy of the site.
# Usage: tools/verify.sh [base-url]   (default: the AIO preview)
# Exit 0 when every check passes.
B="${1:-https://scalesafe.capital}"
B="${B%/}"
REPO=$(cd "$(dirname "$0")/.." && pwd)
host=$(echo "$B" | sed -E 's#^https?://([^/:]+).*#\1#')
case "$host" in
  scalesafe.co.in|www.scalesafe.co.in) preview=0 ;;
  *) preview=1 ;;
esac
fail=0

check() { # path expected_code [expected_cache]
  H=$(curl -sI -m 15 "$B$1" | tr -d '\r')
  code=$(echo "$H" | head -1 | awk '{print $2}')
  cache=$(echo "$H" | awk -F': ' 'tolower($1)=="cache-control"{print $2}')
  sec=$(echo "$H" | grep -ciE '^(strict-transport-security|x-frame-options|x-content-type-options|referrer-policy|permissions-policy|cross-origin-opener-policy|content-security-policy-report-only):')
  robots=$(echo "$H" | awk -F': ' 'tolower($1)=="x-robots-tag"{print $2}')
  loc=$(echo "$H" | awk -F': ' 'tolower($1)=="location"{print $2}')
  ok=PASS
  [ "$code" != "$2" ] && ok=FAIL
  [ -n "$3" ] && [ "$cache" != "$3" ] && ok=FAIL
  if [ "$1" != "/health" ]; then
    [ "$sec" -lt 7 ] && ok=FAIL
    if [ "$preview" = 1 ]; then [ "$robots" != "noindex, nofollow" ] && ok=FAIL
    else [ -n "$robots" ] && ok=FAIL; fi
  fi
  [ "$ok" = FAIL ] && fail=1
  printf "%s %-46s %s sec=%s robots=[%s] cache=%s %s\n" "$ok" "$1" "$code" "$sec" "$robots" "$cache" "${loc:+loc=$loc}"
}

echo "Checking $B ($( [ "$preview" = 1 ] && echo preview || echo production ) host)"
check / 200 "public, max-age=0, must-revalidate"
check /terms 301
check /terms/ 200
check /privacy-notice/ 200
check /cookie-notice/ 200
check /accredited-investor-desk/ 200
check /llms.txt 200
check /robots.txt 200
check /sitemap.xml 200 "public, max-age=3600"
check /site.webmanifest 200
check /img/articles/dpdp-rules-2025.jpg 200 "public, max-age=2592000"
check /assets/fonts/ibm-plex-mono-400-latin.woff2 200 "public, max-age=2592000"
check /_headers 404
check /this-page-does-not-exist/ 404
check /health 200
check /insights/ 200 "public, max-age=0, must-revalidate"

# /insights: the sitemap lists the section and its articles; one article page is well-formed.
sm=$(curl -s -m 15 "$B/sitemap.xml")
n=$(echo "$sm" | grep -o '<loc>https://scalesafe.co.in/insights/[^<]*</loc>' | wc -l | tr -d ' ')
echo "$sm" | grep -q '<loc>https://scalesafe.co.in/insights/</loc>' && [ "$n" -gt 1 ] && echo "PASS sitemap lists /insights/ and $((n - 1)) article(s)" || { echo "FAIL sitemap /insights/ entries ($n)"; fail=1; }
slug=$(echo "$sm" | grep -o '<loc>https://scalesafe.co.in/insights/[a-z0-9-][a-z0-9-]*/</loc>' | head -1 | sed -E 's#.*/insights/([^/]+)/.*#\1#')
if [ -n "$slug" ]; then
  check "/insights/$slug/" 200 "public, max-age=0, must-revalidate"
  page=$(curl -s -m 15 "$B/insights/$slug/")
  canon=$(echo "$page" | grep -o '<link rel="canonical" href="[^"]*"' | sed -E 's/.*href="([^"]*)"/\1/')
  [ "$canon" = "https://scalesafe.co.in/insights/$slug/" ] && echo "PASS /insights/$slug/ canonical $canon" || { echo "FAIL /insights/$slug/ canonical [$canon]"; fail=1; }
  h1=$(echo "$page" | grep -o '<h1[ >]' | wc -l | tr -d ' ')
  [ "$h1" = 1 ] && echo "PASS /insights/$slug/ has exactly one <h1>" || { echo "FAIL /insights/$slug/ has $h1 <h1>"; fail=1; }
else
  echo "FAIL no article URL under /insights/ in the sitemap"; fail=1
fi

loc=$(curl -sI -m 15 "$B/terms" | tr -d '\r' | awk -F': ' 'tolower($1)=="location"{print $2}')
case "$loc" in /terms/|"$B/terms/") echo "PASS /terms redirect stays on host ($loc)";; *) echo "FAIL /terms redirect: $loc"; fail=1;; esac

rb=$(curl -s -m 15 "$B/robots.txt")
if [ "$preview" = 1 ]; then
  echo "$rb" | grep -q '^Disallow: /$' && echo "PASS robots.txt disallows all (preview)" || { echo "FAIL robots.txt should disallow all on preview"; fail=1; }
else
  echo "$rb" | grep -q '^Allow: /$' && echo "PASS robots.txt is the site's own" || { echo "FAIL robots.txt is not the site's own"; fail=1; }
fi

# nginx rewrites the production API origin per host (nginx/default.conf, map $api_origin): apply the same
# rewrite to the committed page before comparing, or every page with a form would differ on scalesafe.capital.
case "$B" in *scalesafe.capital*) api="https://api.scalesafe.capital" ;; *) api="https://api.scalesafe.co.in" ;; esac
rw() { sed "s#https://api.scalesafe.co.in#$api#g"; }
a=$(curl -s -m 20 "$B/" | md5sum | cut -c1-8)
b=$(git -C "$REPO" show HEAD:site-deploy/index.html | rw | md5sum | cut -c1-8)
w=$(rw < "$REPO/site-deploy/index.html" | md5sum | cut -c1-8)
if [ "$a" = "$b" ]; then echo "PASS home page matches committed site-deploy/index.html ($a)"
elif [ "$a" = "$w" ]; then echo "PASS home page matches working-tree site-deploy/index.html ($a; not committed yet)"
else echo "FAIL home page $a != committed $b"; fail=1; fi

tls=$(curl -s -o /dev/null -m 15 -w "%{ssl_verify_result}" "$B/")
case "$B" in https://*) [ "$tls" = 0 ] && echo "PASS TLS certificate valid" || { echo "FAIL TLS verify result $tls"; fail=1; };; esac

[ "$fail" = 0 ] && { echo "RESULT: ALL PASS"; exit 0; } || { echo "RESULT: FAILURES ABOVE"; exit 1; }

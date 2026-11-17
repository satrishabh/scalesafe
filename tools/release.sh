#!/bin/bash
# Build the committed site on AIO (Azure Tekton) and roll it out to the preview.
#
# Usage (from the repo root, Git Bash):  tools/release.sh
# Needs: az login (subscription with AKS 'creative'), kubectl, git with GitHub access.
#
# Steps, each one stopping the release on failure:
#   1. Refuse to run with uncommitted changes or commits not on origin/main.
#   2. Run deploy/pipeline-run.yaml on Azure: clone, test, build-push, Trivy scan (no GitOps write).
#   3. Require the scan to be clean at HIGH/CRITICAL.
#   4. Pin the new image digest in satrishabh/aio-gitops apps/scalesafe-site/values-dev.yaml.
#   5. Sync Argo CD app scalesafe-site-dev and wait for Synced/Healthy on the new digest.
#   6. Run tools/verify.sh against the preview.
# Rollback: put the previous digest back in the GitOps values file and sync (see deploy/README.md).
set -euo pipefail

APP=scalesafe-site
ARGO_APP=scalesafe-site-dev
NS=dev
RG=creative
CLUSTER=creative
GITOPS_REPO=https://github.com/satrishabh/aio-gitops.git
VALUES=apps/$APP/values-dev.yaml
PREVIEW=${PREVIEW:-https://scalesafe.capital}   # pre-corporate staging host (nip.io retired 2026-11-16)

REPO=$(cd "$(dirname "$0")/.." && pwd)
cd "$REPO"
say() { printf '\n== %s\n' "$*"; }

# Azure CLI may not be on Git Bash's PATH.
AZ=$(command -v az || true)
# (-f, not -x: Git Bash does not report .cmd files as executable)
[ -z "$AZ" ] && [ -f "/c/Program Files/Microsoft SDKs/Azure/CLI2/wbin/az.cmd" ] && AZ="/c/Program Files/Microsoft SDKs/Azure/CLI2/wbin/az.cmd"
[ -z "$AZ" ] && { echo "Azure CLI not found. Install it and run az login."; exit 1; }

say "1. Source"
[ -n "$(git status --porcelain)" ] && { echo "Uncommitted changes. Commit them first."; git status --short; exit 1; }
git fetch -q origin main
[ "$(git rev-parse HEAD)" != "$(git rev-parse origin/main)" ] && { echo "HEAD is not origin/main. Push (or pull) first."; exit 1; }
SHA=$(git rev-parse --short=12 HEAD)
echo "Releasing $SHA"

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
export KUBECONFIG="$TMP/kubeconfig"   # separate file: ~/.kube/config is left alone
"$AZ" aks get-credentials -g "$RG" -n "$CLUSTER" --file "$KUBECONFIG" -o none 2>/dev/null
k() { kubectl --request-timeout=60s "$@"; }

say "2. Build on AIO (Azure Tekton)"
RUN=$(k create -f deploy/pipeline-run.yaml -o jsonpath='{.metadata.name}')
echo "PipelineRun ci/$RUN"
for i in $(seq 1 120); do
  st=$(k -n ci get pipelinerun "$RUN" -o jsonpath='{.status.conditions[0].status}' 2>/dev/null || true)
  [ "$st" = True ] || [ "$st" = False ] && break
  sleep 15
done
reason=$(k -n ci get pipelinerun "$RUN" -o jsonpath='{.status.conditions[0].reason}')
k -n ci get taskruns -l tekton.dev/pipelineRun="$RUN" \
  -o custom-columns=TASK:.metadata.labels.tekton\\.dev/pipelineTask,STATUS:.status.conditions[0].reason --no-headers
[ "$st" = True ] || { echo "Build $reason. Logs: kubectl -n ci logs -l tekton.dev/pipelineRun=$RUN --all-containers"; exit 1; }
results=$(k -n ci get taskruns -l tekton.dev/pipelineRun="$RUN" -o jsonpath='{range .items[*]}{range .status.results[*]}{.name}={.value}{"\n"}{end}{end}')
DIGEST=$(echo "$results" | sed -n 's/^IMAGE_DIGEST=//p' | head -1)
SUMMARY=$(echo "$results" | sed -n 's/^SUMMARY=//p' | head -1)
echo "digest=$DIGEST scan: $SUMMARY"
[[ "$DIGEST" =~ ^sha256:[a-f0-9]{64}$ ]] || { echo "No image digest in the run results."; exit 1; }

say "3. Scan gate"
crit=$(echo "$SUMMARY" | sed -n 's/.*critical=\([0-9]*\).*/\1/p'); high=$(echo "$SUMMARY" | sed -n 's/.*high=\([0-9]*\).*/\1/p')
[ "${crit:-1}" = 0 ] && [ "${high:-1}" = 0 ] || { echo "Scan not clean ($SUMMARY). Not releasing."; exit 1; }
echo "clean"

say "4. GitOps"
git clone -q "$GITOPS_REPO" "$TMP/gitops"
f="$TMP/gitops/$VALUES"
[ -f "$f" ] || { echo "$VALUES not found in aio-gitops."; exit 1; }
prev=$(sed -n 's/^  tag: //p' "$f" | tr -d '\r')
if [ "$prev" = "$DIGEST" ]; then
  echo "Already pinned to $DIGEST (identical build); no GitOps change."
else
  sed -i "s|^  tag: .*|  tag: $DIGEST|" "$f"
  sed -i "s|^# Source: .*|# Source: github.com/satrishabh/scalesafe @ $SHA, built by ci/$RUN|" "$f"
  sed -i "s|^# (Trivy HIGH/CRITICAL gate: .*|# (Trivy HIGH/CRITICAL gate: $(echo "$SUMMARY" | tr ',' ' '))|" "$f"
  git -C "$TMP/gitops" add "$VALUES"
  if git -C "$TMP/gitops" diff --cached --quiet; then
    echo "No effective GitOps change."
  else
  git -C "$TMP/gitops" commit -q -m "deploy($APP): $SHA to dev (preview)

Image ${DIGEST} from ci/$RUN, scan $SUMMARY.
Previous: $prev"
  git -C "$TMP/gitops" push -q origin main
  echo "aio-gitops $(git -C "$TMP/gitops" rev-parse --short HEAD): $prev -> $DIGEST"
  fi
fi

say "5. Argo CD sync"
k -n argocd patch application "$ARGO_APP" --type merge \
  -p '{"operation":{"initiatedBy":{"username":"release.sh"},"sync":{"revision":"main","prune":false}}}' >/dev/null
for i in $(seq 1 60); do
  s=$(k -n argocd get application "$ARGO_APP" -o jsonpath='{.status.operationState.phase}|{.status.sync.status}|{.status.health.status}')
  live=$(k -n "$NS" get deploy "$APP" -o jsonpath='{.spec.template.spec.containers[0].image}' 2>/dev/null || true)
  ready=$(k -n "$NS" get deploy "$APP" -o jsonpath='{.status.updatedReplicas}/{.status.readyReplicas}/{.spec.replicas}' 2>/dev/null || true)
  if [ "$s" = "Succeeded|Synced|Healthy" ] && [[ "$live" == *"$DIGEST" ]] && [ "$ready" = "1/1/1" ]; then break; fi
  case "$s" in Failed*|Error*) echo "Argo sync $s"; exit 1;; esac
  sleep 10
done
echo "argo: $s | image: ${live##*@} | replicas updated/ready/desired: $ready"
[[ "$live" == *"$DIGEST" ]] || { echo "Rollout did not reach the new digest in time."; exit 1; }

say "6. Verify preview"
sh "$REPO/tools/verify.sh" "$PREVIEW"

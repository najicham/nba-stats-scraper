#!/usr/bin/env bash
# Verify that the deployed code is actually the code you think it is.
#
# WHY THIS EXISTS
# ---------------
# On 2026-08-20 six Cloud Functions reported SUCCESSFUL builds, `gcloud
# functions deploy` exited 0, and all six kept serving old code. Two more
# (`transition-monitor`, `grading-gap-detector`) were found the next day, one of
# them seven weeks stale.
#
# The check that caught the first six — `latestReady == latestCreated` — is NOT
# sufficient. When a nested source build EXPIRES, no revision is created at all,
# so both fields still point at the OLD revision and the comparison passes while
# gcloud prints a hard ERROR and exits 0.
#
# The only honest check is to read BUILD_COMMIT off the revision that is
# actually receiving traffic. That is what this does.
#
# Note the length mismatch: Cloud Build's ${SHORT_SHA} is 7 characters while
# bin/deploy-function.sh uses `git rev-parse --short` (8 here). Prefix-match,
# never string-equal.
#
# Usage:  ./bin/verify-deploy.sh [service ...]     (default: the halt-gate set)
set -uo pipefail

PROJECT=nba-props-platform
REGION=us-west2
HEAD8=$(git rev-parse --short=8 HEAD)
HEAD7=${HEAD8:0:7}
FAIL=0

DEFAULT_SERVICES=(halt-state-writer phase6-export post-grading-export weekly-retrain)
SERVICES=("${@:-${DEFAULT_SERVICES[@]}}")

echo "Expecting BUILD_COMMIT to start with ${HEAD7} (HEAD=${HEAD8})"
echo

check() {
  local svc=$1 traffic_rev commit

  traffic_rev=$(timeout 90 gcloud run services list --region="$REGION" --project="$PROJECT" \
      --filter="metadata.name=$svc" --format="json(status.traffic)" 2>/dev/null \
    | python3 -c "
import json,sys
try:
    t = json.load(sys.stdin)[0]['status']['traffic']
except Exception:
    print(''); raise SystemExit
print(next((x.get('revisionName','') for x in t if x.get('percent') == 100), ''))
")

  if [[ -z "$traffic_rev" ]]; then
    echo "ERROR $svc — could not resolve the traffic-bearing revision"
    FAIL=1; return
  fi

  commit=$(timeout 90 gcloud run revisions list --service="$svc" --region="$REGION" \
      --project="$PROJECT" --limit=10 --format="json(metadata.name,spec.containers)" 2>/dev/null \
    | python3 -c "
import json,sys
rev = '$traffic_rev'
for r in json.load(sys.stdin):
    if r['metadata']['name'] == rev:
        env = {e['name']: e.get('value','') for e in (r['spec']['containers'][0].get('env') or [])}
        print(env.get('BUILD_COMMIT','MISSING')); break
else:
    print('REVISION_NOT_LISTED')
")

  case "$commit" in
    ${HEAD7}*) echo "OK    $svc  BUILD_COMMIT=$commit  rev=$traffic_rev" ;;
    *)         echo "STALE $svc  BUILD_COMMIT=$commit  rev=$traffic_rev  (expected ${HEAD7}*)"
               FAIL=1 ;;
  esac
}

for s in "${SERVICES[@]}"; do check "$s"; done

echo
echo "Builds that did not succeed (quota failures show up here):"
timeout 120 gcloud builds list --region="$REGION" --project="$PROJECT" --limit=40 \
  --format="table(status,substitutions.TRIGGER_NAME,createTime)" 2>/dev/null \
  | grep -v SUCCESS || echo "  (none)"

echo
if [[ $FAIL -eq 0 ]]; then
  echo "PASS — every checked service is serving HEAD"
else
  echo "FAIL — at least one service is NOT serving HEAD. Do not assume the deploy landed."
fi
exit $FAIL

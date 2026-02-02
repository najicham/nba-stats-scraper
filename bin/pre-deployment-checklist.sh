#!/bin/bash
#
# Pre-Deployment Checklist
#
# Validates that a service is ready for deployment.
# Run this BEFORE deploying to catch issues early.
#
# Usage:
#   ./bin/pre-deployment-checklist.sh <service-name>
#
# Example:
#   ./bin/pre-deployment-checklist.sh nba-phase4-precompute-processors
#
# Exit codes:
#   0 = All checks passed, safe to deploy
#   1 = Some checks failed, review before deploying

set -euo pipefail

if [[ $# -lt 1 ]]; then
    echo "Usage: $0 <service-name>"
    echo ""
    echo "Available services:"
    echo "  - nba-phase4-precompute-processors"
    echo "  - nba-phase3-analytics-processors"
    echo "  - nba-phase2-processors"
    echo "  - prediction-worker"
    echo "  - prediction-coordinator"
    echo "  - nba-scrapers"
    exit 1
fi

SERVICE=$1
EXIT_CODE=0

echo "═══════════════════════════════════════════════════════════"
echo "  Pre-Deployment Checklist: $SERVICE"
echo "═══════════════════════════════════════════════════════════"
echo ""

# Check 1: Uncommitted changes
echo "[1/8] Checking for uncommitted changes..."
if [[ -n $(git status --porcelain) ]]; then
    echo "❌ FAIL: Uncommitted changes detected"
    echo ""
    git status --short
    echo ""
    echo "   Action: Commit or stash changes before deploying"
    EXIT_CODE=1
else
    echo "✅ PASS: No uncommitted changes"
fi
echo ""

# Check 2: Current branch
echo "[2/8] Checking branch..."
BRANCH=$(git branch --show-current)
if [[ "$BRANCH" != "main" ]]; then
    echo "⚠️  WARNING: Not on main branch (current: $BRANCH)"
    echo "   Consider merging to main before deploying to production"
else
    echo "✅ PASS: On main branch"
fi
echo ""

# Check 3: Sync with remote
echo "[3/8] Checking if local is synced with remote..."
git fetch origin --quiet
LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse origin/main)

if [[ "$LOCAL" != "$REMOTE" ]]; then
    echo "❌ FAIL: Local is not synced with remote"

    # Check if we're ahead or behind
    AHEAD=$(git rev-list --count origin/main..HEAD)
    BEHIND=$(git rev-list --count HEAD..origin/main)

    if [[ $BEHIND -gt 0 ]]; then
        echo "   You are $BEHIND commits behind origin/main"
        echo "   Action: git pull origin main"
    fi

    if [[ $AHEAD -gt 0 ]]; then
        echo "   You are $AHEAD commits ahead of origin/main"
        echo "   Action: git push origin main"
    fi

    EXIT_CODE=1
else
    echo "✅ PASS: Local synced with remote"
fi
echo ""

# Check 4: Recent commits review
echo "[4/8] Reviewing recent commits..."
echo "   Last 3 commits:"
git log --oneline --decorate -3 | sed 's/^/   /'
echo ""

# Check 5: Check for breaking changes in recent commits
echo "[5/8] Checking for schema changes..."
SCHEMA_CHANGES=$(git diff HEAD~5 schemas/bigquery/ 2>/dev/null | grep -c "ALTER TABLE\|ADD COLUMN\|DROP COLUMN" || echo "0")

if [[ $SCHEMA_CHANGES -gt 0 ]]; then
    echo "⚠️  WARNING: Schema changes detected in last 5 commits"
    echo "   Found $SCHEMA_CHANGES schema modifications"
    echo "   Action: Ensure schema migrations are applied BEFORE deploying code"
    echo ""
    git diff HEAD~5 schemas/bigquery/ | grep -E "ALTER TABLE|ADD COLUMN|DROP COLUMN" | sed 's/^/   /' || true
else
    echo "✅ PASS: No recent schema changes"
fi
echo ""

# Check 6: Run tests (if they exist)
echo "[6/8] Checking for tests..."
if [[ -d "tests/${SERVICE}" ]] && [[ -n $(find tests/${SERVICE} -name "test_*.py" 2>/dev/null) ]]; then
    echo "   Running tests for $SERVICE..."

    if PYTHONPATH=. pytest tests/${SERVICE}/ -v --tb=short -q 2>&1 | tail -20; then
        echo "✅ PASS: Tests passed"
    else
        echo "❌ FAIL: Tests failed"
        EXIT_CODE=1
    fi
elif [[ -f "tests/test_${SERVICE}.py" ]]; then
    echo "   Running test file..."

    if PYTHONPATH=. pytest tests/test_${SERVICE}.py -v --tb=short -q 2>&1 | tail -20; then
        echo "✅ PASS: Tests passed"
    else
        echo "❌ FAIL: Tests failed"
        EXIT_CODE=1
    fi
else
    echo "⚠️  WARNING: No tests found for $SERVICE"
    echo "   Consider adding tests to prevent regressions"
fi
echo ""

# Check 7: Current deployment status
echo "[7/8] Checking current deployment..."
CURRENT_DEPLOYED=$(gcloud run services describe $SERVICE --region=us-west2 \
    --format="value(metadata.labels.commit-sha)" 2>/dev/null || echo "unknown")

if [[ "$CURRENT_DEPLOYED" != "unknown" ]]; then
    echo "   Currently deployed: $CURRENT_DEPLOYED"
    git log --oneline -1 $CURRENT_DEPLOYED 2>/dev/null | sed 's/^/   /' || echo "   (commit not in current branch)"
    echo ""
    echo "   About to deploy: $LOCAL"
    git log --oneline -1 $LOCAL | sed 's/^/   /'
    echo ""

    if [[ "$CURRENT_DEPLOYED" == "$LOCAL" ]]; then
        echo "⚠️  WARNING: Already deployed this commit"
        echo "   Redeployment will create a new revision with same code"
    else
        COMMITS_DIFF=$(git rev-list --count $CURRENT_DEPLOYED..$LOCAL 2>/dev/null || echo "unknown")
        if [[ "$COMMITS_DIFF" != "unknown" ]]; then
            echo "   This deployment includes $COMMITS_DIFF new commits"
        fi
    fi
else
    echo "   Could not determine current deployment"
    echo "   Service may not exist yet (first deployment)"
fi
echo ""

# Check 8: Service health
echo "[8/8] Verifying current service health..."
URL=$(gcloud run services describe $SERVICE --region=us-west2 \
    --format="value(status.url)" 2>/dev/null || echo "")

if [[ -n "$URL" ]]; then
    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" -m 10 $URL/health 2>/dev/null || echo "000")

    if [[ "$HTTP_CODE" == "200" ]]; then
        echo "✅ PASS: Service is healthy (HTTP $HTTP_CODE)"
    elif [[ "$HTTP_CODE" == "000" ]]; then
        echo "⚠️  WARNING: Could not reach service (timeout or connection error)"
    else
        echo "⚠️  WARNING: Service returned HTTP $HTTP_CODE (expected 200)"
    fi
else
    echo "   Service URL not found (may be first deployment)"
fi
echo ""

# Summary
echo "═══════════════════════════════════════════════════════════"
if [[ $EXIT_CODE -eq 0 ]]; then
    echo "  ✅ CHECKLIST COMPLETE - Safe to deploy"
    echo ""
    echo "  Next step:"
    echo "  ./bin/deploy-service.sh $SERVICE"
else
    echo "  ❌ SOME CHECKS FAILED - Review before deploying"
    echo ""
    echo "  Fix the issues above, then run this checklist again"
fi
echo "═══════════════════════════════════════════════════════════"

exit $EXIT_CODE

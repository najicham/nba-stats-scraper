#!/bin/bash
# Pre-Implementation Verification Script
# Checks critical items before starting Week 1 Day 1

set -uo pipefail

echo "========================================="
echo "Pre-Implementation Verification"
echo "========================================="
echo ""
echo "Checking critical items before implementation..."
echo ""

ERRORS=0
WARNINGS=0

# ============================================
# CRITICAL CHECK 1: Phase 3 Rolling Averages
# ============================================
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "CHECK 1: Phase 3 Self-Referential Queries"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if [ -d "data_processors/analytics" ]; then
    echo "Searching for queries reading from nba_analytics..."

    self_ref=$(grep -r "FROM.*nba_analytics\|JOIN.*nba_analytics" data_processors/analytics/ \
        --include="*.py" \
        2>/dev/null | grep -v "^Binary" || true)

    if [ -n "$self_ref" ]; then
        echo "⚠️  Found potential self-referential queries:"
        echo ""
        echo "$self_ref" | head -10
        echo ""
        echo "❌ CRITICAL: Review these queries manually"
        echo "   If processors read from nba_analytics for rolling averages,"
        echo "   parallel backfill will produce incorrect data."
        echo ""
        echo "Action: Review each processor:"
        echo "  - data_processors/analytics/player_game_summary/"
        echo "  - data_processors/analytics/upcoming_player_game_context/"
        echo "  - data_processors/analytics/upcoming_team_game_context/"
        echo ""
        ((ERRORS++))
    else
        echo "✅ No self-referential queries found in Phase 3"
        echo "   Safe to process dates in parallel during backfill"
    fi
else
    echo "⚠️  Warning: data_processors/analytics/ not found"
    echo "   (skipping check - verify path correct)"
    ((WARNINGS++))
fi

echo ""

# ============================================
# CRITICAL CHECK 2: Cloud Run Quota
# ============================================
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "CHECK 2: Cloud Run Quota Limits"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if command -v gcloud &> /dev/null; then
    echo "Checking Cloud Run services..."

    # Try to get service info
    service_info=$(gcloud run services describe nba-phase1-scrapers \
        --region=us-west2 \
        --format='value(status.url)' \
        2>/dev/null || echo "")

    if [ -n "$service_info" ]; then
        echo "✅ Cloud Run service 'nba-phase1-scrapers' found"
        echo "   URL: $service_info"
        echo ""
        echo "⚠️  Manual action required:"
        echo "   1. Check quota limits at:"
        echo "      https://console.cloud.google.com/iam-admin/quotas"
        echo "   2. Search for 'Cloud Run' quotas"
        echo "   3. Verify 'Concurrent requests' ≥ 210"
        echo "   4. If < 210, request quota increase or reduce PARALLEL_DATES"
        echo ""
        ((WARNINGS++))
    else
        echo "❌ Cloud Run service 'nba-phase1-scrapers' not found"
        echo "   Either not deployed yet, or check service name/region"
        echo ""
        ((ERRORS++))
    fi
else
    echo "⚠️  gcloud command not found"
    echo "   Install gcloud CLI to check quotas automatically"
    echo ""
    echo "Manual check required:"
    echo "  https://console.cloud.google.com/iam-admin/quotas"
    echo ""
    ((WARNINGS++))
fi

# ============================================
# CRITICAL CHECK 3: RunHistoryMixin
# ============================================
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "CHECK 3: RunHistoryMixin Immediate Write"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

mixin_file="shared/processors/mixins/run_history_mixin.py"

if [ -f "$mixin_file" ]; then
    echo "Checking RunHistoryMixin implementation..."

    # Check if start_run_tracking writes status immediately
    if grep -A 20 "def start_run_tracking" "$mixin_file" | grep -q "status.*running\|'running'"; then
        echo "✅ RunHistoryMixin writes 'running' status immediately"
        echo "   Deduplication will work correctly with Pub/Sub retries"
    else
        echo "❌ CRITICAL: RunHistoryMixin may not write immediate status"
        echo ""
        echo "Expected behavior:"
        echo "  def start_run_tracking(...):"
        echo "      row = {'status': 'running', ...}"
        echo "      self.bq_client.insert_rows(...)"
        echo ""
        echo "Action: Add immediate 'running' status write to prevent"
        echo "        duplicate processing during Pub/Sub retries"
        echo ""
        ((ERRORS++))
    fi
else
    echo "❌ File not found: $mixin_file"
    echo "   Check file path or codebase structure"
    echo ""
    ((ERRORS++))
fi

echo ""

# ============================================
# CRITICAL CHECK 4: skip_downstream_trigger
# ============================================
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "CHECK 4: skip_downstream_trigger Handling"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

processor_base="data_processors/raw/processor_base.py"

if [ -f "$processor_base" ]; then
    echo "Checking Phase 2 processor base..."

    if grep -q "skip_downstream_trigger" "$processor_base"; then
        echo "✅ Phase 2 checks skip_downstream_trigger flag"
        echo ""

        # Verify it's actually used in publish method
        if grep -A 10 "_publish_completion_event\|publish_completion" "$processor_base" \
            | grep -q "skip_downstream_trigger"; then
            echo "✅ Flag is checked in publish method"
            echo "   Backfill mode will not trigger downstream"
        else
            echo "⚠️  Flag exists but may not be checked in publish"
            echo "   Verify manually in _publish_completion_event()"
            ((WARNINGS++))
        fi
    else
        echo "❌ CRITICAL: Phase 2 doesn't check skip_downstream_trigger"
        echo ""
        echo "Expected in _publish_completion_event():"
        echo "  if self.opts.get('skip_downstream_trigger', False):"
        echo "      logger.info('Backfill mode: skipping downstream')"
        echo "      return"
        echo ""
        echo "Action: Add flag check to prevent backfill triggering full pipeline"
        echo ""
        ((ERRORS++))
    fi
else
    echo "❌ File not found: $processor_base"
    echo "   Check file path or codebase structure"
    echo ""
    ((ERRORS++))
fi

echo ""

# ============================================
# IMPORTANT CHECK 5: Bash Version
# ============================================
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "CHECK 5: Bash Version"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if ((BASH_VERSINFO[0] < 4 || (BASH_VERSINFO[0] == 4 && BASH_VERSINFO[1] < 3))); then
    echo "❌ Bash ${BASH_VERSION} is too old"
    echo "   Backfill scripts require Bash 4.3+"
    echo "   Features used: array[-1], nameref (-n)"
    echo ""
    echo "Action: Upgrade Bash or refactor scripts"
    echo ""
    ((ERRORS++))
else
    echo "✅ Bash ${BASH_VERSION} is compatible"
    echo "   Supports array[-1] and nameref syntax"
fi

echo ""

# ============================================
# SUMMARY
# ============================================
echo "========================================="
echo "VERIFICATION SUMMARY"
echo "========================================="
echo ""

if [ $ERRORS -eq 0 ] && [ $WARNINGS -eq 0 ]; then
    echo "✅ ALL CHECKS PASSED"
    echo ""
    echo "Ready to begin Week 1 Day 1 implementation!"
    echo ""
    exit 0
elif [ $ERRORS -eq 0 ]; then
    echo "⚠️  ${WARNINGS} WARNING(S)"
    echo ""
    echo "No critical issues, but review warnings above."
    echo "You can proceed with implementation."
    echo ""
    exit 0
else
    echo "❌ ${ERRORS} CRITICAL ISSUE(S) FOUND"
    if [ $WARNINGS -gt 0 ]; then
        echo "⚠️  ${WARNINGS} WARNING(S)"
    fi
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "ACTION REQUIRED BEFORE IMPLEMENTATION"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
    echo "1. Review errors above"
    echo "2. Fix critical issues"
    echo "3. Re-run this script"
    echo "4. Update PRE-IMPLEMENTATION-CHECKLIST.md with findings"
    echo ""
    echo "See: docs/08-projects/current/phase4-phase5-integration/"
    echo "     PRE-IMPLEMENTATION-CHECKLIST.md"
    echo ""
    exit 1
fi

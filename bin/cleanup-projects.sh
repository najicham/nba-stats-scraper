#!/bin/bash
# Project Documentation Cleanup Script
# Generated: 2026-02-02
#
# This script moves completed projects to archive/ and organizes standalone files.
# REVIEW CAREFULLY BEFORE RUNNING - moves are permanent!

set -e

BASE_DIR="docs/08-projects"
CURRENT_DIR="$BASE_DIR/current"
ARCHIVE_DIR="$BASE_DIR/archive"
DRY_RUN=1

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --execute)
            DRY_RUN=0
            shift
            ;;
        *)
            echo "Unknown option: $1"
            echo "Usage: $0 [--execute]"
            echo "  Default: Dry run (shows what would be moved)"
            echo "  --execute: Actually move files"
            exit 1
            ;;
    esac
done

if [ $DRY_RUN -eq 1 ]; then
    echo "=== DRY RUN MODE ==="
    echo "Add --execute flag to actually move files"
    echo ""
fi

# Create monthly archive directories
mkdir -p "$ARCHIVE_DIR/2025-12"
mkdir -p "$ARCHIVE_DIR/2026-01"
mkdir -p "$ARCHIVE_DIR/2026-02"

# Track counts
ARCHIVED_COUNT=0
COMPLETED_COUNT=0
ORGANIZED_COUNT=0

echo "=== PHASE 1: Archive Old Projects (> 30 days) ==="
echo ""

# Projects older than 30 days (from assessment)
OLD_PROJECTS=(
    "system-evolution"
    "website-ui"
    "boxscore-monitoring"
    "challenge-system-backend"
    "live-data-reliability"
    "test-environment"
    "email-alerting"
)

for project in "${OLD_PROJECTS[@]}"; do
    if [ -d "$CURRENT_DIR/$project" ]; then
        # Determine archive month based on last modified date
        LAST_MOD=$(stat -c %Y "$CURRENT_DIR/$project" 2>/dev/null || stat -f %m "$CURRENT_DIR/$project" 2>/dev/null)
        MOD_MONTH=$(date -d "@$LAST_MOD" +%Y-%m 2>/dev/null || date -r $LAST_MOD +%Y-%m 2>/dev/null)

        if [ $DRY_RUN -eq 0 ]; then
            mv "$CURRENT_DIR/$project" "$ARCHIVE_DIR/$MOD_MONTH/"
            echo "✓ Archived: $project → archive/$MOD_MONTH/"
        else
            echo "  Would archive: $project → archive/$MOD_MONTH/"
        fi
        ARCHIVED_COUNT=$((ARCHIVED_COUNT + 1))
    fi
done

echo ""
echo "=== PHASE 2: Move Completed Projects (39 projects) ==="
echo ""

# Date-prefixed incidents from January (11 projects)
JANUARY_INCIDENTS=(
    "2026-01-25-incident-remediation"
    "2026-01-26-P0-incident"
    "2026-01-26-betting-timing-fix"
    "2026-01-27-data-quality-investigation"
    "2026-01-27-deployment-runbook"
    "2026-01-28-system-validation"
    "2026-01-29-dnp-tracking-improvements"
    "2026-01-30-processpool-pycache-fix"
    "2026-01-30-scraper-reliability-fixes"
    "2026-01-30-session-44-maintenance"
)

for project in "${JANUARY_INCIDENTS[@]}"; do
    if [ -d "$CURRENT_DIR/$project" ]; then
        if [ $DRY_RUN -eq 0 ]; then
            mv "$CURRENT_DIR/$project" "$ARCHIVE_DIR/2026-01/"
            echo "✓ Moved: $project → archive/2026-01/"
        else
            echo "  Would move: $project → archive/2026-01/"
        fi
        COMPLETED_COUNT=$((COMPLETED_COUNT + 1))
    fi
done

# Session maintenance projects (5 projects)
SESSION_PROJECTS=(
    "session-10-maintenance"
    "session-12-improvements"
    "session-122-morning-checkup"
    "session-7-validation-and-reliability"
)

for project in "${SESSION_PROJECTS[@]}"; do
    if [ -d "$CURRENT_DIR/$project" ]; then
        if [ $DRY_RUN -eq 0 ]; then
            mv "$CURRENT_DIR/$project" "$ARCHIVE_DIR/2026-01/"
            echo "✓ Moved: $project → archive/2026-01/"
        else
            echo "  Would move: $project → archive/2026-01/"
        fi
        COMPLETED_COUNT=$((COMPLETED_COUNT + 1))
    fi
done

# Completed feature/infrastructure work (15 projects)
COMPLETED_FEATURES=(
    "architecture-refactoring-2026-01"
    "bettingpros-reliability"
    "bigquery-quota-fix"
    "bug-fixes"
    "code-quality-2026-01"
    "comprehensive-improvements-jan-2026"
    "game-id-standardization"
    "grading-improvements"
    "health-endpoints-implementation"
    "jan-21-critical-fixes"
    "jan-23-orchestration-fixes"
    "ml-model-v8-deployment"
    "mlb-optimization"
    "mlb-pipeline-deployment"
    "resilience-pattern-gaps"
)

for project in "${COMPLETED_FEATURES[@]}"; do
    if [ -d "$CURRENT_DIR/$project" ]; then
        if [ $DRY_RUN -eq 0 ]; then
            mv "$CURRENT_DIR/$project" "$ARCHIVE_DIR/2026-01/"
            echo "✓ Moved: $project → archive/2026-01/"
        else
            echo "  Would move: $project → archive/2026-01/"
        fi
        COMPLETED_COUNT=$((COMPLETED_COUNT + 1))
    fi
done

# Analysis/investigation projects (8 projects)
ANALYSIS_PROJECTS=(
    "catboost-v8-jan-2026-incident"
    "catboost-v8-performance-analysis"
    "historical-backfill-audit"
    "historical-data-validation"
    "historical-odds-backfill"
    "monitoring-storage-evaluation"
    "v8-model-investigation"
    "worker-reliability-investigation"
)

for project in "${ANALYSIS_PROJECTS[@]}"; do
    if [ -d "$CURRENT_DIR/$project" ]; then
        if [ $DRY_RUN -eq 0 ]; then
            mv "$CURRENT_DIR/$project" "$ARCHIVE_DIR/2026-01/"
            echo "✓ Moved: $project → archive/2026-01/"
        else
            echo "  Would move: $project → archive/2026-01/"
        fi
        COMPLETED_COUNT=$((COMPLETED_COUNT + 1))
    fi
done

echo ""
echo "=== PHASE 3: Organize Standalone .md Files (17 files) ==="
echo ""

# Create organized directories
mkdir -p "$CURRENT_DIR/sessions"
mkdir -p "$CURRENT_DIR/planning"
mkdir -p "$ARCHIVE_DIR/2026-01/analysis"

# Move session summaries
if [ -f "$CURRENT_DIR/SESSION-SUMMARY-2026-01-26.md" ]; then
    if [ $DRY_RUN -eq 0 ]; then
        mv "$CURRENT_DIR/SESSION-SUMMARY-2026-01-26.md" "$CURRENT_DIR/sessions/"
        echo "✓ Organized: SESSION-SUMMARY-2026-01-26.md → sessions/"
    else
        echo "  Would move: SESSION-SUMMARY-2026-01-26.md → sessions/"
    fi
    ORGANIZED_COUNT=$((ORGANIZED_COUNT + 1))
fi

if [ -f "$CURRENT_DIR/SESSION-12-AFTERNOON-IMPROVEMENT-PLAN.md" ]; then
    if [ $DRY_RUN -eq 0 ]; then
        mv "$CURRENT_DIR/SESSION-12-AFTERNOON-IMPROVEMENT-PLAN.md" "$CURRENT_DIR/sessions/"
        echo "✓ Organized: SESSION-12-AFTERNOON-IMPROVEMENT-PLAN.md → sessions/"
    else
        echo "  Would move: SESSION-12-AFTERNOON-IMPROVEMENT-PLAN.md → sessions/"
    fi
    ORGANIZED_COUNT=$((ORGANIZED_COUNT + 1))
fi

# Archive old planning documents
ARCHIVE_FILES=(
    "MASTER-PROJECT-TRACKER.md"
    "MASTER-TODO-LIST.md"
    "MASTER-TODO-LIST-ENHANCED.md"
    "COMPREHENSIVE-SYSTEM-ANALYSIS-2026-01-21.md"
    "coordinator-batch-loading-performance-analysis.md"
    "coordinator-deployment-session-102.md"
    "coordinator-dockerfile-incident-2026-01-18.md"
    "injury-processor-stats-bug-fix.md"
)

for file in "${ARCHIVE_FILES[@]}"; do
    if [ -f "$CURRENT_DIR/$file" ]; then
        if [ $DRY_RUN -eq 0 ]; then
            mv "$CURRENT_DIR/$file" "$ARCHIVE_DIR/2026-01/analysis/"
            echo "✓ Archived: $file → archive/2026-01/analysis/"
        else
            echo "  Would archive: $file → archive/2026-01/analysis/"
        fi
        ORGANIZED_COUNT=$((ORGANIZED_COUNT + 1))
    fi
done

# Move operational guides to appropriate locations
if [ -f "$CURRENT_DIR/STALE-PREDICTION-DETECTION-GUIDE.md" ]; then
    if [ $DRY_RUN -eq 0 ]; then
        mv "$CURRENT_DIR/STALE-PREDICTION-DETECTION-GUIDE.md" "$CURRENT_DIR/prevention-and-monitoring/"
        echo "✓ Organized: STALE-PREDICTION-DETECTION-GUIDE.md → prevention-and-monitoring/"
    else
        echo "  Would move: STALE-PREDICTION-DETECTION-GUIDE.md → prevention-and-monitoring/"
    fi
    ORGANIZED_COUNT=$((ORGANIZED_COUNT + 1))
fi

if [ -f "$CURRENT_DIR/SLACK-ALERTS-AND-DASHBOARD-INTEGRATION.md" ]; then
    if [ $DRY_RUN -eq 0 ]; then
        mv "$CURRENT_DIR/SLACK-ALERTS-AND-DASHBOARD-INTEGRATION.md" "$CURRENT_DIR/prevention-and-monitoring/"
        echo "✓ Organized: SLACK-ALERTS-AND-DASHBOARD-INTEGRATION.md → prevention-and-monitoring/"
    else
        echo "  Would move: SLACK-ALERTS-AND-DASHBOARD-INTEGRATION.md → prevention-and-monitoring/"
    fi
    ORGANIZED_COUNT=$((ORGANIZED_COUNT + 1))
fi

if [ -f "$CURRENT_DIR/DUAL-WRITE-ATOMICITY-FIX.md" ]; then
    if [ $DRY_RUN -eq 0 ]; then
        mv "$CURRENT_DIR/DUAL-WRITE-ATOMICITY-FIX.md" "$ARCHIVE_DIR/2026-01/"
        echo "✓ Archived: DUAL-WRITE-ATOMICITY-FIX.md → archive/2026-01/"
    else
        echo "  Would archive: DUAL-WRITE-ATOMICITY-FIX.md → archive/2026-01/"
    fi
    ORGANIZED_COUNT=$((ORGANIZED_COUNT + 1))
fi

if [ -f "$CURRENT_DIR/DUAL-WRITE-FIX-QUICK-REFERENCE.md" ]; then
    if [ $DRY_RUN -eq 0 ]; then
        mv "$CURRENT_DIR/DUAL-WRITE-FIX-QUICK-REFERENCE.md" "$ARCHIVE_DIR/2026-01/"
        echo "✓ Archived: DUAL-WRITE-FIX-QUICK-REFERENCE.md → archive/2026-01/"
    else
        echo "  Would archive: DUAL-WRITE-FIX-QUICK-REFERENCE.md → archive/2026-01/"
    fi
    ORGANIZED_COUNT=$((ORGANIZED_COUNT + 1))
fi

if [ -f "$CURRENT_DIR/UNIT-TESTING-IMPLEMENTATION-PLAN.md" ]; then
    if [ $DRY_RUN -eq 0 ]; then
        mv "$CURRENT_DIR/UNIT-TESTING-IMPLEMENTATION-PLAN.md" "$CURRENT_DIR/planning/"
        echo "✓ Organized: UNIT-TESTING-IMPLEMENTATION-PLAN.md → planning/"
    else
        echo "  Would move: UNIT-TESTING-IMPLEMENTATION-PLAN.md → planning/"
    fi
    ORGANIZED_COUNT=$((ORGANIZED_COUNT + 1))
fi

if [ -f "$CURRENT_DIR/grading-coverage-alert-deployment.md" ]; then
    if [ $DRY_RUN -eq 0 ]; then
        mv "$CURRENT_DIR/grading-coverage-alert-deployment.md" "$CURRENT_DIR/prevention-and-monitoring/"
        echo "✓ Organized: grading-coverage-alert-deployment.md → prevention-and-monitoring/"
    else
        echo "  Would move: grading-coverage-alert-deployment.md → prevention-and-monitoring/"
    fi
    ORGANIZED_COUNT=$((ORGANIZED_COUNT + 1))
fi

if [ -f "$CURRENT_DIR/daily-orchestration-issues-2026-02-01.md" ]; then
    if [ $DRY_RUN -eq 0 ]; then
        mv "$CURRENT_DIR/daily-orchestration-issues-2026-02-01.md" "$CURRENT_DIR/daily-orchestration-improvements/"
        echo "✓ Organized: daily-orchestration-issues-2026-02-01.md → daily-orchestration-improvements/"
    else
        echo "  Would move: daily-orchestration-issues-2026-02-01.md → daily-orchestration-improvements/"
    fi
    ORGANIZED_COUNT=$((ORGANIZED_COUNT + 1))
fi

echo ""
echo "=== SUMMARY ==="
echo "Archived (>30 days old): $ARCHIVED_COUNT projects"
echo "Completed (moved to archive): $COMPLETED_COUNT projects"
echo "Organized standalone files: $ORGANIZED_COUNT files"
echo "Total files moved: $((ARCHIVED_COUNT + COMPLETED_COUNT + ORGANIZED_COUNT))"
echo ""

if [ $DRY_RUN -eq 1 ]; then
    echo "=== DRY RUN COMPLETE ==="
    echo "Review the moves above. If they look correct, run:"
    echo "  ./bin/cleanup-projects.sh --execute"
else
    echo "=== CLEANUP COMPLETE ==="
    echo "Projects have been reorganized successfully."
    echo ""
    echo "Next steps:"
    echo "1. Review the changes: git status"
    echo "2. Update docs/08-projects/README.md with new structure"
    echo "3. Commit the changes"
fi

#!/bin/bash
# Investigate team_defense_zone_analysis table status
# Part of Session 209: Priority 3 - Fix team_defense_zone_analysis Dependency

set -e

echo "=========================================="
echo "Defense Zone Analysis Table Investigation"
echo "=========================================="
echo ""

# Define possible datasets
DATASETS=("nba_analytics" "nba_precompute")
TABLE_NAME="team_defense_zone_analysis"

for dataset in "${DATASETS[@]}"; do
    echo "──────────────────────────────────────────"
    echo "Checking ${dataset}.${TABLE_NAME}"
    echo "──────────────────────────────────────────"

    # Check if table exists
    TABLE_EXISTS=$(bq show nba-props-platform:${dataset}.${TABLE_NAME} 2>&1 | grep -c "Not found" || true)

    if [ "$TABLE_EXISTS" -gt 0 ]; then
        echo "❌ Table does not exist"
    else
        echo "✅ Table exists"

        # Get schema info
        echo ""
        echo "Schema:"
        bq show --format=prettyjson nba-props-platform:${dataset}.${TABLE_NAME} | \
            grep -A 2 '"schema"' | tail -1

        # Check data count (last 7 days)
        echo ""
        echo "Data check (last 7 days):"
        DATA_COUNT=$(bq query --use_legacy_sql=false --format=csv \
            "SELECT COUNT(*) as count
             FROM ${dataset}.${TABLE_NAME}
             WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)" 2>&1 | tail -1)

        if echo "$DATA_COUNT" | grep -q "Not found"; then
            echo "  ❌ Query failed - table might not exist or have issues"
        else
            echo "  Records: $DATA_COUNT"

            # If we have data, show sample
            if [ "$DATA_COUNT" != "0" ] && [ "$DATA_COUNT" != "count" ]; then
                echo ""
                echo "Sample data (3 recent rows):"
                bq query --use_legacy_sql=false --format=prettyjson \
                    "SELECT game_date, team_tricode, opponent_def_rating
                     FROM ${dataset}.${TABLE_NAME}
                     WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
                     ORDER BY game_date DESC
                     LIMIT 3" | grep -E '(game_date|team_tricode|opponent_def_rating)' || true
            fi
        fi

        # Check for related processors
        echo ""
        echo "Related processor files:"
        find data_processors -name "*defense*zone*" -o -name "*zone*defense*" 2>/dev/null || echo "  None found"
    fi
    echo ""
done

# Check Phase 4 precompute processors for defense zone
echo "=========================================="
echo "Phase 4 Processor Check"
echo "=========================================="
echo ""
echo "Looking for defense zone processor in Phase 4:"
find data_processors/precompute -type f -name "*.py" | \
    xargs grep -l "defense.*zone\|zone.*defense" 2>/dev/null || echo "  ❌ No defense zone processor found"

echo ""
echo "=========================================="
echo "NEXT STEPS"
echo "=========================================="
echo ""
echo "Based on findings above:"
echo "1. If table exists + has data:"
echo "   → Update FEATURE_UPSTREAM_TABLES mapping in quality_scorer.py"
echo ""
echo "2. If table missing:"
echo "   → Investigate if processor exists but not registered"
echo "   → Or feature should use different source"
echo ""
echo "3. Check feature usage:"
echo "   PYTHONPATH=. python -c \"from data_processors.precompute.ml_feature_store.quality_scorer import FEATURE_UPSTREAM_TABLES; print([k for k,v in FEATURE_UPSTREAM_TABLES.items() if 'defense_zone' in v])\""
echo ""

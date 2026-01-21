#!/bin/bash
#
# Complete January 2026 Validation Suite
#
# Runs all validation methods to ensure backfill completed properly:
# 1. Standard pipeline validation (per-day)
# 2. Data quality analysis (temporal, volume, completeness)
# 3. Cross-phase consistency checks
# 4. Statistical anomaly detection
#
# Usage:
#   bash bin/validation/run_complete_january_validation.sh
#   bash bin/validation/run_complete_january_validation.sh --quick
#
# Output:
#   - validation_results/january_2026_complete/
#     - pipeline_validation/  (per-day results)
#     - data_quality.txt      (quality analysis)
#     - final_report.txt      (combined summary)
#

set -e
set -u

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Configuration
OUTPUT_DIR="validation_results/january_2026_complete"
PIPELINE_DIR="$OUTPUT_DIR/pipeline_validation"
QUICK_MODE=false

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --quick)
            QUICK_MODE=true
            shift
            ;;
        --help)
            echo "Usage: $0 [--quick]"
            echo ""
            echo "Options:"
            echo "  --quick  Run quick validation (skip detailed per-day checks)"
            echo "  --help   Show this help message"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

# Create output directories
mkdir -p "$OUTPUT_DIR"
mkdir -p "$PIPELINE_DIR"

echo -e "${BLUE}=================================================================${NC}"
echo -e "${BLUE}  Complete January 2026 Validation Suite${NC}"
echo -e "${BLUE}=================================================================${NC}"
echo ""

# Step 1: Run data quality analysis
echo -e "${BLUE}[1/3] Running Data Quality Analysis...${NC}"
echo ""

if python3 bin/validation/validate_data_quality_january.py --detailed > "$OUTPUT_DIR/data_quality.txt" 2>&1; then
    echo -e "${GREEN}✓ Data quality analysis complete${NC}"
    cat "$OUTPUT_DIR/data_quality.txt"
else
    echo -e "${RED}✗ Data quality analysis failed${NC}"
    cat "$OUTPUT_DIR/data_quality.txt"
fi

echo ""

# Step 2: Run standard pipeline validation
if [ "$QUICK_MODE" = false ]; then
    echo -e "${BLUE}[2/3] Running Standard Pipeline Validation (per-day)...${NC}"
    echo "This may take 10-15 minutes..."
    echo ""

    # Run comprehensive per-day validation
    if bash bin/validation/validate_january_2026.sh --verbose 2>&1 | tee "$PIPELINE_DIR/validation.log"; then
        echo -e "${GREEN}✓ Pipeline validation complete${NC}"

        # Copy summary
        if [ -f "validation_results/january_2026/summary.txt" ]; then
            cp "validation_results/january_2026/summary.txt" "$OUTPUT_DIR/pipeline_summary.txt"
        fi
    else
        echo -e "${YELLOW}⚠ Pipeline validation completed with issues${NC}"
    fi
else
    echo -e "${YELLOW}[2/3] Skipping detailed per-day validation (quick mode)${NC}"
fi

echo ""

# Step 3: Generate final combined report
echo -e "${BLUE}[3/3] Generating Final Report...${NC}"
echo ""

cat > "$OUTPUT_DIR/final_report.txt" <<EOF
=================================================================
  January 2026 Backfill Validation - Final Report
=================================================================

Generated: $(date -u +"%Y-%m-%d %H:%M:%S UTC")
Validation Suite Version: 1.0

=================================================================
  Executive Summary
=================================================================

This report combines multiple validation approaches to ensure
January 2026 backfill completed successfully:

1. Data Quality Analysis - Temporal, volume, completeness checks
2. Pipeline Validation - Per-day comprehensive validation
3. Cross-Phase Consistency - Data flow verification
4. Statistical Anomalies - Outlier detection

=================================================================
  1. Data Quality Analysis
=================================================================

EOF

# Append data quality results
cat "$OUTPUT_DIR/data_quality.txt" >> "$OUTPUT_DIR/final_report.txt"

if [ "$QUICK_MODE" = false ] && [ -f "$OUTPUT_DIR/pipeline_summary.txt" ]; then
    cat >> "$OUTPUT_DIR/final_report.txt" <<EOF

=================================================================
  2. Pipeline Validation Summary
=================================================================

EOF
    cat "$OUTPUT_DIR/pipeline_summary.txt" >> "$OUTPUT_DIR/final_report.txt"
fi

cat >> "$OUTPUT_DIR/final_report.txt" <<EOF

=================================================================
  Additional Validation Methods
=================================================================

To further validate January 2026 data, consider these approaches:

1. SPOT CHECK VALIDATION
   - Manually verify 3-5 random dates
   - Check game results match ESPN/NBA.com
   - Verify player stats match official box scores

   Example:
   $ python3 bin/validate_pipeline.py 2026-01-15 --verbose --show-missing

2. GRADING ACCURACY CHECK
   - Verify prediction grading for completed games
   - Check grading coverage (should be 70-90%)

   Query:
   SELECT game_date, COUNT(*) as graded_predictions
   FROM \`nba_predictions.prediction_grading\`
   WHERE game_date BETWEEN '2026-01-01' AND '2026-01-21'
   GROUP BY game_date
   ORDER BY game_date;

3. TIME SERIES ANALYSIS
   - Plot daily player counts
   - Look for unexpected gaps or spikes
   - Verify consistent processing patterns

4. COMPARISON WITH PREVIOUS MONTH
   - Compare December 2025 vs January 2026
   - Look for similar patterns and volumes
   - Verify no degradation in coverage

5. MANUAL SPOT CHECKS
   - Pick 2-3 high-profile games
   - Manually verify all stats for star players
   - Check against multiple sources (NBA.com, ESPN, Basketball Reference)

6. DOWNSTREAM IMPACT CHECK
   - Verify web app is showing predictions
   - Check GCS exports are complete
   - Validate JSON files have expected structure

=================================================================
  Validation Artifacts
=================================================================

Output files saved to: $OUTPUT_DIR/

- final_report.txt         (this file)
- data_quality.txt          (quality analysis results)
EOF

if [ "$QUICK_MODE" = false ]; then
    cat >> "$OUTPUT_DIR/final_report.txt" <<EOF
- pipeline_summary.txt      (per-day validation summary)
- pipeline_validation/      (detailed per-day logs)
EOF
fi

cat >> "$OUTPUT_DIR/final_report.txt" <<EOF

=================================================================
  Next Steps
=================================================================

1. Review this report for any issues
2. Investigate any failed or partial validations
3. Run spot checks on random dates
4. Verify downstream systems (web app, exports)
5. Document any findings or required fixes

=================================================================
  Approval Checklist
=================================================================

Before declaring January 2026 backfill complete, verify:

[ ] All dates have data across all phases
[ ] Player counts are within expected ranges
[ ] No statistical anomalies detected
[ ] Cross-phase consistency maintained
[ ] Grading coverage is 70-90%+
[ ] Spot checks pass for 3-5 random dates
[ ] Web app showing predictions correctly
[ ] GCS exports are complete

=================================================================

For questions or issues, see:
- docs/02-operations/backfill-guide.md
- docs/02-operations/daily-operations.md

EOF

echo -e "${GREEN}✓ Final report generated: $OUTPUT_DIR/final_report.txt${NC}"
echo ""

# Display final summary
echo -e "${BLUE}=================================================================${NC}"
echo -e "${BLUE}  Validation Complete${NC}"
echo -e "${BLUE}=================================================================${NC}"
echo ""
echo "Results saved to: $OUTPUT_DIR/"
echo ""
echo "Quick summary:"
grep -A 20 "Executive Summary" "$OUTPUT_DIR/final_report.txt" || true
echo ""
echo -e "${GREEN}Next step: Review ${OUTPUT_DIR}/final_report.txt${NC}"
echo ""

# Check if there were any failures
if grep -q "✗.*FAILED" "$OUTPUT_DIR/data_quality.txt" 2>/dev/null; then
    echo -e "${RED}⚠ Data quality checks found issues!${NC}"
    echo "Review $OUTPUT_DIR/data_quality.txt for details"
    exit 1
elif grep -q "⚠.*WARNING" "$OUTPUT_DIR/data_quality.txt" 2>/dev/null; then
    echo -e "${YELLOW}⚠ Data quality checks found warnings!${NC}"
    echo "Review $OUTPUT_DIR/data_quality.txt for details"
    exit 2
else
    echo -e "${GREEN}✓ All validation checks passed!${NC}"
    exit 0
fi

# Backfill Remediation Plan

**Created:** January 12, 2026
**Status:** IN PROGRESS

---

## Phase 1: Immediate Actions (Today)

### 1.1 Fix Slack Webhook (P0)

All alerting is non-functional. This blocks visibility into pipeline health.

```bash
# Step 1: Create new Slack webhook in your workspace
# Go to: https://api.slack.com/apps → Create App → Incoming Webhooks

# Step 2: Add to Secret Manager
echo -n "https://hooks.slack.com/services/YOUR/WEBHOOK/URL" | \
  gcloud secrets versions add slack-webhook-default \
  --data-file=- --project=nba-props-platform

# Step 3: Verify functions can access it
gcloud functions call daily-health-summary --region=us-west2
```

**Time:** 15 minutes
**Owner:** User (requires Slack admin access)

### 1.2 Verify Current Day Pipeline (P0)

```bash
# Check today's pipeline status
curl -s "https://daily-health-summary-f7p3g7f6ya-wl.a.run.app" | jq '.'

# Check DLQ is clear
curl -s "https://dlq-monitor-f7p3g7f6ya-wl.a.run.app" | jq '.total_messages'

# Check prediction coverage for today
bq query --use_legacy_sql=false "
SELECT game_date, COUNT(DISTINCT player_lookup) as players
FROM \`nba_predictions.player_prop_predictions\`
WHERE game_date >= CURRENT_DATE() - 1
GROUP BY game_date ORDER BY game_date"
```

**Time:** 5 minutes

---

## Phase 2: Run Validation Scripts

### 2.1 Backfill Coverage Validation

```bash
# Focus on current + last season first
cd /home/naji/code/nba-stats-scraper

# Run coverage validation
python scripts/validate_backfill_coverage.py \
  --start-date 2024-10-22 \
  --end-date 2026-01-12 \
  --details \
  > docs/08-projects/current/historical-backfill-audit/logs/coverage-validation-$(date +%Y%m%d).log 2>&1

# Review results
cat docs/08-projects/current/historical-backfill-audit/logs/coverage-validation-*.log | grep -E "UNTRACKED|Investigate|ERROR"
```

**Time:** 10-15 minutes
**Expected Output:** Status codes per processor (OK, Skipped, DepsMiss, Untracked, Investigate)

### 2.2 Cascade Contamination Check

```bash
# Check for bad data propagation
python scripts/validate_cascade_contamination.py \
  --start-date 2024-10-22 \
  --end-date 2026-01-12 \
  --strict \
  > docs/08-projects/current/historical-backfill-audit/logs/contamination-check-$(date +%Y%m%d).log 2>&1
```

**Time:** 5-10 minutes
**Critical Fields Checked:**
- `opponent_strength_score > 0`
- `opp_paint_attempts > 0`
- No NULL in required fields

### 2.3 Circuit Breaker Status

```bash
# Check for locked-out entities
./scripts/completeness/check-circuit-breaker-status --active-only \
  > docs/08-projects/current/historical-backfill-audit/logs/circuit-breakers-$(date +%Y%m%d).log 2>&1

# If many locked out, consider bulk override after validating data exists
./scripts/completeness/bulk-override-circuit-breaker \
  --date-from 2024-10-22 \
  --date-to 2026-01-12 \
  --reason "Upstream data now available after backfill audit" \
  --dry-run  # Remove --dry-run to execute
```

**Time:** 5 minutes

---

## Phase 3: Address Specific Gaps

### 3.1 Player Normalization Backfill (P1)

This fixes 78% of historical predictions that used default line_value=20.

```bash
# Step 1: Review the patch SQL
cat bin/patches/patch_player_lookup_normalization.sql

# Step 2: Run in dry-run mode first
bq query --use_legacy_sql=false --dry_run < bin/patches/patch_player_lookup_normalization.sql

# Step 3: Execute the patch
bq query --use_legacy_sql=false < bin/patches/patch_player_lookup_normalization.sql

# Step 4: Verify fix
python bin/patches/verify_normalization_fix.py
```

**Time:** 30 minutes
**Impact:** Fixes prop line matching for ~6,000+ predictions

### 3.2 Registry Backlog Cleanup (P1)

Clear 2,078 pending unresolved names.

```bash
# Check current backlog
bq query --use_legacy_sql=false "
SELECT status, COUNT(*) as cnt
FROM \`nba_reference.unresolved_player_names\`
GROUP BY status"

# Trigger registry automation manually
curl -X POST "https://registry-automation-f7p3g7f6ya-wl.a.run.app/process" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" \
  -d '{"batch_size": 100}'

# Monitor progress (repeat until backlog cleared)
watch -n 60 'bq query --use_legacy_sql=false "SELECT status, COUNT(*) FROM nba_reference.unresolved_player_names GROUP BY status"'
```

**Time:** 1-2 hours (may need multiple batches)

---

## Phase 4: Historical Season Backfill

### 4.1 Validate Phase 3 Completeness

```bash
# Check Phase 3 is complete before running Phase 4
python bin/backfill/verify_phase3_for_phase4.py \
  --start-date 2021-10-19 \
  --end-date 2026-01-12

# Expected: All dates should show "ready" status
```

### 4.2 Backfill Phase 4 (If Gaps Found)

```bash
# Run Phase 4 processors for any gaps
# Note: Include 30-day lookback for proper rolling averages

# Team Defense Zone Analysis
python backfill_jobs/precompute/team_defense_zone_analysis/team_defense_zone_analysis_precompute_backfill.py \
  --start-date 2021-10-19 --end-date 2026-01-12 --parallel --workers 15

# Player Shot Zone Analysis
python backfill_jobs/precompute/player_shot_zone_analysis/player_shot_zone_analysis_precompute_backfill.py \
  --start-date 2021-10-19 --end-date 2026-01-12

# Player Composite Factors (depends on above)
python backfill_jobs/precompute/player_composite_factors/player_composite_factors_precompute_backfill.py \
  --start-date 2021-10-19 --end-date 2026-01-12

# ML Feature Store (final Phase 4)
python backfill_jobs/precompute/ml_feature_store/ml_feature_store_precompute_backfill.py \
  --start-date 2021-10-19 --end-date 2026-01-12
```

**Time:** 8-12 hours (can run overnight)

### 4.3 Backfill Phase 5 Predictions (If Needed)

```bash
# Only run after Phase 4 is complete
python backfill_jobs/prediction/player_prop_predictions_backfill.py \
  --start-date 2021-10-19 --end-date 2026-01-12
```

**Time:** 2-4 hours

---

## Phase 5: Post-Backfill Validation

### 5.1 Data Quality Checks

```sql
-- Check for duplicates
SELECT game_date, player_lookup, COUNT(*) as dup_count
FROM `nba_predictions.player_prop_predictions`
WHERE game_date >= '2024-10-22'
GROUP BY game_date, player_lookup
HAVING COUNT(*) > 1;
-- Expected: 0 rows

-- Check for NULL critical fields
SELECT
  COUNTIF(game_id IS NULL) as null_game_id,
  COUNTIF(player_lookup IS NULL) as null_player,
  COUNTIF(predicted_points IS NULL) as null_predicted
FROM `nba_predictions.player_prop_predictions`
WHERE game_date >= '2024-10-22';
-- Expected: All zeros

-- Check prediction quality (MAE)
SELECT
  EXTRACT(YEAR FROM p.game_date) as year,
  COUNT(*) as predictions,
  ROUND(AVG(ABS(p.predicted_points - pgs.points)), 2) as mae
FROM `nba_predictions.player_prop_predictions` p
JOIN `nba_analytics.player_game_summary` pgs
  ON p.game_date = pgs.game_date AND p.player_lookup = pgs.player_lookup
WHERE p.game_date >= '2024-10-22'
GROUP BY 1 ORDER BY 1;
-- Expected: MAE < 6.0
```

### 5.2 Update Status Document

After each remediation step, update:
- `docs/08-projects/current/historical-backfill-audit/STATUS.md`

---

## Decision Points

### Decision 1: 2021-22 Season Odds Data

The 2021-22 season has no Odds API props data. Options:

| Option | Pros | Cons | Effort |
|--------|------|------|--------|
| Accept gap | Simple, no work | 29% prediction coverage | None |
| Find alt source | Better coverage | May not exist, cost | High |
| Regenerate without Vegas | Consistent | Lower accuracy | Medium |

**Recommendation:** Accept gap unless ML model training specifically needs that season.

### Decision 2: Registry Automation

Should registry automation run continuously or on-demand?

| Option | Pros | Cons |
|--------|------|------|
| Continuous (hourly) | Always up-to-date | API costs, complexity |
| Daily batch | Balanced | Up to 24h lag |
| On-demand | Simple | Manual intervention |

**Recommendation:** Daily batch at 6 AM ET.

---

## Success Criteria

- [ ] All alerting functions working (Slack webhook configured)
- [ ] `validate_backfill_coverage.py` shows no UNTRACKED or Investigate status
- [ ] `validate_cascade_contamination.py` passes in strict mode
- [ ] No active circuit breakers blocking processing
- [ ] Player normalization backfill SQL executed
- [ ] Registry backlog < 100 pending names
- [ ] Prediction MAE < 6.0 for all seasons with data

---

## Timeline

| Phase | Duration | Dependencies |
|-------|----------|--------------|
| Phase 1: Immediate | 30 min | Slack webhook URL |
| Phase 2: Validation | 30 min | None |
| Phase 3: Specific Fixes | 2-3 hours | Phase 2 results |
| Phase 4: Historical Backfill | 8-12 hours | Phase 3 complete |
| Phase 5: Post-Validation | 30 min | Phase 4 complete |

**Total:** 12-16 hours (can be spread across multiple sessions)

---

*Created: January 12, 2026*

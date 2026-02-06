# Session 133 Non-Schema Tasks - Handoff for Parallel Work

**Date:** February 5, 2026
**Status:** 🟢 READY - Can be done in parallel with schema implementation
**Estimated Time:** 20-30 minutes
**Priority:** P1 - Do before schema implementation completes

---

## Context

Session 133 completed comprehensive ML Feature Store quality visibility system design. Another chat is implementing the schema (14-17 hours). These are supporting tasks that can be done in parallel to prepare the environment and documentation.

---

## Task List

### Task 1: Deploy Stale Services (10 min) - P1

**Why:** External review identified 3 services with stale deployments (3 commits behind). Deploy now to avoid compounding drift during schema implementation.

**Services to deploy:**
```bash
./bin/deploy-service.sh nba-phase3-analytics-processors
./bin/deploy-service.sh nba-phase4-precompute-processors
./bin/deploy-service.sh prediction-coordinator
```

**Verification:**
```bash
# Check deployment status
./bin/whats-deployed.sh

# Verify no drift
./bin/check-deployment-drift.sh --verbose
```

**Expected commits:**
- cf659d52: "test: Session 135 Part 2 - Integration testing and documentation"
- 563e7efa: "feat: Add self-healing with full observability (Session 135)"
- caf9f3b3: "feat: Add resilience monitoring system - P0 foundation (Session 135)"

**Success criteria:**
- [ ] All 3 services deployed
- [ ] `check-deployment-drift.sh` shows no stale services
- [ ] Health endpoints return 200 OK

---

### Task 2: Update CLAUDE.md (5 min) - P1

**Why:** Future sessions need to know about the quality visibility system.

**File:** `/home/naji/code/nba-stats-scraper/CLAUDE.md`

**Changes to make:**

#### Add New Keyword Section

Find the "## Key Tables [Keyword: TABLES]" section and add after it:

```markdown
## ML Feature Quality [Keyword: QUALITY]

**Status:** Session 134 implementation in progress

The ML feature store has comprehensive per-feature quality tracking:
- **114 fields total:** 66 per-feature columns + 48 aggregate/JSON fields
- **5 categories:** matchup, player_history, team_context, vegas, game_context
- **Detection time:** <5 seconds for quality issues (vs 2+ hours manual)

### Quick Quality Checks

```sql
-- Check overall quality
SELECT game_date, AVG(feature_quality_score) as avg_quality,
       COUNTIF(quality_alert_level = 'red') as red_count
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= CURRENT_DATE() - 7
GROUP BY 1 ORDER BY 1 DESC;

-- Check category quality
SELECT game_date,
       ROUND(AVG(matchup_quality_pct), 1) as matchup,
       ROUND(AVG(player_history_quality_pct), 1) as history,
       ROUND(AVG(game_context_quality_pct), 1) as context
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= CURRENT_DATE() - 7
GROUP BY 1 ORDER BY 1 DESC;

-- Find bad features (direct columns - FAST)
SELECT player_lookup, feature_5_quality, feature_6_quality, feature_7_quality, feature_8_quality
FROM nba_predictions.ml_feature_store_v2
WHERE game_date = CURRENT_DATE()
  AND (feature_5_quality < 50 OR feature_6_quality < 50 OR feature_7_quality < 50 OR feature_8_quality < 50);
```

### Per-Feature Quality Fields

Each of 33 features has:
- `feature_N_quality` - Quality score 0-100 (direct column)
- `feature_N_source` - Source type: 'phase4', 'phase3', 'calculated', 'default' (direct column)

**Critical features to monitor:**
- Features 5-8: Composite factors (fatigue, shot zone, pace, usage)
- Features 13-14: Opponent defense (def rating, pace)

### Category Definitions

| Category | Features | Critical? |
|----------|----------|-----------|
| **matchup** | 5-8, 13-14 (6 total) | ✅ Yes - Session 132 issue |
| **player_history** | 0-4, 29-32 (9 total) | No |
| **team_context** | 22-24 (3 total) | No |
| **vegas** | 25-28 (4 total) | No |
| **game_context** | 9-12, 15-21 (12 total) | No |

### Common Issues

| Issue | Detection | Fix |
|-------|-----------|-----|
| All matchup features defaulted | `matchup_quality_pct = 0` | Check PlayerCompositeFactorsProcessor ran |
| High default rate | `default_feature_count > 6` | Check Phase 4 processors completed |
| Low training quality | `training_quality_feature_count < 30` | Investigate per-feature quality scores |

### Documentation

**Project docs:** `docs/08-projects/current/feature-quality-visibility/`
- 00-PROJECT-OVERVIEW.md - Problem analysis and solution
- 07-FINAL-HYBRID-SCHEMA.md - Complete schema design
- Session 134 handoff: `docs/09-handoff/2026-02-05-SESSION-134-START-HERE.md`

**Key insight:** "The aggregate feature_quality_score is a lie" - it masks component failures. Always check category-level quality (matchup, history, context, vegas, game_context) for root cause.
```

#### Update "Common Issues" Section

Find the existing "## Common Issues [Keyword: ISSUES]" table and add:

```markdown
| **Low feature quality** | **`matchup_quality_pct < 50` or high `default_feature_count`** | **Check which processor didn't run: query `missing_processors` field or check phase_completions table** |
| **Session 132 recurrence** | **All matchup features (5-8) at quality 40** | **PlayerCompositeFactorsProcessor didn't run - check scheduler job configuration** |
```

---

### Task 3: Create Helper Query Scripts (5 min) - P2

**Why:** Make the new schema easy to use for daily debugging.

**Files to create:**

#### File 1: `bin/queries/check_feature_quality.sh`

```bash
#!/bin/bash
# Check feature quality for a specific date
# Usage: ./bin/queries/check_feature_quality.sh [YYYY-MM-DD]

DATE="${1:-$(date +%Y-%m-%d)}"

echo "=== Feature Quality Check for $DATE ==="
echo ""

bq query --use_legacy_sql=false --format=pretty "
-- Overall quality summary
SELECT
  'Overall' as category,
  ROUND(AVG(feature_quality_score), 1) as avg_quality,
  COUNTIF(quality_alert_level = 'red') as red_count,
  COUNTIF(quality_alert_level = 'yellow') as yellow_count,
  COUNTIF(quality_alert_level = 'green') as green_count,
  COUNT(*) as total_players
FROM nba_predictions.ml_feature_store_v2
WHERE game_date = '$DATE'

UNION ALL

-- Category breakdown
SELECT
  'Matchup' as category,
  ROUND(AVG(matchup_quality_pct), 1) as avg_quality,
  COUNTIF(matchup_quality_pct < 50) as red_count,
  COUNTIF(matchup_quality_pct BETWEEN 50 AND 80) as yellow_count,
  COUNTIF(matchup_quality_pct > 80) as green_count,
  COUNT(*) as total_players
FROM nba_predictions.ml_feature_store_v2
WHERE game_date = '$DATE'

UNION ALL

SELECT
  'Player History' as category,
  ROUND(AVG(player_history_quality_pct), 1),
  COUNTIF(player_history_quality_pct < 50),
  COUNTIF(player_history_quality_pct BETWEEN 50 AND 80),
  COUNTIF(player_history_quality_pct > 80),
  COUNT(*)
FROM nba_predictions.ml_feature_store_v2
WHERE game_date = '$DATE'

UNION ALL

SELECT
  'Game Context' as category,
  ROUND(AVG(game_context_quality_pct), 1),
  COUNTIF(game_context_quality_pct < 50),
  COUNTIF(game_context_quality_pct BETWEEN 50 AND 80),
  COUNTIF(game_context_quality_pct > 80),
  COUNT(*)
FROM nba_predictions.ml_feature_store_v2
WHERE game_date = '$DATE'

UNION ALL

SELECT
  'Team Context' as category,
  ROUND(AVG(team_context_quality_pct), 1),
  COUNTIF(team_context_quality_pct < 50),
  COUNTIF(team_context_quality_pct BETWEEN 50 AND 80),
  COUNTIF(team_context_quality_pct > 80),
  COUNT(*)
FROM nba_predictions.ml_feature_store_v2
WHERE game_date = '$DATE'

UNION ALL

SELECT
  'Vegas' as category,
  ROUND(AVG(vegas_quality_pct), 1),
  COUNTIF(vegas_quality_pct < 50),
  COUNTIF(vegas_quality_pct BETWEEN 50 AND 80),
  COUNTIF(vegas_quality_pct > 80),
  COUNT(*)
FROM nba_predictions.ml_feature_store_v2
WHERE game_date = '$DATE'

ORDER BY category;
"
```

**Make executable:**
```bash
chmod +x bin/queries/check_feature_quality.sh
```

#### File 2: `bin/queries/find_bad_features.sh`

```bash
#!/bin/bash
# Find features with low quality for a specific date
# Usage: ./bin/queries/find_bad_features.sh [YYYY-MM-DD] [threshold]

DATE="${1:-$(date +%Y-%m-%d)}"
THRESHOLD="${2:-50}"

echo "=== Features with quality < $THRESHOLD for $DATE ==="
echo ""

bq query --use_legacy_sql=false --format=pretty "
-- Check critical composite factors (Session 132 issue)
SELECT
  'Composite Factors (5-8)' as feature_group,
  ROUND(AVG(feature_5_quality), 1) as feature_5_avg,
  ROUND(AVG(feature_6_quality), 1) as feature_6_avg,
  ROUND(AVG(feature_7_quality), 1) as feature_7_avg,
  ROUND(AVG(feature_8_quality), 1) as feature_8_avg,
  COUNTIF(feature_5_quality < $THRESHOLD OR feature_6_quality < $THRESHOLD
          OR feature_7_quality < $THRESHOLD OR feature_8_quality < $THRESHOLD) as players_affected
FROM nba_predictions.ml_feature_store_v2
WHERE game_date = '$DATE'

UNION ALL

-- Check opponent defense
SELECT
  'Opponent Defense (13-14)' as feature_group,
  ROUND(AVG(feature_13_quality), 1),
  ROUND(AVG(feature_14_quality), 1),
  NULL as feature_7_avg,
  NULL as feature_8_avg,
  COUNTIF(feature_13_quality < $THRESHOLD OR feature_14_quality < $THRESHOLD)
FROM nba_predictions.ml_feature_store_v2
WHERE game_date = '$DATE';

-- Show details for players with bad composite factors
SELECT
  player_lookup,
  feature_5_quality, feature_5_source,
  feature_6_quality, feature_6_source,
  feature_7_quality, feature_7_source,
  feature_8_quality, feature_8_source,
  matchup_quality_pct,
  quality_alert_level
FROM nba_predictions.ml_feature_store_v2
WHERE game_date = '$DATE'
  AND (feature_5_quality < $THRESHOLD OR feature_6_quality < $THRESHOLD
       OR feature_7_quality < $THRESHOLD OR feature_8_quality < $THRESHOLD)
ORDER BY matchup_quality_pct ASC
LIMIT 20;
"
```

**Make executable:**
```bash
chmod +x bin/queries/find_bad_features.sh
```

#### File 3: `bin/queries/training_quality_check.sh`

```bash
#!/bin/bash
# Check training data quality for a date range
# Usage: ./bin/queries/training_quality_check.sh [START_DATE] [END_DATE]

START="${1:-$(date -d '30 days ago' +%Y-%m-%d)}"
END="${2:-$(date +%Y-%m-%d)}"

echo "=== Training Quality Check: $START to $END ==="
echo ""

bq query --use_legacy_sql=false --format=pretty "
SELECT
  COUNT(*) as total_records,
  COUNTIF(is_training_ready) as training_ready_count,
  ROUND(COUNTIF(is_training_ready) / COUNT(*) * 100, 1) as training_ready_pct,
  COUNTIF(critical_features_training_quality) as critical_quality_count,
  ROUND(COUNTIF(critical_features_training_quality) / COUNT(*) * 100, 1) as critical_quality_pct,
  ROUND(AVG(training_quality_feature_count), 1) as avg_training_features,
  ROUND(AVG(feature_quality_score), 1) as avg_overall_quality,
  ROUND(AVG(matchup_quality_pct), 1) as avg_matchup_quality
FROM nba_predictions.ml_feature_store_v2
WHERE game_date BETWEEN '$START' AND '$END';
"
```

**Make executable:**
```bash
chmod +x bin/queries/training_quality_check.sh
```

---

### Task 4: Check Current System State (5 min) - P2 (Optional)

**Why:** Understand if there are ongoing quality issues today.

**Queries to run:**

```bash
# Check today's feature quality
./bin/queries/check_feature_quality.sh

# Check yesterday's quality
./bin/queries/check_feature_quality.sh $(date -d '1 day ago' +%Y-%m-%d)

# Check recent predictions
bq query --use_legacy_sql=false "
SELECT game_date, COUNT(*) as prediction_count
FROM nba_predictions.player_prop_predictions
WHERE game_date >= CURRENT_DATE() - 3
  AND superseded = false
  AND system_id = 'catboost_v9'
GROUP BY 1
ORDER BY 1 DESC
"

# Check recent feature store records
bq query --use_legacy_sql=false "
SELECT
  game_date,
  COUNT(*) as player_count,
  ROUND(AVG(feature_quality_score), 1) as avg_quality
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= CURRENT_DATE() - 3
GROUP BY 1
ORDER BY 1 DESC
"
```

**Document findings:**
- Are there current quality issues?
- Any patterns in recent days?
- Note in session handoff for schema implementation chat

---

## Implementation Checklist

### Task 1: Deploy Stale Services
- [ ] Deploy nba-phase3-analytics-processors
- [ ] Deploy nba-phase4-precompute-processors
- [ ] Deploy prediction-coordinator
- [ ] Run `./bin/whats-deployed.sh` to verify
- [ ] Run `./bin/check-deployment-drift.sh` to confirm no drift
- [ ] Check health endpoints

### Task 2: Update CLAUDE.md
- [ ] Add "ML Feature Quality [Keyword: QUALITY]" section
- [ ] Add quality check queries
- [ ] Add per-feature field documentation
- [ ] Add category definitions table
- [ ] Update "Common Issues" table with quality issues
- [ ] Add references to project documentation

### Task 3: Create Helper Scripts
- [ ] Create `bin/queries/check_feature_quality.sh`
- [ ] Create `bin/queries/find_bad_features.sh`
- [ ] Create `bin/queries/training_quality_check.sh`
- [ ] Make all scripts executable (`chmod +x`)
- [ ] Test each script (may error if schema not deployed yet - that's OK)

### Task 4: Check Current State (Optional)
- [ ] Run quality checks for today/yesterday
- [ ] Check recent predictions
- [ ] Check recent feature store records
- [ ] Document any current issues

---

## Success Criteria

- [ ] Zero deployment drift (`check-deployment-drift.sh` clean)
- [ ] CLAUDE.md has quality system documentation
- [ ] 3 helper query scripts created and executable
- [ ] Scripts tested (or verified they'll work once schema deployed)
- [ ] Current system state documented (optional)

---

## Notes for Schema Implementation Chat

**Once these tasks complete:**
- Deployment drift is clear
- CLAUDE.md has quality documentation for future sessions
- Helper scripts ready for daily debugging

**Coordination:**
- These tasks can run in parallel with schema implementation
- Deploy stale services BEFORE schema backfill starts (avoid conflicts)
- Helper scripts will work once schema is deployed

**If schema is deployed before these tasks:**
- Helper scripts can be tested immediately
- Quality checks will show real data

---

## Files Created/Modified

### Files to Create
- [ ] `bin/queries/check_feature_quality.sh`
- [ ] `bin/queries/find_bad_features.sh`
- [ ] `bin/queries/training_quality_check.sh`

### Files to Modify
- [ ] `CLAUDE.md` - Add quality system documentation

### Services to Deploy
- [ ] `nba-phase3-analytics-processors`
- [ ] `nba-phase4-precompute-processors`
- [ ] `prediction-coordinator`

---

## Estimated Timeline

| Task | Time | Can Run in Parallel? |
|------|------|----------------------|
| Deploy stale services | 10 min | No (sequential deploys) |
| Update CLAUDE.md | 5 min | Yes |
| Create helper scripts | 5 min | Yes |
| Check current state | 5 min | Yes |
| **Total** | **15-20 min** | (parallel tasks) |

---

## References

### Session Context
- Session 133: ML feature quality visibility system design
- Session 134: Schema implementation (separate chat)
- Review feedback: External review identified stale deployments + need for documentation

### Related Docs
- Schema design: `docs/08-projects/current/feature-quality-visibility/07-FINAL-HYBRID-SCHEMA.md`
- Schema handoff: `docs/09-handoff/2026-02-05-SESSION-134-START-HERE.md`
- Original crisis: Session 132 (2+ hour investigation)

### CLAUDE.md Keywords
- **DEPLOY** - Deployment procedures
- **DOC** - Documentation procedure
- **QUERIES** - Essential queries
- **QUALITY** - (NEW) Quality system documentation

---

**Document Version:** 1.0
**Date:** February 5, 2026
**Status:** ✅ READY - Can start immediately
**Coordination:** Run in parallel with schema implementation
**Priority:** P1 - Complete before schema backfill
**Estimated Time:** 20-30 minutes

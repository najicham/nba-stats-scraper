# Backfill System Improvement Gameplan

**Date**: 2026-01-02
**Status**: 🎯 READY FOR EXECUTION
**Priority**: P0 (Critical) - System has architectural gaps causing data loss

---

## 🎯 TL;DR - What You Need to Know

**THE PROBLEM**: Your backfill system is broken. Event-driven orchestration (Pub/Sub) works great for today's games but completely fails for historical data.

**THE IMPACT**: 430 playoff games stuck in Phase 2, never processed through analytics/predictions.

**THE FIX**:
- **Week 1** (4-6 hrs): Fill all gaps manually
- **Week 2-3** (1-2 weeks): Build unified backfill orchestrator
- **Month 2** (2-4 weeks): Add query-driven auto-healing

**THE DECISION**:
- ✅ **ML work**: Can proceed now (regular season data sufficient)
- 🔴 **System health**: Must fix (prevents future silent data loss)

---

## 🚨 Critical Findings

### Root Cause: Event-Driven Architecture Breaks for Backfill

**Real-time pipeline** (✅ Works perfectly):
```
Game Today → Phase 1 scrapes → GCS file created → Pub/Sub event
→ Phase 2 processes → Pub/Sub event → Phase 3 triggered → Pub/Sub event
→ Phase 4 triggered → HTTP call → Phase 5 predictions run
```

**Backfill pipeline** (❌ Completely broken):
```
Historical game → Phase 1 data in GCS (already exists)
→ Phase 2 backfill script runs → NO Pub/Sub event published ❌
→ Phase 3 NEVER TRIGGERS ❌
→ Phase 4-6 NEVER RUN ❌
→ Data stuck in Phase 2 forever ❌
```

### Five Systematic Problems

1. **No unified backfill framework** - Must run 6+ scripts manually
2. **Backfill scripts don't trigger downstream** - Each phase isolated
3. **No validation between phases** - Can run Phase 4 when Phase 3 incomplete
4. **Event-driven, not query-driven** - Can't detect historical data that needs processing
5. **No automated gap detection** - Gaps accumulate silently for months

### Specific Gaps Identified

| Gap | Impact | Root Cause |
|-----|--------|-----------|
| 2021-24 playoffs missing from Phase 3-6 | 430 games stuck | Phase 3 never triggered after Phase 2 ran |
| 2024-25 grading incomplete | Only 1 test record vs 100k expected | Backfill scope didn't include this season |

---

## 📋 Master Todo List

### ✅ Analysis Complete (Today)

- [x] Deep investigation of backfill scripts
- [x] Root cause analysis of data gaps
- [x] Systematic problem identification
- [x] Recommendation development
- [x] Gameplan creation

### 🔴 P0: Fix Current Gaps (THIS WEEK - 4-6 hours)

**Goal**: Fill all 430 playoff games + 2024-25 grading gaps

#### Step 1: Phase 3 Analytics Backfill (2-3 hours)

```bash
cd /home/naji/code/nba-stats-scraper

# 2021-22 Playoffs
PYTHONPATH=. .venv/bin/python \
  backfill_jobs/analytics/player_game_summary/player_game_summary_analytics_backfill.py \
  --start-date 2022-04-16 --end-date 2022-06-17

# 2022-23 Playoffs
PYTHONPATH=. .venv/bin/python \
  backfill_jobs/analytics/player_game_summary/player_game_summary_analytics_backfill.py \
  --start-date 2023-04-15 --end-date 2023-06-13

# 2023-24 Playoffs
PYTHONPATH=. .venv/bin/python \
  backfill_jobs/analytics/player_game_summary/player_game_summary_analytics_backfill.py \
  --start-date 2024-04-16 --end-date 2024-06-18
```

**Validation**:
```sql
SELECT season_year, COUNT(DISTINCT game_code) as playoff_games
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE season_year IN (2021, 2022, 2023) AND game_date >= '2022-04-15'
GROUP BY season_year;
-- Expect: ~135-152 games per season
```

#### Step 2: Phase 4 Precompute Backfill (1-2 hours)

```bash
# After Phase 3 completes
./bin/backfill/run_phase4_backfill.sh \
  --start-date 2022-04-16 --end-date 2022-06-17

./bin/backfill/run_phase4_backfill.sh \
  --start-date 2023-04-15 --end-date 2023-06-13

./bin/backfill/run_phase4_backfill.sh \
  --start-date 2024-04-16 --end-date 2024-06-18
```

**Validation**:
```sql
SELECT COUNT(DISTINCT game_date) as playoff_dates
FROM `nba-props-platform.nba_precompute.player_composite_factors`
WHERE game_date >= '2022-04-15' AND game_date <= '2024-06-18';
-- Expect: ~90 dates
```

#### Step 3: Phase 5 Predictions Backfill (30 min - 1 hour)

```bash
# Get auth token
TOKEN=$(gcloud auth print-identity-token)

# Trigger for each playoff period
curl -X POST https://prediction-coordinator-f7p3g7f6ya-wl.a.run.app/start \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"start_date": "2022-04-16", "end_date": "2022-06-17"}'

curl -X POST https://prediction-coordinator-f7p3g7f6ya-wl.a.run.app/start \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"start_date": "2023-04-15", "end_date": "2023-06-13"}'

curl -X POST https://prediction-coordinator-f7p3g7f6ya-wl.a.run.app/start \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"start_date": "2024-04-16", "end_date": "2024-06-18"}'
```

#### Step 4: Grade 2024-25 Season (1 hour)

```bash
# Explore prediction backfill jobs to find grading script
ls -la backfill_jobs/prediction/

# Run grading backfill (exact script TBD)
# Expected: Something like this
PYTHONPATH=. .venv/bin/python \
  backfill_jobs/prediction/player_prop_predictions_backfill.py \
  --start-date 2024-10-22 --end-date 2025-04-30 --mode grade
```

**Validation**:
```sql
SELECT COUNT(*) as graded_predictions
FROM `nba-props-platform.nba_predictions.prediction_accuracy`
WHERE season_year = 2024;
-- Expect: ~100k-110k (currently only 1)
```

#### Step 5: Document Completion (15 min)

- [ ] Update `DATA-COMPLETENESS-2026-01-02.md` with new counts
- [ ] Create handoff doc for P0 completion
- [ ] Verify all gaps filled

**P0 COMPLETION CRITERIA**: All SQL validation queries return expected counts

---

### 🟡 P1: Unified Backfill Orchestrator (WEEKS 2-3 - 1-2 weeks)

**Goal**: Single command to backfill any date range through all phases

#### Tasks

- [ ] **Design**: Create architecture for `bin/backfill/run_full_backfill.sh`
  - Single entry point for all backfill operations
  - Takes: `--start-date`, `--end-date`, `--phases` (default: 2,3,4,5)
  - Runs phases in dependency order
  - Validates between phases

- [ ] **Build validation framework**:
  - `bin/backfill/validate_phase_complete.py`
  - Checks date range completeness for each phase
  - Returns: complete/incomplete with details

- [ ] **Create phase runners**:
  - `bin/backfill/runners/run_phase2.sh` - BDL + Gamebook + all Phase 2
  - `bin/backfill/runners/run_phase3.sh` - All analytics processors
  - `bin/backfill/runners/run_phase4.sh` - Already exists, integrate
  - `bin/backfill/runners/run_phase5.sh` - Prediction coordinator caller
  - `bin/backfill/runners/run_phase6.sh` - Export runner (if needed)

- [ ] **Add orchestration logic**:
  - Pre-flight checks before start
  - Validation gates between phases
  - Progress tracking and logging
  - Error handling and rollback
  - Resume capability (checkpoint state)

- [ ] **Testing**:
  - Test on small range (1 week)
  - Test on medium range (1 month)
  - Test on large range (full season)
  - Test resume after failure

- [ ] **Documentation**:
  - Create `docs/02-operations/backfill/unified-backfill-guide.md`
  - Update existing backfill guide
  - Add troubleshooting section

**P1 COMPLETION CRITERIA**:
```bash
# Single command backfills full season through all phases
./bin/backfill/run_full_backfill.sh \
  --start-date 2024-10-22 --end-date 2025-04-30 \
  --phases 2,3,4,5
# Result: All phases complete with validation
```

---

### 🟢 P2: Query-Driven Orchestration (MONTH 2 - 2-4 weeks)

**Goal**: Backfill data flows automatically without manual triggers

#### Tasks

- [ ] **Design query-driven mode**:
  - Add to existing Phase 2→3, 3→4, 4→5 orchestrators
  - Two trigger modes: Pub/Sub (real-time) + HTTP (backfill scan)
  - Cloud Scheduler triggers hourly gap scans

- [ ] **Implement gap detection queries**:
  ```python
  def find_gaps_phase2_to_phase3():
      """Find dates in Phase 2 but not Phase 3"""
      query = """
      WITH phase2 AS (
        SELECT DISTINCT game_date FROM `nba_raw.bdl_player_boxscores`
        WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 90 DAY)
      ),
      phase3 AS (
        SELECT DISTINCT game_date FROM `nba_analytics.player_game_summary`
        WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 90 DAY)
      )
      SELECT p2.game_date FROM phase2 p2
      LEFT JOIN phase3 p3 USING (game_date)
      WHERE p3.game_date IS NULL
      """
      return run_query(query)
  ```

- [ ] **Modify orchestrators**:
  - `orchestration/cloud_functions/phase2_to_phase3/main.py`
  - `orchestration/cloud_functions/phase3_to_phase4/main.py`
  - `orchestration/cloud_functions/phase4_to_phase5/main.py`
  - Add `/scan-gaps` endpoint to each
  - Trigger downstream phases for detected gaps

- [ ] **Add Cloud Scheduler jobs**:
  ```bash
  gcloud scheduler jobs create http phase3-gap-scanner \
    --schedule="0 */1 * * *" \
    --uri="https://phase2-to-phase3-orch.run.app/scan-gaps" \
    --http-method=POST
  ```

- [ ] **Testing**:
  - Create test gap (backfill Phase 2, skip Phase 3)
  - Verify gap detected within 1 hour
  - Verify Phase 3 triggered automatically
  - Verify cascade to Phase 4-5

- [ ] **Monitoring**:
  - Log all gap detections
  - Alert if gap > 30 days old
  - Track gap healing metrics

**P2 COMPLETION CRITERIA**: Backfill Phase 2 for a date, Phase 3-5 trigger automatically within 1 hour

---

### 🔵 P3: Self-Healing Gap Detection (QUARTER 1 - 1-2 weeks)

**Goal**: Zero silent gaps, automatic healing, alerts only on anomalies

#### Tasks

- [ ] **Create gap detection service**:
  - `services/gap_detector/main.py` (Cloud Run)
  - Runs daily via Cloud Scheduler
  - Scans all phase pairs (2→3, 3→4, 4→5, 5→6)

- [ ] **Implement healing logic**:
  - Recent gaps (<30 days): Auto-trigger backfill
  - Old gaps (>30 days): Alert for investigation
  - Track healing success/failure

- [ ] **Create gap tracking table**:
  ```sql
  CREATE TABLE nba_orchestration.data_gaps (
    detected_at TIMESTAMP,
    phase_from INT64,
    phase_to INT64,
    game_date DATE,
    gap_age_days INT64,
    healing_status STRING,  -- pending/triggered/complete/failed
    healed_at TIMESTAMP
  );
  ```

- [ ] **Build gap dashboard**:
  - BigQuery view: Current gaps by phase
  - Looker dashboard: Gap trends over time
  - Alerts: Slack/email for old gaps

- [ ] **Deploy and monitor**:
  - Deploy to Cloud Run
  - Set up daily scheduler
  - Monitor for 2 weeks
  - Tune thresholds

**P3 COMPLETION CRITERIA**:
- Zero gaps > 24 hours old
- All recent gaps auto-healed
- Alerts only for anomalies

---

## 🎯 Decision Framework

### Should You Do This?

**For ML Work**:
- ❌ **Not blocking**: 3,000+ regular season games sufficient for training
- ✅ **Nice to have**: 430 playoff games adds valuable data
- ⏸️ **Can defer**: Focus on ML first, backfill later

**For System Health**:
- 🔴 **Critical**: Silent data loss is unacceptable
- 🔴 **Will recur**: Every future backfill will have same problem
- 🔴 **Technical debt**: Gets worse over time
- ✅ **Must fix**: Before it causes bigger problems

**For Data Completeness**:
- ✅ **You have raw data**: Already paid scraping cost
- ✅ **Low effort to fill**: 4-6 hours for all gaps
- ✅ **High value**: Playoffs are important
- ✅ **Future-proof**: If you want playoff predictions later

### Recommended Priority

**Option A: Fix Everything (Recommended)**
- Week 1: P0 (fix gaps)
- Weeks 2-3: P1 (unified orchestrator)
- Month 2: P2 (query-driven)
- Quarter 1: P3 (gap detection)
- **Total**: ~6 weeks, complete solution

**Option B: ML First, Fix Later**
- Week 1-4: Focus on ML evaluation/training
- Month 2: Come back to P0-P1
- Month 3: P2-P3
- **Risk**: More gaps accumulate during ML work

**Option C: Minimum Fix Only**
- Week 1: P0 only (fix gaps)
- Defer P1-P3 indefinitely
- **Risk**: Manual backfill forever, gaps will recur

**My Recommendation**: **Option A** - Fix it right, fix it once. The ROI is clear:
- Investment: 6 weeks
- Savings: 4-6 hrs/backfill × 12 backfills/year = 48-72 hrs/year
- Risk reduction: Prevents production data quality issues
- Payback: 1-2 quarters

---

## 📊 Success Metrics

### How to Measure Progress

**After P0** (Fix Gaps):
- ✅ 0 known data gaps in BigQuery
- ✅ Playoffs available for ML training
- ✅ 2024-25 grading complete (100k+ records)
- ❌ Still requires manual backfill process

**After P1** (Unified Orchestrator):
- ✅ Single command backfills any date range
- ✅ Automatic validation prevents bad data
- ✅ 50% time reduction (2-3 hrs vs 4-6 hrs per backfill)
- ✅ 90% reduction in human error
- ❌ Still requires manual trigger

**After P2** (Query-Driven):
- ✅ Backfill data flows automatically within 1 hour
- ✅ No manual script execution needed
- ✅ Works for both real-time and historical
- ❌ Still requires proactive backfill runs

**After P3** (Self-Healing):
- ✅ Zero gaps accumulate silently
- ✅ All gaps detected within 24 hours
- ✅ Recent gaps auto-healed
- ✅ Only anomalies require human intervention
- ✅ **FULLY AUTOMATED PIPELINE**

---

## 🚀 Getting Started

### This Week - P0 Execution

**Monday** (2-3 hours):
1. Run Phase 3 backfill for all 3 playoff periods
2. Validate Phase 3 completion

**Tuesday** (1-2 hours):
1. Run Phase 4 backfill for all playoff periods
2. Validate Phase 4 completion

**Wednesday** (1 hour):
1. Trigger Phase 5 predictions for playoffs
2. Run 2024-25 grading backfill

**Thursday** (1 hour):
1. Validate all gaps filled
2. Document completion
3. Update ML project docs with new data availability

**Friday** (Planning):
1. Review P0 completion
2. Decide: Continue to P1 or focus on ML?
3. Plan P1 if proceeding

### Want to Start? Run This:

```bash
# Step 1: Verify you have the backfill scripts
ls -la /home/naji/code/nba-stats-scraper/backfill_jobs/analytics/player_game_summary/
ls -la /home/naji/code/nba-stats-scraper/bin/backfill/

# Step 2: Check Phase 2 data exists for playoffs
bq query --use_legacy_sql=false "
SELECT COUNT(*) as playoff_games
FROM \`nba-props-platform.nba_raw.bdl_player_boxscores\`
WHERE game_date >= '2022-04-15' AND game_date <= '2024-06-18'"
# Expect: ~430 games

# Step 3: Verify Phase 3 gap
bq query --use_legacy_sql=false "
SELECT COUNT(*) as playoff_games
FROM \`nba-props-platform.nba_analytics.player_game_summary\`
WHERE game_date >= '2022-04-15' AND game_date <= '2024-06-18'"
# Expect: ~0 (this is the gap)

# Step 4: Run first backfill (2021-22 playoffs)
cd /home/naji/code/nba-stats-scraper
PYTHONPATH=. .venv/bin/python \
  backfill_jobs/analytics/player_game_summary/player_game_summary_analytics_backfill.py \
  --start-date 2022-04-16 --end-date 2022-06-17

# Step 5: Validate it worked
bq query --use_legacy_sql=false "
SELECT COUNT(DISTINCT game_code) as playoff_games
FROM \`nba-props-platform.nba_analytics.player_game_summary\`
WHERE season_year = 2021 AND game_date >= '2022-04-16'"
# Expect: ~135 games
```

---

## 📁 Documentation Map

**Created Today**:
- `ROOT-CAUSE-ANALYSIS.md` - Deep dive into all 5 systematic problems
- `GAMEPLAN.md` ← YOU ARE HERE - Execution plan with todos

**Next to Create** (after P0):
- `P0-COMPLETION-REPORT.md` - What was backfilled, validation results
- `unified-backfill-guide.md` - How to use new orchestrator (after P1)

**Existing References**:
- `docs/02-operations/backfill/backfill-guide.md` - Current manual process
- `docs/09-handoff/2026-01-02-SESSION-HANDOFF-ML-READY.md` - ML readiness context
- `docs/08-projects/current/four-season-backfill/DATA-COMPLETENESS-2026-01-02.md` - Gap details

---

## 🏁 Next Steps

**Right Now** - Choose your path:

**Path 1: Fix Backfill System First** (Recommended)
```bash
# Start P0 today
cd /home/naji/code/nba-stats-scraper
PYTHONPATH=. .venv/bin/python \
  backfill_jobs/analytics/player_game_summary/player_game_summary_analytics_backfill.py \
  --start-date 2022-04-16 --end-date 2022-06-17
```

**Path 2: ML Work First, Backfill Later**
```bash
# Jump to ML evaluation
# Use: docs/08-projects/current/ml-model-development/02-EVALUATION-PLAN.md
bq query --use_legacy_sql=false < evaluation_query_1.sql
```

**Path 3: Quick Win - Just Fill Gaps**
```bash
# Run P0 this week (4-6 hours)
# Defer P1-P3 to future
# Result: Complete data, but manual process remains
```

**What's your call?**

I recommend Path 1: Fix it right, fix it once. But if you want to jump into ML work immediately (Path 2), the regular season data is solid and ready to use.

Let me know which path you want to take! 🚀

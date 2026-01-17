# MLB Two-Table System Investigation
**Date**: 2026-01-17
**Investigator**: Claude Sonnet 4.5
**Context**: Session 80 continuation - Understanding existing database architecture

---

## 🔍 Investigation Summary

Investigated the MLB prediction database architecture to understand:
1. Why two tables exist (`pitcher_strikeouts` vs `pitcher_strikeout_predictions`)
2. Which table is actively used
3. Why predictions appear to have stopped in September 2025
4. How the existing system relates to Session 80's multi-model architecture implementation

---

## 📊 Key Findings

### Table 1: `pitcher_strikeouts` (ACTIVE)
**Purpose**: Production predictions from worker.py
**Status**: ✅ ACTIVE - Contains real data
**Row Count**: 16,666 predictions
**Date Range**: 2024-04-09 to 2025-09-28
**Schema**: Simple (23 columns)
- Single prediction per row
- Fields: `predicted_strikeouts`, `confidence`, `model_version`, `recommendation`, `edge`
- Uses `pitcher_lookup` for player ID
- Partitioned by `game_date`
- Clustered by `pitcher_lookup`, `team_abbr`

**Model Versions Found**:
1. `mlb_pitcher_strikeouts_v1_20260107` - 8,130 predictions
2. `mlb_pitcher_strikeouts_v1_6_rolling_20260115_131149` - 8,536 predictions

### Table 2: `pitcher_strikeout_predictions` (UNUSED)
**Purpose**: Designed for multi-model architecture
**Status**: ❌ EMPTY - Never used
**Row Count**: 0
**Schema**: Comprehensive (42 columns)
- Separate columns for each model: `ma_prediction`, `sim_prediction`, `xgb_prediction`, `ensemble_prediction`
- Each with separate confidence scores
- Rich feature tracking: `k_avg_last_5`, `season_k_per_9`, `opponent_k_rate`, etc.
- Uses `player_lookup` instead of `pitcher_lookup`
- Partitioned by `game_date`
- Clustered by `player_lookup`, `team_abbr`, `season_year`

### Table 3: `shadow_mode_predictions` (TESTING)
**Purpose**: A/B testing V1.4 vs V1.6
**Status**: ✅ ACTIVE - Used for shadow mode testing
**Written By**: `shadow_mode_runner.py`
**Schema**: Comparison-focused
- Side-by-side V1.4 and V1.6 predictions
- Prediction diff, agreement tracking
- Offline evaluation only

---

## 🎯 Critical Discovery: The "Multi-Model" Pattern Was a Backfill

### What It Looked Like
When querying `pitcher_strikeouts` for recent dates, I saw:
```sql
SELECT * FROM pitcher_strikeouts WHERE game_date = '2025-09-28';
-- Result: Each pitcher had 2 rows (V1 and V1.6)
```

This looked like a live multi-model system running!

### What Actually Happened
```sql
SELECT game_date, DATE(created_at) as written_on, model_version
FROM pitcher_strikeouts
WHERE game_date = '2025-09-28';

+------------+------------+-----------------------------------------------------+
| game_date  | written_on | model_version                                        |
+------------+------------+-----------------------------------------------------+
| 2025-09-28 | 2026-01-16 | mlb_pitcher_strikeouts_v1_6_rolling_20260115_131149  |
| 2025-09-28 | 2026-01-09 | mlb_pitcher_strikeouts_v1_20260107                   |
+------------+------------+-----------------------------------------------------+
```

**The Truth**:
- **Jan 9, 2026**: ALL V1 predictions backfilled (8,130 rows covering Apr 2024 - Sep 2025)
- **Jan 16, 2026**: ALL V1.6 predictions backfilled (8,536 rows covering same period)
- These were **two separate backfill runs**, not concurrent multi-model predictions
- The worker.py is still single-model only

---

## 📅 Timeline of Events

### 2024-04-09 to 2025-09-28
- MLB season games occurred
- NO PREDICTIONS were made in real-time
- Data was collected but predictions were generated later

### 2026-01-09 (V1 Backfill Day)
- V1 model: `mlb_pitcher_strikeouts_v1_20260107`
- Backfilled all historical predictions using V1.4 features
- 8,130 predictions written
- Covered entire 2024 season retroactively

### 2026-01-15 (V1.6 Deployment)
- Commit `d0a83fa`: "Deploy V1.6 pitcher strikeouts model with shadow mode infrastructure"
- V1.6 became the new champion model (60.2% win rate vs V1.4)
- Added shadow mode testing infrastructure
- Model: `mlb_pitcher_strikeouts_v1_6_rolling_20260115_131149`

### 2026-01-16 (V1.6 Backfill Day)
- V1.6 model backfilled same historical period
- 8,536 predictions written
- Allows direct comparison: V1 vs V1.6 on same games

### 2026-01-17 (Today - Session 80)
- Implemented multi-model architecture from scratch
- Assumed we were building something new
- Actually implementing what should have been the production system all along

---

## 🤔 Why Predictions Stopped in September 2025

**Answer**: They didn't stop - **they never started in real-time**

The system has been in "development mode":
1. Data collection happens (game logs, pitcher stats, etc.)
2. Models are trained and improved
3. Predictions are backfilled for validation
4. No real-time production predictions yet

The worker.py exists but is not currently deployed to run on game days.

---

## 🏗️ Architectural Analysis

### Current State
```
Data Collection → Storage → Model Training → Backfill Testing
                                                    ↓
                                         shadow_mode_predictions
                                         pitcher_strikeouts (backfilled)
```

### Session 80 Implementation (What We Built)
```
Game Day → worker.py → Multiple Systems → BigQuery
                       ├─ V1 Baseline
                       ├─ V1.6 Rolling
                       └─ Ensemble V1
                                ↓
                       pitcher_strikeouts (with system_id)
```

### What Should Happen
```
1. Deploy Session 80 worker.py to Cloud Run
2. Schedule daily predictions via Cloud Scheduler
3. Run all 3 systems concurrently
4. Write to pitcher_strikeouts with system_id field
5. Monitor using the 5 views we created
```

---

## 💡 Key Insights

### 1. Session 80 Work Is Still Needed
- The multi-model architecture we built is **not redundant**
- It's actually the missing piece to go from backfill mode to production
- The fancy `pitcher_strikeout_predictions` table was someone's design doc but never implemented

### 2. Two Backfills ≠ Multi-Model System
- Having V1 and V1.6 in the same table doesn't mean they ran concurrently
- It just means they were both backfilled for comparison
- Real multi-model = same game_date, created_at timestamp

### 3. Migration Strategy Clarity
- **Target Table**: `pitcher_strikeouts` (the active one)
- **Add Column**: `system_id` (new field for multi-model)
- **Keep Column**: `model_version` (for backward compatibility)
- **Ignore Table**: `pitcher_strikeout_predictions` (abandoned design)

### 4. Why There's No Recent Data
- Not a system failure
- Not a data pipeline issue
- Simply: Real-time predictions haven't been deployed yet
- We're building the system to enable that

---

## ✅ Updated Todo List

Based on these findings:

1. ✅ Understand two-table system (COMPLETE)
2. ✅ Determine migration target (COMPLETE: `pitcher_strikeouts`)
3. 🔲 Run BigQuery migration to add `system_id` to `pitcher_strikeouts`
4. 🔲 Deploy Session 80 worker to Cloud Run
5. 🔲 Set up Cloud Scheduler for daily predictions
6. 🔲 Test with upcoming MLB games (when season starts)
7. 🔲 Monitor using the 5 BigQuery views
8. 🔲 Compare ensemble vs V1.6 performance over 30 days
9. 🔲 Consider: Migrate old backfilled data to include `system_id`?
   - V1 predictions → `system_id = 'v1_baseline'`
   - V1.6 predictions → `system_id = 'v1_6_rolling'`

---

## 🚨 Important Notes

### About `pitcher_strikeout_predictions`
- **Do NOT migrate this table**
- It was a design idea that never got implemented
- Focus on `pitcher_strikeouts` only
- We could delete it or leave it as a future option

### About Historical Data
- The 16,666 existing predictions are valuable for training
- They show V1 vs V1.6 performance on real games
- We should backfill `system_id` values so our monitoring views work
- This is optional but recommended

### About Going Live
- Session 80 implementation is ready
- Need to deploy worker to Cloud Run
- MLB season starts in ~2 months (April 2026)
- Perfect time to test before season begins

---

## 📝 Recommendations

### Immediate (Next Session)
1. Run migration to add `system_id` column to `pitcher_strikeouts`
2. Backfill historical data with `system_id` values
3. Create the 5 monitoring views
4. Test worker locally with mock data

### Short-term (This Week)
1. Deploy worker to Cloud Run (staging)
2. Set up Cloud Scheduler (disabled, ready to enable)
3. Document deployment process
4. Create runbook for when MLB season starts

### Long-term (Before Season)
1. Test on spring training games
2. Validate ensemble performs better than individual systems
3. Set up alerting (Slack/email when predictions fail)
4. Create dashboard for daily prediction summary

---

## 🎓 Lessons Learned

1. **Always check created_at timestamps** when analyzing data patterns
2. **Backfills can look like real-time systems** if you only check game_date
3. **Empty tables in production** often mean abandoned designs
4. **Multiple model versions** don't necessarily mean multi-model architecture
5. **Historical validation** (backfills) is different from production deployment

---

## Next Steps

The Session 80 implementation is exactly what's needed. Proceed with:
1. Migration to add `system_id`
2. Deploy worker to Cloud Run
3. Set up scheduling for when MLB season resumes

No major changes needed - the architecture we built is correct for the real production use case.

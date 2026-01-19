# Next Session - Immediate Priorities (NOW)

**Created:** 2026-01-18 10:30 PM PST
**Context:** Post Session 110 - Ensemble V1.1 Deployed
**Estimated Time:** 2-3 hours for all tasks
**Priority:** HIGH - These are blocking issues or quick wins

---

## 🚨 PRIORITY 1: Deploy Session 107 Metrics (45-60 minutes)

### Background
**CRITICAL FINDING:** Session 107 handoff documentation says "✅ COMPLETE - All Features Deployed" but BigQuery schema verification shows the metrics were NEVER deployed to production.

**Missing Metrics:**
- 5 Variance Metrics (opponent_ft_rate_variance, opponent_def_rating_variance, opponent_off_rating_variance, opponent_rebounding_rate_variance, opponent_pace_variance)
- 2 Enhanced Star Tracking (questionable_star_teammates, star_tier_out)
- Plus Session 104 metrics: opponent_rebounding_rate, opponent_off_rating_last_10

**Impact:** Models cannot use 6+ valuable features that were implemented and tested but never deployed.

### Steps Required

**1. Verify Code Exists (5 minutes)**
```bash
# Check if Session 107 code exists in analytics processor
grep -n "opponent_ft_rate_variance" \
  data_processors/analytics/upcoming_player_game_context/upcoming_player_game_context_processor.py

grep -n "questionable_star_teammates" \
  data_processors/analytics/upcoming_player_game_context/upcoming_player_game_context_processor.py
```

**Expected:** Should find methods around lines 2952-3340 based on Session 107 handoff

**2. Check Git History (5 minutes)**
```bash
# Find Session 107 commits
git log --oneline --grep="Session 107\|variance\|star.*tier" --all

# Check if code was committed but not deployed
git show <commit-hash>
```

**3. Deploy Analytics Processor (20-30 minutes)**

If code exists:
```bash
# Deploy from data_processors/analytics/upcoming_player_game_context/
gcloud run deploy nba-phase3-analytics-processors \
  --source . \
  --region us-west2 \
  --project nba-props-platform \
  --timeout=600 \
  --memory=2Gi \
  --cpu=2
```

**Note:** May need to check correct service name and deployment script from previous sessions.

**4. Run Analytics Processor for Recent Games (10 minutes)**

Trigger processing for recent games to populate new fields:
```bash
# Check coordinator or trigger mechanism
# May need to call Cloud Scheduler or run manually for Jan 17-18
```

**5. Verify Fields Populate (10 minutes)**
```sql
-- Check schema updated
SELECT column_name, data_type
FROM `nba-props-platform.nba_analytics.INFORMATION_SCHEMA.COLUMNS`
WHERE table_name = 'upcoming_player_game_context'
  AND column_name LIKE '%variance%' OR column_name LIKE '%star_tier%' OR column_name LIKE '%questionable%'
ORDER BY column_name;

-- Check data population
SELECT
  game_date,
  COUNT(*) as total_records,
  COUNTIF(opponent_ft_rate_variance IS NOT NULL) as ft_var_populated,
  COUNTIF(opponent_def_rating_variance IS NOT NULL) as def_var_populated,
  COUNTIF(opponent_off_rating_variance IS NOT NULL) as off_var_populated,
  COUNTIF(opponent_rebounding_rate_variance IS NOT NULL) as reb_var_populated,
  COUNTIF(questionable_star_teammates IS NOT NULL) as questionable_populated,
  COUNTIF(star_tier_out IS NOT NULL) as tier_populated,
  ROUND(COUNTIF(opponent_ft_rate_variance IS NOT NULL) * 100.0 / COUNT(*), 1) as variance_pct
FROM `nba-props-platform.nba_analytics.upcoming_player_game_context`
WHERE game_date >= '2026-01-17'
GROUP BY game_date
ORDER BY game_date DESC;
```

**Success Criteria:**
- ✅ All 6+ fields exist in schema
- ✅ Data population > 90% for recent games
- ✅ Values are reasonable (not all NULL or 0)

---

## ⚡ PRIORITY 2: Verify Ensemble V1.1 Predictions (15 minutes)

### Background
Ensemble V1.1 deployed successfully (revision 00072-cz2) but need to verify it's actually generating predictions and writing to BigQuery with correct model_version.

### Verification Steps

**1. Check Service is Generating Predictions**
```bash
# Check prediction worker logs for ensemble_v1_1
gcloud run services logs read prediction-worker \
  --region=us-west2 \
  --project=nba-props-platform \
  --limit=100 | grep -i "ensemble_v1_1"
```

**2. Query BigQuery for Ensemble V1.1 Predictions**
```sql
-- Check if ensemble_v1_1 predictions exist
SELECT
  system_id,
  model_version,
  COUNT(*) as predictions,
  MIN(created_at) as first_prediction,
  MAX(created_at) as latest_prediction
FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE system_id = 'ensemble_v1_1'
  AND created_at >= '2026-01-18T22:00:00'  -- After deployment (10 PM PST)
GROUP BY system_id, model_version;
```

**3. Verify Model Version is Set**
```sql
-- Check model_version is not NULL
SELECT
  system_id,
  model_version,
  COUNT(*) as predictions,
  COUNTIF(model_version IS NULL) as null_count,
  COUNTIF(model_version IS NOT NULL) as non_null_count
FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE system_id = 'ensemble_v1_1'
  AND created_at >= '2026-01-18T22:00:00'
GROUP BY system_id, model_version;
```

**4. Spot Check Prediction Quality**
```sql
-- Get sample predictions to verify metadata
SELECT
  player_lookup,
  game_date,
  predicted_points,
  confidence,
  recommendation,
  model_version,
  feature_importance  -- Should contain weights_used
FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE system_id = 'ensemble_v1_1'
  AND created_at >= '2026-01-18T22:00:00'
LIMIT 5;
```

**Success Criteria:**
- ✅ Predictions exist for ensemble_v1_1
- ✅ model_version = 'ensemble_v1_1' (not NULL)
- ✅ feature_importance contains weights_used metadata
- ✅ Predictions have reasonable values (not all 0 or errors)

---

## 🚀 PRIORITY 3: Forward-Looking Schedule Metrics (45-60 minutes)

### Background
These 4 metrics enable predictions based on upcoming schedule density and opponent strength. Data is available in `bdl_schedule` table.

**Metrics to Implement:**
1. `next_game_days_rest` - Days between current game and next game
2. `games_in_next_7_days` - Upcoming games in next week
3. `next_opponent_win_pct` - Win percentage of next opponent
4. `next_game_is_primetime` - Is next game nationally televised

### Implementation Location
File: `data_processors/analytics/upcoming_player_game_context/upcoming_player_game_context_processor.py`

### Method Templates

**1. next_game_days_rest**
```python
def _get_next_game_days_rest(self, team_abbr: str, current_game_date: date) -> Optional[int]:
    """Get days of rest after current game before next game."""
    try:
        query = f"""
        SELECT MIN(game_date) as next_game_date
        FROM `{self.project_id}.nba_raw.nbac_schedule`
        WHERE (home_team_tricode = '{team_abbr}' OR away_team_tricode = '{team_abbr}')
          AND game_date > '{current_game_date}'
          AND game_date >= '2024-10-01'
        """
        result = self.bq_client.query(query).result()
        for row in result:
            if row.next_game_date:
                return (row.next_game_date - current_game_date).days
        return None
    except Exception as e:
        logger.error(f"Error getting next game days rest: {e}")
        return None
```

**2. games_in_next_7_days**
```python
def _get_games_in_next_7_days(self, team_abbr: str, current_game_date: date) -> int:
    """Get count of games in next 7 days after current game."""
    try:
        query = f"""
        SELECT COUNT(*) as game_count
        FROM `{self.project_id}.nba_raw.nbac_schedule`
        WHERE (home_team_tricode = '{team_abbr}' OR away_team_tricode = '{team_abbr}')
          AND game_date > '{current_game_date}'
          AND game_date <= DATE_ADD('{current_game_date}', INTERVAL 7 DAY)
        """
        result = self.bq_client.query(query).result()
        for row in result:
            return row.game_count or 0
        return 0
    except Exception as e:
        logger.error(f"Error getting games in next 7 days: {e}")
        return 0
```

**3. next_opponent_win_pct**
```python
def _get_next_opponent_win_pct(self, team_abbr: str, current_game_date: date) -> Optional[float]:
    """Get win percentage of team's next opponent."""
    try:
        # First get next opponent
        query = f"""
        WITH next_game AS (
            SELECT
                CASE
                    WHEN home_team_tricode = '{team_abbr}' THEN away_team_tricode
                    ELSE home_team_tricode
                END as opponent,
                game_date
            FROM `{self.project_id}.nba_raw.nbac_schedule`
            WHERE (home_team_tricode = '{team_abbr}' OR away_team_tricode = '{team_abbr}')
              AND game_date > '{current_game_date}'
            ORDER BY game_date ASC
            LIMIT 1
        )
        SELECT s.win_percentage
        FROM next_game ng
        JOIN `{self.project_id}.nba_raw.bdl_standings` s
          ON s.team_abbr = ng.opponent
          AND s.date_recorded = ng.game_date
        """
        result = self.bq_client.query(query).result()
        for row in result:
            return round(row.win_percentage, 3) if row.win_percentage else None
        return None
    except Exception as e:
        logger.error(f"Error getting next opponent win pct: {e}")
        return None
```

**4. next_game_is_primetime**
```python
def _get_next_game_is_primetime(self, team_abbr: str, current_game_date: date) -> Optional[bool]:
    """Check if next game is primetime/nationally televised."""
    try:
        query = f"""
        SELECT
            COALESCE(is_primetime, FALSE) as is_primetime,
            COALESCE(has_national_tv, FALSE) as has_national_tv
        FROM `{self.project_id}.nba_raw.nbac_schedule`
        WHERE (home_team_tricode = '{team_abbr}' OR away_team_tricode = '{team_abbr}')
          AND game_date > '{current_game_date}'
        ORDER BY game_date ASC
        LIMIT 1
        """
        result = self.bq_client.query(query).result()
        for row in result:
            return row.is_primetime or row.has_national_tv
        return None
    except Exception as e:
        logger.error(f"Error getting next game primetime status: {e}")
        return None
```

### Integration Steps

1. Add method calls in `_calculate_player_context()` around line 2260
2. Add fields to context dict around line 2360
3. Create unit tests (4 tests per metric = 16 tests)
4. Deploy analytics processor
5. Verify fields populate

**Success Criteria:**
- ✅ All 4 methods implemented
- ✅ Fields added to context dict
- ✅ Unit tests pass (16 new tests)
- ✅ Deployed to production
- ✅ Data populates in BigQuery

---

## 📋 Quick Task Checklist

Use this for tracking during the session:

- [ ] **Session 107 Metrics**
  - [ ] Verify code exists in processor
  - [ ] Deploy analytics processor
  - [ ] Run for recent games
  - [ ] Verify schema updated
  - [ ] Verify data populated (>90%)

- [ ] **Ensemble V1.1 Verification**
  - [ ] Check service logs
  - [ ] Query for predictions
  - [ ] Verify model_version not NULL
  - [ ] Spot check prediction quality

- [ ] **Forward-Looking Metrics** (if time)
  - [ ] Implement 4 methods
  - [ ] Add to context dict
  - [ ] Write unit tests
  - [ ] Deploy
  - [ ] Verify

---

## 📊 Expected Outcomes

**After Session:**
- ✅ Session 107 gap closed (6+ new fields in production)
- ✅ Ensemble V1.1 verified working correctly
- ✅ Potentially +4 schedule metrics (if time allows)
- ✅ All deployments verified in BigQuery

**Time Budget:**
- Session 107: 45-60 min
- Ensemble V1.1 verification: 15 min
- Forward-looking metrics: 45-60 min
- **Total:** ~2-2.5 hours

---

## 🔗 Reference Documents

- Session 110 Handoff: `docs/09-handoff/SESSION-110-ENSEMBLE-V1.1-AND-COMPREHENSIVE-TODOS.md`
- Session 107 Handoff: `docs/09-handoff/SESSION-107-VARIANCE-AND-STAR-TRACKING.md`
- Analytics Processor: `data_processors/analytics/upcoming_player_game_context/upcoming_player_game_context_processor.py`
- Performance Analysis Guide: `docs/08-projects/current/ml-model-v8-deployment/PERFORMANCE-ANALYSIS-GUIDE.md`

---

**Start Here:** Deploy Session 107 metrics - it's the highest priority finding from Session 110.

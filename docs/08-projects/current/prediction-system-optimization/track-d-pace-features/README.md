# Track D: Team Pace Feature Implementation

**Status:** 📋 Planned
**Priority:** MEDIUM
**Estimated Time:** 3-4 hours
**Target Completion:** 2026-01-22

---

## 🎯 Objective

Implement 3 missing team pace metrics in the analytics processor to improve prediction quality across all 6 models by providing tempo context.

---

## 📊 Features to Implement

### 1. pace_differential
**Description:** Team pace vs opponent pace (last 10 games)
**Type:** float
**Range:** -5.0 to +5.0 (typical)
**Interpretation:**
- Positive: Team plays faster than opponent
- Negative: Team plays slower than opponent
- Impact: Affects total possessions → scoring opportunities

### 2. opponent_pace_last_10
**Description:** Opponent's average pace over last 10 games
**Type:** float
**Range:** 95-105 (typical NBA pace)
**Interpretation:**
- >100: Fast-paced team
- <100: Slow-paced team
- Directly affects prediction environment

### 3. opponent_ft_rate_allowed
**Description:** Opponent's defensive FT rate allowed (FTA per game, last 10)
**Type:** float
**Range:** 15-25 (typical)
**Interpretation:**
- Higher: Defense allows more FT attempts
- Lower: Defense limits FT attempts
- Important for players who draw fouls

---

## 📋 Implementation Guide

### Quick Start
**See detailed guide:** [Session 103 Handoff](../../../../09-handoff/SESSION-103-TEAM-PACE-HANDOFF.md)

The Session 103 handoff document provides:
- ✅ Step-by-step implementation instructions
- ✅ Complete code templates
- ✅ BigQuery test queries
- ✅ Validation checklist
- ✅ Deployment guide

---

## 🗂️ Data Sources

### Team Offense Summary
**Table:** `nba-props-platform.nba_analytics.team_offense_game_summary`
**Rows:** 3,840 (2024-25 season)
**Key Fields:**
- `pace` - Possessions per 48 minutes
- `offensive_rating` - Points per 100 possessions
- `team_abbr` - Team abbreviation
- `game_date` - Game date

**Status:** ✅ Data available and validated

### Team Defense Summary
**Table:** `nba-props-platform.nba_analytics.team_defense_game_summary`
**Rows:** 3,848 (2024-25 season)
**Key Fields:**
- `defensive_rating` - Points allowed per 100 possessions
- `opponent_pace` - Opponent's pace
- `opp_ft_attempts` - FT attempts allowed
- `team_abbr` - Team abbreviation
- `game_date` - Game date

**Status:** ✅ Data available and validated

---

## 🚀 Implementation Steps

### Step 1: Locate Stub Functions (5 mins)
```bash
cd /home/naji/code/nba-stats-scraper
grep -n "pace_differential\|opponent_pace_last_10\|opponent_ft_rate_allowed" \
  data_processors/analytics/upcoming_player_game_context/upcoming_player_game_context_processor.py
```

### Step 2: Implement Functions (1.5 hours)
- `_calculate_pace_differential()` - 30 mins
- `_get_opponent_pace_last_10()` - 20 mins
- `_get_opponent_ft_rate_allowed()` - 30 mins

### Step 3: Wire Up Features (15 mins)
Connect functions to feature extraction pipeline

### Step 4: Test Locally (30 mins)
- Run unit tests
- Manual BigQuery verification
- Check value ranges

### Step 5: Deploy (15 mins)
```bash
./bin/analytics/deploy/deploy_analytics_processors.sh
```

### Step 6: Validate Production (30 mins)
Verify features populate correctly in production

### Step 7: Document & Commit (10 mins)
Git commit with clear message

---

## 📈 Success Criteria

### Implementation Complete When:
- ✅ All 3 functions implemented
- ✅ Functions wired into feature extraction
- ✅ Unit tests passing
- ✅ BigQuery verification shows valid data
- ✅ 0% NULL values in production
- ✅ Values within expected ranges
- ✅ Code committed with clear message

### Quality Gates:
- `pace_differential`: Values between -10 and +10
- `opponent_pace_last_10`: Values between 90 and 110
- `opponent_ft_rate_allowed`: Values between 10 and 30
- No BigQuery timeout errors
- Error handling works correctly

---

## 💡 Code Templates

### Template: pace_differential
```python
def _calculate_pace_differential(self, team_abbr: str, opponent_abbr: str, game_date: str) -> float:
    """Calculate difference between team's pace and opponent's pace (last 10 games)."""
    try:
        query = f"""
        WITH team_pace AS (
            SELECT AVG(pace) as avg_pace
            FROM `nba-props-platform.nba_analytics.team_offense_game_summary`
            WHERE team_abbr = '{team_abbr}'
              AND game_date < '{game_date}'
            ORDER BY game_date DESC
            LIMIT 10
        ),
        opponent_pace AS (
            SELECT AVG(pace) as avg_pace
            FROM `nba-props-platform.nba_analytics.team_offense_game_summary`
            WHERE team_abbr = '{opponent_abbr}'
              AND game_date < '{game_date}'
            ORDER BY game_date DESC
            LIMIT 10
        )
        SELECT
            ROUND(t.avg_pace - o.avg_pace, 2) as pace_diff
        FROM team_pace t, opponent_pace o
        """

        result = self.bq_client.query(query).result()
        for row in result:
            return row.pace_diff if row.pace_diff is not None else 0.0

        logger.warning(f"No pace data found for {team_abbr} vs {opponent_abbr}")
        return 0.0

    except Exception as e:
        logger.error(f"Error calculating pace differential: {e}")
        return 0.0
```

**See Session 103 handoff for complete templates of all 3 functions.**

---

## 🧪 Testing Strategy

### Unit Tests
```bash
pytest tests/processors/analytics/upcoming_player_game_context/test_unit.py -v -k pace
```

### Integration Test
```sql
-- Verify features populate in production
SELECT
    player_lookup,
    team_abbr,
    opponent_abbr,
    pace_differential,
    opponent_pace_last_10,
    opponent_ft_rate_allowed,
    game_date
FROM `nba-props-platform.nba_analytics.upcoming_player_game_context`
WHERE game_date >= CURRENT_DATE()
LIMIT 20;
```

### Validation Checks
```sql
-- Check for NULL values (should be 0)
SELECT
    COUNTIF(pace_differential IS NULL) as null_pace_diff,
    COUNTIF(opponent_pace_last_10 IS NULL) as null_opp_pace,
    COUNTIF(opponent_ft_rate_allowed IS NULL) as null_ft_rate
FROM `nba-props-platform.nba_analytics.upcoming_player_game_context`
WHERE game_date >= CURRENT_DATE();

-- Check value ranges
SELECT
    MIN(pace_differential) as min_pace_diff,
    MAX(pace_differential) as max_pace_diff,
    MIN(opponent_pace_last_10) as min_opp_pace,
    MAX(opponent_pace_last_10) as max_opp_pace,
    MIN(opponent_ft_rate_allowed) as min_ft_rate,
    MAX(opponent_ft_rate_allowed) as max_ft_rate
FROM `nba-props-platform.nba_analytics.upcoming_player_game_context`
WHERE game_date >= CURRENT_DATE();
```

---

## 🎯 Expected Impact

### Model Improvements
These features provide **tempo context** that helps models understand:
1. **Game pace** - Fast vs slow games affect total scoring
2. **Matchup dynamics** - How team pace matches opponent pace
3. **FT opportunities** - Defensive foul rates affect scoring potential

### Performance Boost Estimate
- **XGBoost V1:** +1-2% (pace features have low importance ~1-2%)
- **CatBoost V8:** +1-2% (similar importance)
- **Ensemble:** +1-3% (compounds across models)
- **Overall:** Small but meaningful improvement in prediction quality

### Feature Importance Prediction
Based on CatBoost V8 analysis:
- `opponent_pace_last_10`: 0.8-1.2% importance
- `pace_differential`: 0.5-0.8% importance
- `opponent_ft_rate_allowed`: 0.3-0.5% importance

---

## 📝 Deliverables

- [ ] Implementation in `upcoming_player_game_context_processor.py`
- [ ] Unit tests updated and passing
- [ ] `validation-results.md` - BigQuery validation results
- [ ] `deployment-log.md` - Deployment notes
- [ ] Git commit with comprehensive message
- [ ] Updated PROGRESS-LOG.md

---

## 🔗 Related Documentation

- **Primary Guide:** [Session 103 Handoff](../../../../09-handoff/SESSION-103-TEAM-PACE-HANDOFF.md)
- **Processor Code:** `data_processors/analytics/upcoming_player_game_context/upcoming_player_game_context_processor.py`
- **Tests:** `tests/processors/analytics/upcoming_player_game_context/test_unit.py`
- **Master Plan:** [../MASTER-PLAN.md](../MASTER-PLAN.md)

---

## 🚨 Troubleshooting

### Issue: BigQuery queries timeout
**Solution:** Add query timeout and consider caching
```python
job_config = bigquery.QueryJobConfig(default_dataset=f"{self.project_id}.nba_analytics")
result = self.bq_client.query(query, job_config=job_config).result(timeout=60)
```

### Issue: No data for some teams
**Solution:** Add fallback to league average
```python
if not result or row.avg_pace is None:
    logger.warning(f"No recent pace data for {team_abbr}, using league average")
    return 100.0  # League average pace
```

### Issue: Unit tests fail
**Solution:**
1. Check test fixtures have required fields
2. Update test expectations for new features
3. Add mocks for BigQuery queries if needed

---

## 📅 Timeline

| Phase | Duration | Description |
|-------|----------|-------------|
| Setup | 15 mins | Review handoff, locate code |
| Implementation | 1.5 hours | Code all 3 functions |
| Testing | 30 mins | Unit tests + validation |
| Deployment | 15 mins | Deploy to analytics processor |
| Validation | 30 mins | Verify production data |
| Documentation | 15 mins | Commit and document |
| **Total** | **3-4 hours** | **Complete feature implementation** |

---

**Track Owner:** Engineering Team
**Created:** 2026-01-18
**Status:** Ready to Start
**Next Step:** Review Session 103 handoff for detailed implementation guide

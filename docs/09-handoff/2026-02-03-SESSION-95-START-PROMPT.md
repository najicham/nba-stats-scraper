# Session 95 Start Prompt

Copy everything below this line into a new Claude Code chat:

---

## Task: Design & Implement Prediction Quality System

### Context

Session 94 discovered that our top 3 high-edge picks on Feb 2 all MISSED because they had **missing BDB shot zone data**. The model predicted conservatively (low points), creating artificially high "edges" that looked like good bets but weren't.

**Read the full handoff first:**
```bash
cat docs/09-handoff/2026-02-03-SESSION-94-HANDOFF.md
```

### Key Problem

```
Player             Quality   Predicted  Line   Actual  Result
Trey Murphy III    82.73%    11.1       22.5   27      MISS
Jaren Jackson Jr   82.73%    13.8       22.5   30      MISS
Jabari Smith Jr    82.73%    9.4        17.5   19      MISS
Zion Williamson    87.59%    21.0       23.5   14      HIT
```

The 82.73% quality players had MISSING shot zone features. The 87.59% player had complete data.

### Your Tasks

#### 1. Design Prediction Timing Strategy

Current schedule creates predictions too late (4:38 PM instead of 5 AM). Review and decide:

- When should first prediction attempt run?
- Should early predictions require real betting lines or allow estimated?
- How many retry attempts before proceeding with incomplete data?

**Check current schedules:**
```bash
gcloud scheduler jobs list --location=us-west2 | grep -E "predict|phase6"
```

#### 2. Design Missing Data Handling

User requirement: "Only force prediction with low quality features if it is the last try"

For each data type, decide:
- **Betting lines missing**: Pause or proceed with estimated?
- **BDB shot zones missing**: Pause or proceed?
- **B2B player missing previous game BDB**: This is CRITICAL for fatigue - how to handle?
- **Opponent stats missing**: Pause or proceed?

Should missing data:
- Just alert (Slack)?
- Auto-trigger the relevant scraper?
- Auto-trigger + schedule retry?

#### 3. Ensure Predictions Store Features Used

Currently predictions and features are in separate tables joined by player_lookup + game_date. We need:

- Store `feature_quality_score` directly on prediction
- Store `low_quality_reason` if applicable
- Store `b2b_missing_bdb` flag
- Consider: Do we need prediction versioning/history?

**Check current schema:**
```bash
bq show --schema nba_predictions.player_prop_predictions | head -50
bq show --schema nba_predictions.ml_feature_store_v2 | head -30
```

#### 4. Implement Your Design

After deciding on the above, implement changes in:
- `predictions/coordinator/coordinator.py` - Retry logic, quality gates
- `predictions/coordinator/player_loader.py` - B2B quality checks
- Schema changes if needed

#### 5. Deploy Changes

Session 94 committed but didn't deploy:
- `all_subsets_picks_exporter.py` with 85% quality filter

Deploy this plus any new changes.

### Reference Documentation

```bash
# Session 94 findings
cat docs/08-projects/current/prediction-quality-system/README.md

# Smart retry design (draft)
cat docs/08-projects/current/prediction-quality-system/SMART-RETRY-DESIGN.md

# Research on coordinator code
# See Session 94 handoff for detailed code analysis
```

### Verification Queries

```bash
# Check prediction timing history
bq query --use_legacy_sql=false "
SELECT game_date,
  FORMAT_TIMESTAMP('%H:%M', MIN(created_at), 'America/New_York') as first_et,
  COUNT(*) as predictions
FROM nba_predictions.player_prop_predictions
WHERE game_date >= CURRENT_DATE() - 7
  AND system_id = 'catboost_v9' AND is_active = TRUE
GROUP BY 1 ORDER BY 1 DESC"

# Check feature quality distribution today
bq query --use_legacy_sql=false "
SELECT
  CASE WHEN feature_quality_score >= 85 THEN 'High'
       WHEN feature_quality_score >= 80 THEN 'Medium'
       ELSE 'Low' END as tier,
  COUNT(*) as players
FROM nba_predictions.ml_feature_store_v2
WHERE game_date = CURRENT_DATE()
GROUP BY 1"
```

### Success Criteria

1. Predictions run early enough for 11 AM export to have picks
2. Low-quality predictions are flagged and excluded from top picks
3. B2B players without previous game BDB data are handled specially
4. Missing data triggers alerts (and optionally scrapers)
5. Predictions store quality score and flags for transparency

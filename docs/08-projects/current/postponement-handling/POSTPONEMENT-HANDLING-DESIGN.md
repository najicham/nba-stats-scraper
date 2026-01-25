# Postponed Game Handling - Design Document

**Created:** 2026-01-25
**Trigger:** GSW@MIN postponed due to shooting incident in Minneapolis
**Status:** Design Phase

---

## Problem Statement

On 2026-01-24, the GSW@MIN game was postponed ~2 hours before tip-off due to a federal agent shooting in Minneapolis. Our system:

1. **Made predictions for a game that didn't happen** (486 predictions for 7 games, only 6 played)
2. **Didn't detect the postponement** despite having news articles about it
3. **Has corrupted schedule data** - old record shows "Final" with NULL scores
4. **Has no mechanism to cascade updates** when the game is rescheduled

---

## Current State Analysis

### What We Have

| Data Source | Status | Gap |
|-------------|--------|-----|
| **Schedule** | Shows game_id 0022500644 twice (Jan 24 "Final", Jan 25 "Scheduled") | No "Postponed" status, old record not updated |
| **News** | 10+ articles about postponement captured at 20:00 UTC | Not parsed for schedule impact |
| **Predictions** | 486 predictions made for Jan 24 including GSW players | Will be graded as "no actual" |
| **Boxscores** | 0 records for GSW@MIN | Correct - game didn't happen |
| **Analytics** | 0 records for GSW/MIN players on Jan 24 | Correct - no data to process |

### Detection Signals We Missed

1. **"Final" status with NULL scores** - Should NEVER happen for completed games
2. **News articles mentioning "postpone"** - Clear signal we captured but didn't act on
3. **Boxscore scraper returning 0 records** for a "Final" game - Red flag
4. **Schedule showing same game_id on two dates** - Indicates reschedule

---

## Proposed Solution Architecture

### Phase 1: Detection (Automated Alerts)

#### 1.1 Schedule Anomaly Detection

```python
# In daily health check or real-time monitor
def detect_schedule_anomalies(game_date):
    anomalies = []

    # Check for "Final" with NULL scores
    query = """
    SELECT game_id, home_team_tricode, away_team_tricode
    FROM nba_raw.nbac_schedule
    WHERE game_date = @date
      AND game_status = 3  -- Final
      AND (home_team_score IS NULL OR away_team_score IS NULL)
    """
    final_no_score = run_query(query, date=game_date)
    if final_no_score:
        anomalies.append({
            'type': 'FINAL_WITHOUT_SCORE',
            'severity': 'CRITICAL',
            'games': final_no_score,
            'action': 'Investigate - likely postponed or data corruption'
        })

    # Check for duplicate game_ids across dates
    query = """
    SELECT game_id, ARRAY_AGG(DISTINCT game_date) as dates
    FROM nba_raw.nbac_schedule
    WHERE game_date >= DATE_SUB(@date, INTERVAL 7 DAY)
    GROUP BY game_id
    HAVING COUNT(DISTINCT game_date) > 1
    """
    rescheduled = run_query(query, date=game_date)
    if rescheduled:
        anomalies.append({
            'type': 'GAME_RESCHEDULED',
            'severity': 'HIGH',
            'games': rescheduled,
            'action': 'Update predictions and downstream data'
        })

    return anomalies
```

#### 1.2 News-Based Detection

```python
# Parse news for schedule-impacting events
POSTPONEMENT_KEYWORDS = [
    'postpone', 'postponed', 'postponement',
    'cancel', 'cancelled', 'rescheduled',
    'delay', 'delayed', 'moved to'
]

def scan_news_for_schedule_changes(since_timestamp):
    query = """
    SELECT article_id, title, summary, published_at
    FROM nba_raw.news_articles_raw
    WHERE published_at >= @since
      AND (
        REGEXP_CONTAINS(LOWER(title), r'postpone|cancel|reschedule|delay')
        OR REGEXP_CONTAINS(LOWER(summary), r'game.*postpone|postpone.*game')
      )
    """
    return run_query(query, since=since_timestamp)
```

#### 1.3 Cross-Source Validation

```python
def validate_game_completion(game_date):
    """
    Cross-validate that 'Final' games have data in all expected places.
    """
    query = """
    WITH schedule AS (
        SELECT game_id, game_status
        FROM nba_raw.nbac_schedule
        WHERE game_date = @date AND game_status = 3
    ),
    boxscores AS (
        SELECT DISTINCT game_id FROM nba_raw.bdl_player_boxscores
        WHERE game_date = @date
    ),
    gamebook AS (
        SELECT DISTINCT game_id FROM nba_raw.nbac_gamebook_player_stats
        WHERE game_date = @date
    )
    SELECT
        s.game_id,
        s.game_status,
        b.game_id IS NOT NULL as has_bdl,
        g.game_id IS NOT NULL as has_gamebook
    FROM schedule s
    LEFT JOIN boxscores b ON s.game_id = b.game_id
    LEFT JOIN gamebook g ON s.game_id = g.game_id
    WHERE b.game_id IS NULL AND g.game_id IS NULL
    """
    # Games marked Final but no data = likely postponed
    return run_query(query, date=game_date)
```

### Phase 2: Data Model Changes

#### 2.1 Schedule Table Enhancement

```sql
-- Add columns to track postponements
ALTER TABLE nba_raw.nbac_schedule ADD COLUMN IF NOT EXISTS
    original_game_date DATE,
    postponement_reason STRING,
    rescheduled_from_game_id STRING,
    schedule_status STRING DEFAULT 'active';  -- active, postponed, cancelled
```

#### 2.2 Postponement Tracking Table

```sql
CREATE TABLE IF NOT EXISTS nba_orchestration.game_postponements (
    postponement_id STRING DEFAULT GENERATE_UUID(),
    game_id STRING NOT NULL,
    original_date DATE NOT NULL,
    new_date DATE,  -- NULL if cancelled
    reason STRING,
    detected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP(),
    detection_source STRING,  -- 'news', 'schedule_anomaly', 'manual'
    news_article_ids ARRAY<STRING>,  -- Links to news articles
    predictions_invalidated INT64 DEFAULT 0,
    status STRING DEFAULT 'detected',  -- detected, confirmed, resolved
    resolved_at TIMESTAMP,
    PRIMARY KEY (game_id, original_date) NOT ENFORCED
)
PARTITION BY DATE(detected_at);
```

#### 2.3 Prediction Status Enhancement

```sql
-- Add invalidation tracking to predictions
ALTER TABLE nba_predictions.player_prop_predictions ADD COLUMN IF NOT EXISTS
    invalidation_reason STRING,  -- 'postponed', 'cancelled', 'player_inactive'
    invalidated_at TIMESTAMP;
```

### Phase 3: Workflow Changes

#### 3.1 When Postponement is Detected

```
1. ALERT: Send notification (Slack/email)
2. UPDATE: Mark predictions as invalidated
   - Set invalidation_reason = 'game_postponed'
   - Set invalidated_at = CURRENT_TIMESTAMP()
3. LOG: Create record in game_postponements table
4. UPDATE: Fix schedule record (set status to postponed, not Final)
5. SKIP: Don't attempt to grade these predictions
```

#### 3.2 When Rescheduled Game is Played

```
1. DETECT: Game now has boxscore data
2. VALIDATE: Confirm it's the rescheduled game (same game_id)
3. RUN: Full data pipeline cascade:
   - Phase 1: Boxscore scraping (already done)
   - Phase 2: Raw data processing
   - Phase 3: Analytics processing
   - Phase 4: Feature computation
   - Phase 5: New predictions (for future games)
   - Phase 6: Grading (for the game that just completed)
4. UPDATE: Mark postponement as resolved
5. COMPARE: If predictions were made for new date, grade them
```

#### 3.3 Handling Predictions for Rescheduled Games

```
Scenario A: Predictions made for original date only
- Mark as invalidated (postponed)
- Don't grade
- Generate new predictions for new date

Scenario B: Predictions made for both dates
- Invalidate original date predictions
- Keep and grade new date predictions

Scenario C: No predictions for either date (game too far out)
- No action needed until game approaches
```

### Phase 4: Implementation Priority

#### P0 - Critical (Do Now)

1. **Add anomaly detection to daily health check**
   - "Final" with NULL scores
   - Duplicate game_ids across dates

2. **Add news parsing for postponements**
   - Scan news on game days
   - Alert on postponement keywords

3. **Fix current data**
   - Update Jan 24 GSW@MIN schedule record
   - Invalidate predictions made for Jan 24 GSW players

#### P1 - High (This Week)

4. **Create game_postponements table**
5. **Add invalidation columns to predictions**
6. **Update grading to skip invalidated predictions**

#### P2 - Medium (This Month)

7. **Automated cascade when rescheduled game plays**
8. **Dashboard for postponement tracking**
9. **Historical backfill of past postponements**

---

## Immediate Actions for GSW@MIN

### 1. Fix Schedule Data

```sql
-- Update the incorrect "Final" record
UPDATE nba_raw.nbac_schedule
SET
    game_status = 0,  -- Or whatever status code means "Postponed"
    game_status_text = 'Postponed'
WHERE game_date = '2026-01-24'
  AND game_id = '0022500644';
```

### 2. Identify Affected Predictions

```sql
-- Find predictions for GSW/MIN players on Jan 24
SELECT player_lookup, system_id, predicted_points
FROM nba_predictions.player_prop_predictions p
JOIN nba_reference.player_registry r ON p.player_lookup = r.player_lookup
WHERE p.game_date = '2026-01-24'
  AND r.current_team_abbr IN ('GSW', 'MIN');
```

### 3. Mark Predictions as Invalidated

```sql
-- Add invalidation reason (once column exists)
UPDATE nba_predictions.player_prop_predictions
SET
    invalidation_reason = 'game_postponed_gsw_min_2026-01-24',
    invalidated_at = CURRENT_TIMESTAMP()
WHERE game_date = '2026-01-24'
  AND player_lookup IN (
    SELECT player_lookup
    FROM nba_reference.player_registry
    WHERE current_team_abbr IN ('GSW', 'MIN')
  );
```

### 4. Generate Predictions for Jan 25

When the pipeline runs for Jan 25, it should:
- Detect GSW@MIN is now scheduled for today
- Generate predictions for GSW/MIN players
- These will be graded when the game completes

---

## Success Metrics

| Metric | Current | Target |
|--------|---------|--------|
| Time to detect postponement | Not detected | < 30 minutes |
| Predictions invalidated automatically | 0% | 100% |
| Rescheduled games with predictions | Unknown | 100% |
| False positive rate | N/A | < 5% |

---

## Open Questions

1. **What is the correct NBA.com status code for "Postponed"?**
   - Current data only shows 1 (Scheduled) and 3 (Final)
   - Need to check NBA.com API documentation

2. **Should we store predictions for both original and new dates?**
   - Option A: Archive original, create new
   - Option B: Update game_date on existing predictions
   - Recommendation: Archive original (preserve history)

3. **How to handle cascading rolling window updates?**
   - Player's L5D/L10D stats may need recalculation
   - Feature quality scores may be affected

---

*Document created after GSW@MIN postponement incident*
*Next step: Review with team and prioritize implementation*

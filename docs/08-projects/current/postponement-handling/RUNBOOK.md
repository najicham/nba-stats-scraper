# Postponed Game Handling - Operational Runbook

## Quick Reference

### Detection Command
```bash
# Check specific date
python bin/validation/detect_postponements.py --date 2026-01-24

# Check last 3 days
python bin/validation/detect_postponements.py --days 3

# Check and log to BigQuery
python bin/validation/detect_postponements.py --date 2026-01-24 --log

# Check and send Slack alert for CRITICAL/HIGH findings
python bin/validation/detect_postponements.py --date 2026-01-24 --slack

# Full detection with logging and alerting
python bin/validation/detect_postponements.py --days 3 --log --slack
```

### Fix Command
```bash
# Dry run first
python bin/fixes/fix_postponed_game.py \
  --game-id 0022500644 \
  --original-date 2026-01-24 \
  --new-date 2026-01-25 \
  --reason "Reason for postponement" \
  --dry-run

# Apply fix
python bin/fixes/fix_postponed_game.py \
  --game-id 0022500644 \
  --original-date 2026-01-24 \
  --new-date 2026-01-25 \
  --reason "Reason for postponement"
```

---

## Scenarios

### Scenario 1: Suspected Postponement (Alert Received)

**Symptoms:**
- Daily health check reports "Final" game with NULL scores
- News mentions postponement
- Boxscore scraper returns 0 records for a "Final" game

**Steps:**

1. **Verify the postponement**
   ```bash
   python bin/validation/detect_postponements.py --date YYYY-MM-DD
   ```

2. **Check news articles**
   ```sql
   SELECT title, summary, published_at
   FROM nba_raw.news_articles_raw
   WHERE LOWER(title) LIKE '%postpone%'
     AND published_at >= 'YYYY-MM-DD'
   ORDER BY published_at DESC
   LIMIT 10;
   ```

3. **Find the rescheduled date**
   ```sql
   SELECT game_id, game_date, game_status_text
   FROM nba_raw.nbac_schedule
   WHERE game_id = 'GAME_ID'
   ORDER BY game_date;
   ```

4. **Apply the fix**
   ```bash
   python bin/fixes/fix_postponed_game.py \
     --game-id GAME_ID \
     --original-date YYYY-MM-DD \
     --new-date YYYY-MM-DD \
     --reason "Reason"
   ```

### Scenario 2: Rescheduled Game is Played

**When:** The postponed game finally happens on its new date.

**Steps:**

1. **Verify game completed**
   ```sql
   SELECT game_date, game_status_text, home_team_score, away_team_score
   FROM nba_raw.nbac_schedule
   WHERE game_id = 'GAME_ID'
   ORDER BY game_date;
   ```

2. **Check boxscore data exists**
   ```sql
   SELECT COUNT(*) as players
   FROM nba_raw.bdl_player_boxscores
   WHERE game_date = 'NEW_DATE'
     AND game_id LIKE '%AWAY%HOME%';
   ```

3. **Update postponement record**
   ```sql
   UPDATE nba_orchestration.game_postponements
   SET status = 'resolved', resolved_at = CURRENT_TIMESTAMP()
   WHERE game_id = 'GAME_ID' AND original_date = 'ORIGINAL_DATE';
   ```

4. **Verify analytics ran**
   ```sql
   SELECT COUNT(*) as players
   FROM nba_analytics.player_game_summary
   WHERE game_date = 'NEW_DATE'
     AND (team_abbr IN ('AWAY', 'HOME') OR opponent_team_abbr IN ('AWAY', 'HOME'));
   ```

### Scenario 3: Game Cancelled (Not Rescheduled)

**Steps:**

1. **Record as cancelled**
   ```bash
   python bin/fixes/fix_postponed_game.py \
     --game-id GAME_ID \
     --original-date YYYY-MM-DD \
     --reason "Game cancelled - not rescheduled"
   ```

2. **No new_date means cancelled**

---

## SQL Queries

### Find All Active Postponements
```sql
SELECT *
FROM nba_orchestration.game_postponements
WHERE status IN ('detected', 'confirmed')
ORDER BY original_date DESC;
```

### Find Predictions for Postponed Game
```sql
SELECT player_lookup, system_id, predicted_points, created_at
FROM nba_predictions.player_prop_predictions
WHERE game_date = @original_date
  AND game_id = @prediction_game_id  -- Format: YYYYMMDD_AWAY_HOME
ORDER BY player_lookup;
```

### Check Schedule Anomalies
```sql
-- Final games with NULL scores
SELECT game_id, game_date, home_team_tricode, away_team_tricode
FROM nba_raw.nbac_schedule
WHERE game_status = 3  -- Final
  AND (home_team_score IS NULL OR away_team_score IS NULL)
  AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY);
```

### Check Duplicate Game IDs
```sql
SELECT game_id, ARRAY_AGG(DISTINCT game_date ORDER BY game_date) as dates
FROM nba_raw.nbac_schedule
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 14 DAY)
GROUP BY game_id
HAVING COUNT(DISTINCT game_date) > 1;
```

---

## Alerts Integration

### Add to Daily Health Check

The detection script returns exit codes:
- `0`: No issues
- `1`: HIGH severity issues found
- `2`: CRITICAL severity issues found

Integrate with alerting:
```bash
python bin/validation/detect_postponements.py --days 1 --log
EXIT_CODE=$?

if [ $EXIT_CODE -eq 2 ]; then
    # Send critical alert
    curl -X POST $SLACK_WEBHOOK -d '{"text":"CRITICAL: Postponed game detected!"}'
elif [ $EXIT_CODE -eq 1 ]; then
    # Send warning
    curl -X POST $SLACK_WEBHOOK -d '{"text":"WARNING: Schedule anomaly detected"}'
fi
```

---

## Forcing Predictions for Rescheduled Games

When a game is rescheduled and needs new predictions:

```bash
# Force predictions with retry logic (handles rate limiting)
./bin/pipeline/force_predictions.sh 2026-01-25

# The script includes:
# - Exponential backoff (30s, 60s, 120s) for HTTP 429/503
# - Max 3 retries per API call
# - Clears stuck Firestore entries
# - Runs Phase 3 → Phase 4 → Phase 5 sequentially
```

---

## Prevention Checklist

Before each game day:
- [ ] Run `detect_postponements.py --slack` for today's date
- [ ] Check news for any postponement mentions
- [ ] Verify schedule status for all games

After games complete:
- [ ] Verify all "Final" games have scores
- [ ] Verify boxscore data exists for all completed games
- [ ] Check for any new duplicate game_ids (rescheduled games)

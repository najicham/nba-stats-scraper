# Fix Prompt for New Chat Session

**Copy everything below the line to start a new chat session.**

---

## Mission: Fix NBA Props Platform Data Quality Issues

You need to fix 2 critical issues affecting the NBA props platform. Games are tonight, so Priority 0 is urgent.

### Context
Read the full investigation at: `docs/08-projects/current/2026-01-27-data-quality-investigation/findings.md`

---

## Priority 0: Fix Missing Predictions for Jan 27 (URGENT - Games Tonight!)

### Problem
Zero predictions generated for Jan 27. Root cause: Phase 3 ran before betting lines were scraped, so all players have `has_prop_line = FALSE`.

### Evidence
```sql
-- All players missing prop lines flag
SELECT game_date, COUNT(*) as players, COUNTIF(has_prop_line = TRUE) as with_lines
FROM `nba-props-platform.nba_analytics.upcoming_player_game_context`
WHERE game_date = '2026-01-27'
GROUP BY game_date
-- Result: 236 players, 0 with_lines
```

But betting lines DO exist in raw:
```sql
SELECT COUNT(DISTINCT player_lookup) FROM `nba-props-platform.nba_raw.odds_api_player_points_props`
WHERE game_date = '2026-01-27'
-- Result: 40 players have lines
```

### Fix Steps

1. **Re-run Phase 3 `upcoming_player_game_context` processor for Jan 27**

   Option A - Via Cloud Run endpoint (if available):
   ```bash
   curl -X POST https://nba-phase3-analytics-processors-XXXXX.run.app/process \
     -H "Content-Type: application/json" \
     -d '{"processor": "upcoming_player_game_context", "game_date": "2026-01-27"}'
   ```

   Option B - Direct Python invocation:
   ```bash
   cd /home/naji/code/nba-stats-scraper
   python -c "
   from data_processors.analytics.upcoming_player_game_context.upcoming_player_game_context_processor import UpcomingPlayerGameContextProcessor
   processor = UpcomingPlayerGameContextProcessor()
   processor.process(game_date='2026-01-27')
   "
   ```

   Option C - Find the correct invocation method by checking:
   ```bash
   # Check how the processor is typically invoked
   grep -r "upcoming_player_game_context" orchestration/ --include="*.py" | head -20
   ```

2. **Verify fix worked**
   ```bash
   bq query --use_legacy_sql=false "
   SELECT COUNTIF(has_prop_line = TRUE) as with_lines, COUNT(*) as total
   FROM \`nba-props-platform.nba_analytics.upcoming_player_game_context\`
   WHERE game_date = '2026-01-27'"
   ```
   Expected: ~40 players with has_prop_line = TRUE

3. **Trigger prediction coordinator for Jan 27**

   Option A - Via endpoint:
   ```bash
   curl -X POST https://prediction-coordinator-XXXXX.run.app/start \
     -H "Content-Type: application/json" \
     -d '{"game_date": "2026-01-27"}'
   ```

   Option B - Check how predictions are triggered:
   ```bash
   grep -r "prediction" orchestration/ --include="*.py" | grep -i "trigger\|start\|run" | head -10
   ls predictions/
   ```

4. **Validate predictions generated**
   ```bash
   bq query --use_legacy_sql=false "
   SELECT COUNT(*) as predictions, COUNT(DISTINCT player_lookup) as players
   FROM \`nba-props-platform.nba_predictions.player_prop_predictions\`
   WHERE game_date = '2026-01-27' AND is_active = TRUE"
   ```
   Expected: 80-100+ predictions

---

## Priority 1: Deploy game_id Fix and Reprocess Jan 26

### Problem
Commit `d3066c88` fixes game_id format mismatch but is NOT deployed. 71% of players missing `usage_rate`.

### Evidence
```sql
SELECT COUNTIF(usage_rate IS NULL) as null_count, COUNT(*) as total
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date = '2026-01-26'
-- Result: 161 NULL out of 226 (71%)
```

### Fix Steps

1. **Verify fix is in codebase**
   ```bash
   git log --oneline | grep -i "game_id"
   # Should show: d3066c88 fix: Handle game_id format mismatch in team stats JOIN

   grep -n "game_id_reversed" data_processors/analytics/player_game_summary/player_game_summary_processor.py
   # Should show the fix at lines ~634 and ~668
   ```

2. **Deploy to Cloud Run**

   Option A - If CI/CD exists:
   ```bash
   # Check for deployment scripts
   ls bin/deploy* 2>/dev/null || ls scripts/deploy* 2>/dev/null
   # Or check GitHub Actions
   cat .github/workflows/*.yml 2>/dev/null | grep -A5 "deploy"
   ```

   Option B - Manual gcloud deploy:
   ```bash
   # Find the service configuration
   ls data_processors/analytics/Dockerfile 2>/dev/null
   ls data_processors/analytics/*.yaml 2>/dev/null

   # Deploy (adjust paths as needed)
   gcloud run deploy nba-phase3-analytics-processors \
     --source=data_processors/analytics \
     --region=us-west2 \
     --project=nba-props-platform
   ```

3. **Reprocess Jan 26 player_game_summary**
   ```bash
   # Find how to trigger reprocessing
   grep -r "player_game_summary" orchestration/ --include="*.py" | head -10

   # Or direct invocation
   python -c "
   from data_processors.analytics.player_game_summary.player_game_summary_processor import PlayerGameSummaryProcessor
   processor = PlayerGameSummaryProcessor()
   processor.process(game_date='2026-01-26')
   "
   ```

4. **Validate fix worked**
   ```bash
   bq query --use_legacy_sql=false "
   SELECT
     COUNTIF(usage_rate IS NULL) as null_count,
     COUNTIF(usage_rate IS NOT NULL) as has_value,
     ROUND(100.0 * COUNTIF(usage_rate IS NOT NULL) / COUNT(*), 1) as coverage_pct
   FROM \`nba-props-platform.nba_analytics.player_game_summary\`
   WHERE game_date = '2026-01-26'"
   ```
   Expected: coverage_pct > 90%

---

## Success Criteria

1. ✅ Jan 27 has 80+ predictions generated
2. ✅ Jan 26 usage_rate coverage > 90%
3. ✅ Document what you did in `docs/08-projects/current/2026-01-27-data-quality-investigation/fix-log.md`

---

## If You Get Stuck

1. **Check processor patterns**: `ls data_processors/analytics/*/`
2. **Check orchestration**: `cat orchestration/workflow_executor.py | head -100`
3. **Check Cloud Run services**: `gcloud run services list --region=us-west2`
4. **Check scheduler jobs**: `gcloud scheduler jobs list --location=us-west2`

---

## After Fixing

Update the findings.md with:
- What commands you ran
- What worked/didn't work
- Final validation results

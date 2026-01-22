# BDL Missing Games - Quick Start Guide
**For the next session to implement**

---

## TL;DR

**Problem:** 31 games missing from BigQuery. They're in BDL's API, we just didn't scrape them at the right time.

**Immediate Actions:**

1. **Backfill the data** (5 minutes)
2. **Deploy game logging** (30 minutes)
3. **Add completeness check** (30 minutes)
4. **Fix workflow execution** (investigate + fix)

---

## 1. Backfill Missing Games (Do First)

Run this command:

```bash
gcloud run jobs execute bdl-boxscore-backfill \
  --args="--service-url=https://nba-scrapers-f7p3g7f6ya-wl.a.run.app,--dates=2026-01-01,2026-01-15,2026-01-16,2026-01-17,2026-01-18,2026-01-19" \
  --region=us-west2
```

**Verify it worked:**
```sql
SELECT game_date, COUNT(DISTINCT game_id) as games
FROM nba_raw.bdl_player_boxscores
WHERE game_date IN ('2026-01-01', '2026-01-15', '2026-01-16',
                     '2026-01-17', '2026-01-18', '2026-01-19')
GROUP BY game_date
ORDER BY game_date;
```

**Expected:**
- Jan 1: 5 (was 3)
- Jan 15: 9 (was 1)
- Jan 16: 6 (was 5)
- Jan 17: 9 (was 7)
- Jan 18: 6 (was 4)
- Jan 19: 9 (was 8)

---

## 2. Deploy Game-Level Logging

### Step A: Create BigQuery Table

```bash
bq query --nouse_legacy_sql --location=us-west2 < \
  schemas/bigquery/nba_orchestration/bdl_game_scrape_attempts.sql
```

### Step B: Edit BDL Scraper

File: `scrapers/balldontlie/bdl_box_scores.py`

**Add import** (after line 70):
```python
try:
    from shared.utils.bdl_availability_logger import log_bdl_game_availability
except ImportError:
    logger.warning("Could not import bdl_availability_logger")
    def log_bdl_game_availability(*args, **kwargs): pass
```

**Add logging call** (in `transform_data()` method after `self.data =` around line 230):
```python
        self.data = {
            "date": self.opts["date"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "rowCount": len(rows),
            "boxScores": rows,
        }

        # NEW: Log which games were available
        try:
            log_bdl_game_availability(
                game_date=self.opts["date"],
                execution_id=self.run_id,
                box_scores=self.data["boxScores"],
                workflow=self.opts.get("workflow")
            )
        except Exception as e:
            logger.warning(f"Failed to log game availability: {e}")
```

### Step C: Deploy & Test

```bash
# Test locally with a recent date
python scrapers/balldontlie/bdl_box_scores.py --date 2026-01-20 --debug

# Check data appeared
bq query --nouse_legacy_sql --location=us-west2 \
  "SELECT * FROM nba_orchestration.bdl_game_scrape_attempts WHERE game_date = '2026-01-20' LIMIT 5"
```

---

## 3. Add Completeness Check

**Edit:** `scrapers/balldontlie/bdl_box_scores.py` in `transform_data()` method

Add this AFTER the data logging section:

```python
        # NEW: Check completeness
        try:
            from google.cloud import bigquery
            client = bigquery.Client()

            # Count expected games from schedule
            query = """
            SELECT COUNT(*) as expected_games
            FROM `nba-props-platform.nba_raw.nbac_schedule`
            WHERE game_date = @game_date
              AND season_year = 2025
              AND game_status = 3
            """

            job_config = bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("game_date", "DATE", self.opts["date"])
                ]
            )

            results = list(client.query(query, job_config=job_config).result())
            expected = results[0].expected_games if results else 0

            # Count games we got from BDL
            games_returned = len(set(
                (r.get("game", {}).get("home_team", {}).get("abbreviation"),
                 r.get("game", {}).get("visitor_team", {}).get("abbreviation"))
                for r in self.data["boxScores"]
            ))

            if games_returned < expected:
                missing_count = expected - games_returned
                logger.warning(
                    f"INCOMPLETE DATA: Got {games_returned} of {expected} games for {self.opts['date']} "
                    f"({missing_count} games missing from BDL response)"
                )

                notify_warning(
                    title="BDL Box Scores - Incomplete Data",
                    message=f"Missing {missing_count} games for {self.opts['date']}",
                    details={
                        'scraper': 'bdl_box_scores',
                        'date': self.opts['date'],
                        'expected_games': expected,
                        'returned_games': games_returned,
                        'missing_games': missing_count
                    }
                )
            else:
                logger.info(f"COMPLETE: Got all {games_returned} expected games")

        except Exception as e:
            logger.warning(f"Could not check completeness: {e}")
```

---

## 4. Investigate Workflow Execution

**Question:** Why did only the 1 AM window run? Where are the 2 AM, 4 AM, 6 AM runs?

**Check controller logs:**
```bash
gcloud logging read "resource.type=cloud_run_revision
  AND resource.labels.service_name=master-controller
  AND timestamp>='2026-01-01T00:00:00Z'
  AND timestamp<='2026-01-02T12:00:00Z'" \
  --limit 50 \
  --format json > /tmp/controller_logs_jan1.json
```

**Look for:**
- Decision logic for `post_game_window_2b`, `post_game_window_3`, `morning_recovery`
- Why they didn't trigger
- Errors or skip conditions

**Verify workflows are enabled:**
```bash
grep -A 10 "post_game_window_2b:" config/workflows.yaml
grep -A 10 "morning_recovery:" config/workflows.yaml
```

---

## Files Created (Ready to Use)

✅ `shared/utils/bdl_availability_logger.py` - Logger utility
✅ `schemas/bigquery/nba_orchestration/bdl_game_scrape_attempts.sql` - Table definition
✅ `docs/08-projects/current/robustness-improvements/BDL-MISSING-GAMES-ROOT-CAUSE-AND-FIXES.md` - Full analysis

---

## Expected Timeline

| Task | Time | Blocker? |
|------|------|----------|
| Backfill data | 5 min | No |
| Create BigQuery table | 2 min | No |
| Edit scraper (logging) | 15 min | No |
| Edit scraper (completeness) | 15 min | No |
| Test locally | 10 min | No |
| Deploy to prod | 5 min | No |
| Investigate workflows | 30-60 min | Maybe (need logs access) |

**Total: ~1.5 hours** (excluding workflow investigation)

---

## Testing the Fix

After deploying, wait for tonight's games and check:

1. **Game logging working?**
```sql
SELECT scrape_timestamp, game_date, home_team, away_team, was_available
FROM nba_orchestration.bdl_game_scrape_attempts
WHERE game_date = CURRENT_DATE()
ORDER BY scrape_timestamp DESC
LIMIT 20;
```

2. **Completeness warnings appearing?**
```bash
# Check scraper logs for "INCOMPLETE DATA" warnings
gcloud logging read "resource.labels.service_name=nba-scrapers
  AND textPayload:'INCOMPLETE DATA'" \
  --limit 20
```

3. **All workflow windows running?**
```sql
SELECT
  DATE(triggered_at) as date,
  workflow,
  COUNT(*) as executions
FROM nba_orchestration.scraper_execution_log
WHERE scraper_name LIKE '%bdl%'
  AND DATE(triggered_at) = CURRENT_DATE()
GROUP BY date, workflow
ORDER BY workflow;

-- Should see all 5 workflows:
-- post_game_window_1
-- post_game_window_2
-- post_game_window_2b
-- post_game_window_3
-- morning_recovery
```

---

## Questions for Investigation

1. Why didn't recovery windows (2 AM, 4 AM, 6 AM) execute on Jan 1?
2. Is the master controller running?
3. Are workflow decision conditions too restrictive?
4. Do we need to adjust timing or dependencies?

Check the full document for detailed analysis:
`docs/08-projects/current/robustness-improvements/BDL-MISSING-GAMES-ROOT-CAUSE-AND-FIXES.md`

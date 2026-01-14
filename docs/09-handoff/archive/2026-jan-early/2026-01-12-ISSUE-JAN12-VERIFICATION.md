# Issue: Verify Jan 12 Overnight Processing

**Priority:** P1 (Monitoring)
**Status:** Pending verification
**Created:** January 12, 2026 (Session 23)
**When to Check:** Morning of January 13, 2026

---

## Context

Jan 12, 2026 has **6 NBA games** scheduled for the evening. This document provides commands to verify the pipeline processed them correctly overnight.

---

## Games to Verify

| Game | Expected in Data |
|------|------------------|
| Game 1 | ✓ |
| Game 2 | ✓ |
| Game 3 | ✓ |
| Game 4 | ✓ |
| Game 5 | ✓ |
| Game 6 | ✓ |

---

## Verification Commands

### 1. Check Gamebook Coverage
```bash
bq query --use_legacy_sql=false "
SELECT game_date, COUNT(DISTINCT game_id) as games
FROM \`nba-props-platform.nba_raw.nbac_gamebook_player_stats\`
WHERE game_date = '2026-01-12'
GROUP BY 1"

# Expected: 6 games
```

### 2. Check TDGS Coverage
```bash
bq query --use_legacy_sql=false "
SELECT game_date, COUNT(DISTINCT game_id) as games
FROM \`nba-props-platform.nba_analytics.team_defense_game_summary\`
WHERE game_date = '2026-01-12'
GROUP BY 1"

# Expected: 6 games (12 records - 2 per game)
```

### 3. Check BDL Box Scores
```bash
bq query --use_legacy_sql=false "
SELECT game_date, COUNT(DISTINCT game_id) as games
FROM \`nba-props-platform.nba_raw.bdl_player_boxscores\`
WHERE game_date = '2026-01-12'
GROUP BY 1"

# Note: May have fewer if west coast games affected by timing issue
```

### 4. Check Workflow Executions
```bash
bq query --use_legacy_sql=false "
SELECT workflow_name, status, execution_time
FROM \`nba-props-platform.nba_orchestration.workflow_executions\`
WHERE execution_time > '2026-01-12 20:00:00'
ORDER BY execution_time DESC
LIMIT 20"

# Look for: post_game_window_1, post_game_window_2, post_game_window_3
```

### 5. Check GCS Files
```bash
# Gamebook PDFs
gsutil ls "gs://nba-scraped-data/nba-com/gamebooks-pdf/2026-01-12/" | wc -l
# Expected: 6

# BDL live boxscores
gsutil ls "gs://nba-scraped-data/ball-dont-lie/live-boxscores/2026-01-12/" | wc -l
# Should have many files (scraped every 3 min during games)
```

---

## What to Look For

### Healthy State
- Gamebook: 6 games
- TDGS: 6 games
- BDL: 4-6 games (may miss late west coast if applicable)
- All workflows: completed status

### Warning Signs
- Gamebook < 6 games → Check for 404s in NBA.com
- TDGS < gamebook → Re-run TDGS backfill
- Any workflow failed → Check Cloud Logs

---

## If Issues Found

### Missing Gamebook Data
```bash
# Check which games are missing
bq query --use_legacy_sql=false "
SELECT s.game_id, s.game_date
FROM \`nba-props-platform.nba_raw.nbac_schedule\` s
LEFT JOIN \`nba-props-platform.nba_raw.nbac_gamebook_player_stats\` g
  ON s.game_id = g.game_id
WHERE s.game_date = '2026-01-12'
  AND g.game_id IS NULL"

# Re-run gamebook backfill
PYTHONPATH=. python scripts/backfill_gamebooks.py --date 2026-01-12
```

### Missing TDGS Data
```bash
# Re-run TDGS backfill
PYTHONPATH=. python backfill_jobs/analytics/team_defense_game_summary/team_defense_game_summary_analytics_backfill.py --dates 2026-01-12
```

### Missing BDL Data
```bash
# Re-run BDL backfill
PYTHONPATH=. python backfill_jobs/raw/bdl_boxscores/bdl_boxscores_raw_backfill.py --dates=2026-01-12
```

---

## Success Criteria

| Source | Expected | Status |
|--------|----------|--------|
| Gamebook | 6 games | ⏳ |
| TDGS | 6 games | ⏳ |
| BDL | 4-6 games | ⏳ |
| Workflows | All completed | ⏳ |

---

## Notes

- If all gamebook data is present, pipeline is healthy
- BDL gaps are acceptable due to known west coast timing issue
- Document any new issues in ISSUES-FOUND.md

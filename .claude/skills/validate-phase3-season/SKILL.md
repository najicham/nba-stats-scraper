---
name: validate-phase3-season
description: Run comprehensive Phase 3 analytics audit across the full season or a date range
---

# Phase 3 Season Audit

You are performing a comprehensive Phase 3 analytics audit for the NBA stats scraper. This validates that all game data has been processed into analytics tables correctly.

## Your Mission

Audit the completeness and quality of Phase 3 analytics data (player_game_summary, team_offense_game_summary) across the season. Identify gaps, assess impact, and provide fix commands.

## Quick Mode (No Arguments)

Run the full audit script:

```bash
PYTHONPATH=. python bin/monitoring/phase3_season_audit.py --fix
```

## With Date Range

```bash
PYTHONPATH=. python bin/monitoring/phase3_season_audit.py --start 2026-01-01 --end 2026-02-10 --fix
```

## What It Checks

### 1. Player Game Summary Coverage
Compares scheduled games (game_status=3) against player_game_summary records.
- **Expected**: Every completed game has player records
- **Gap causes**: Phase 3 processor failure, scraper failure, postponed games with wrong status

### 2. Team Offense Game Summary Coverage
Compares expected teams (2 per game) against team_offense_game_summary records.
- **Expected**: Every team that played has a team record
- **Gap causes**: TeamOffenseGameSummaryProcessor failure, timing cascade (ran before data ready)

### 3. Data Quality (Usage Rate)
Checks that active players (non-DNP, minutes > 0) have valid usage_rate values.
- **Expected**: >= 95% coverage per game date
- **0% coverage**: Team data completely missing for that date
- **93-97% coverage**: Normal — a few bench players per game may lack usage rates

### 4. Monthly Summary
Shows records and active players per month for trend analysis.

## Interpreting Results

| Finding | Severity | Action |
|---------|----------|--------|
| PGS games missing | P1 CRITICAL | Reprocess Phase 3 for that date |
| Team records missing | P2 HIGH | Reprocess TeamOffenseGameSummaryProcessor |
| Usage rate 0% | P1 CRITICAL | Reprocess both team + player summaries |
| Usage rate 93-97% | P4 INFO | Normal variance, no action needed |
| Usage rate < 80% | P2 HIGH | Investigate team data for that date |

## Fix Commands

The `--fix` flag outputs curl commands to reprocess gaps:

```bash
# Example fix for Jan 26:
curl -X POST "https://nba-phase3-analytics-processors-756957797294.us-west2.run.app/process-date-range" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" \
  -d '{"start_date": "2026-01-26", "end_date": "2026-01-26", "backfill_mode": true, "trigger_reason": "phase3_audit_fix"}'
```

## Deep Investigation

If gaps are found, use these queries to diagnose:

```sql
-- Which teams are missing for a specific date?
WITH expected AS (
  SELECT away_team_tricode as team FROM nba_reference.nba_schedule
  WHERE game_date = 'YYYY-MM-DD' AND game_status = 3
  UNION ALL
  SELECT home_team_tricode FROM nba_reference.nba_schedule
  WHERE game_date = 'YYYY-MM-DD' AND game_status = 3
),
actual AS (
  SELECT team_abbr FROM nba_analytics.team_offense_game_summary
  WHERE game_date = 'YYYY-MM-DD'
)
SELECT e.team FROM expected e
LEFT JOIN actual a ON e.team = a.team_abbr
WHERE a.team_abbr IS NULL;
```

```sql
-- Check if raw data exists for the missing date
SELECT COUNT(*) FROM nba_raw.bdl_player_boxscores WHERE game_date = 'YYYY-MM-DD';
SELECT COUNT(*) FROM nba_raw.nbac_gamebook_player_boxscores WHERE game_date = 'YYYY-MM-DD';
```

## Related Skills

- `/validate-daily` — Daily pipeline health check
- `/validate-historical` — Historical data cascade analysis
- `/spot-check-features` — Feature store quality validation
- `/reconcile-yesterday` — Check yesterday's pipeline for gaps

## Prevention (Session 185)

The `validate-pipeline-patterns` pre-commit hook prevents:
1. **Enum crashes** — validates SourceCoverageSeverity member usage
2. **Orchestrator name mapping gaps** — ensures CLASS_TO_CONFIG_MAP covers all expected processors
3. **Content-Type 415 errors** — flags unsafe `request.get_json()` in Cloud Scheduler endpoints

Run manually: `python .pre-commit-hooks/validate_pipeline_patterns.py`

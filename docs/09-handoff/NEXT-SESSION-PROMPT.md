# Session 145 Prompt

Read the Session 144 handoff at `docs/09-handoff/2026-02-07-SESSION-144-HANDOFF.md`.

## Context

Session 144 investigated why only 37-45% of feature store records have ALL features populated (despite 100% player coverage). Found three root causes:
1. **PlayerDailyCacheProcessor** only caches today's game players (~175/457) - **FIXED** with on-the-fly fallback in `feature_extractor.py`
2. **Vegas lines** (features 25-27) unavailable for 60% of players (bench players) - external limitation
3. **Shot zone** timing/coverage partially fixed by cache fallback

Session 144 deployed Phase 2, Phase 3, and Phase 4 with the cache miss fix.

## Immediate Tasks

### 1. Verify Deployments and Cache Miss Fix
```bash
# Check deployments completed
./bin/check-deployment-drift.sh --verbose

# Check today's feature completeness (should be ~50-63% vs previous 37-45%)
bq query --use_legacy_sql=false "
SELECT game_date,
  COUNTIF(default_feature_count = 0) as fully_complete,
  COUNT(*) as total,
  ROUND(COUNTIF(default_feature_count = 0) / COUNT(*) * 100, 1) as pct_complete,
  ROUND(AVG(default_feature_count), 1) as avg_defaults
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= CURRENT_DATE() - 1
GROUP BY 1 ORDER BY 1
"
```

### 2. Run 2021 Season Backfill (remaining from Session 144)
```bash
PYTHONPATH=. python backfill_jobs/precompute/ml_feature_store/ml_feature_store_precompute_backfill.py \
  --start-date 2021-11-02 --end-date 2021-12-31 --skip-preflight
```

### 3. Implement Vegas Line Strategy (User Decisions Made)

User wants:
1. **Make vegas optional in zero-tolerance** - modify `data_processors/precompute/ml_feature_store/quality_scorer.py` to not count features 25-27 as defaults when computing `is_quality_ready`. Keep tracking them as defaults for visibility but don't block predictions.
2. **Add scraper health monitoring** - alert when star players (tier 1-2 with >20 PPG) have no vegas lines (indicates scraper issue vs normal bench player absence)
3. **Store projected lines separately** - add `projected_points_line` field to ml_feature_store_v2 (NOT in the features array). Use season avg + matchup adjustment. Never substitute for real lines in the feature vector.
4. **Never mix real vs projected** in the main features array - keep them clearly separated

### 4. Fix PlayerDailyCacheProcessor Root Cause

The cache miss fallback is a band-aid. The proper fix:
- **File:** `data_processors/precompute/player_daily_cache/player_daily_cache_processor.py`
- **Current:** Queries `upcoming_player_game_context WHERE game_date = TODAY` → ~175 players
- **Fix:** Also query `player_game_summary WHERE season_year = X` for all active season players → ~457 players (like shot zone processor does)
- **Ref:** Shot zone processor at `data_processors/precompute/player_shot_zone_analysis/player_shot_zone_analysis_processor.py` lines 641-686 shows the correct approach

### 5. Check Gap Tracking Table
```sql
SELECT game_date, reason, COUNT(*) as gaps
FROM nba_predictions.feature_store_gaps
WHERE resolved_at IS NULL
GROUP BY 1, 2 ORDER BY 1 DESC LIMIT 20;
```

## Key Architecture (from Session 144 Investigation)

### Feature Default Root Causes
| Feature | Index | Default Rate | Root Cause | Status |
|---------|-------|-------------|-----------|--------|
| pts_avg_l5/l10/season/std | 0-4 | 13% | Cache only has today's players | **FIXED** (fallback) |
| fatigue/shot_zone/pace/usage | 5-8 | 4% | composite_factors timing | OK |
| opponent_def_rating/pace | 13-14 | 0% | team_defense healthy | OK |
| pct_paint/mid/three | 18-20 | 24% | Shot zone timing+coverage | **PARTIALLY FIXED** |
| team_pace/off_rating | 22-23 | 13% | Same as cache issue | **FIXED** (fallback) |
| vegas_points/open/move | 25-27 | 60% | Sportsbooks don't publish for bench | **NEEDS STRATEGY** |
| minutes/ppm_avg | 31-32 | 12% | Same as cache issue | **FIXED** (fallback) |

### Pipeline Timing
- PlayerDailyCacheProcessor: ~5:50 PM ET (event-driven), only today's game players
- MLFeatureStoreProcessor: 7+ times/day, authoritative run at ~12:45 PM ET after cascade
- Cache miss fallback activates when `_daily_cache_lookup` returns empty for a player

### New Table: `nba_predictions.feature_store_gaps`
Schema: player_lookup, game_date, game_id, reason, reason_detail, team_abbr, opponent_team_abbr, season_year, detected_at, detected_by, resolved_at, resolved_by

### Updated Skill: `/spot-check-features`
New checks #24 (record coverage), #25 (per-feature defaults), #26 (completeness dashboard), #27 (gap tracking)

## Key Files Changed in Session 144

| File | What Changed |
|------|-------------|
| `data_processors/precompute/ml_feature_store/feature_extractor.py` | `_compute_cache_fields_from_games()` fallback |
| `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py` | `_record_feature_store_gaps()`, `skip_early_season_check` option |
| `backfill_jobs/precompute/ml_feature_store/ml_feature_store_precompute_backfill.py` | `--include-bootstrap` flag, `_resolve_gaps_for_date()` |
| `.claude/skills/spot-check-features/SKILL.md` | Checks #24-27 |
| `schemas/bigquery/nba_predictions/feature_store_gaps.sql` | Gap tracking table schema |

# Session 293 Handoff — Validate, Backfill, Retrain

**Date:** 2026-02-18
**Previous:** Sessions 290-292 fixed feature extraction bugs (8,000+ → 519 bugs), added NaN-safe helpers, backfilled ML feature store

## Current State

| Component | Status |
|-----------|--------|
| Production model | `catboost_v9_33f_train20251102-20260205` — promoted Feb 16, **12 days old** |
| Feature store | Backfilled Jan 6 - Feb 17, **31/33 features CLEAN** |
| Remaining bugs | f4 (188), f32 (331) — upstream data gaps, blocked by quality gates |
| Code | All fixes pushed to main, auto-deployed (`c2c4dffb`) |
| Games | **Resume Feb 19** — All-Star break ends |

## Start Here

```bash
# 1. Read this handoff
cat docs/09-handoff/2026-02-18-SESSION-292-HANDOFF.md

# 2. Quick health check
/daily-steering
```

## Priority 1: Validate Feature Store Quality for Training

Before retraining, confirm the backfilled data is clean enough.

```bash
# Full validation across training window
PYTHONPATH=. python bin/validate_feature_sources.py --start-date 2025-11-02 --end-date 2026-02-17 --sample-days 5

# Spot-check feature quality
/spot-check-features

# Check quality-ready coverage (target: 60%+ quality-ready)
bq query --use_legacy_sql=false "
SELECT game_date,
  COUNT(*) as total,
  COUNTIF(is_quality_ready) as quality_ready,
  ROUND(100.0 * COUNTIF(is_quality_ready) / COUNT(*), 1) as pct_ready,
  ROUND(AVG(feature_quality_score), 1) as avg_quality
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= '2025-11-02'
GROUP BY 1 ORDER BY 1 DESC LIMIT 10"
```

**Expected:** 31/33 features clean, f4 (188 bugs) and f32 (331 bugs) are known upstream data gaps.

## Priority 2: Backfill plus_minus in player_game_summary

Session 292 fixed `_parse_plus_minus()` — it was silently dropping ALL plus_minus values for the entire season. Need to re-process Phase 3 to populate this column.

```bash
# Check current plus_minus coverage (expect ~0% before backfill)
bq query --use_legacy_sql=false "
SELECT
  COUNTIF(plus_minus IS NOT NULL) as has_pm,
  COUNT(*) as total,
  ROUND(100.0 * COUNTIF(plus_minus IS NOT NULL) / COUNT(*), 1) as pm_pct
FROM nba_analytics.player_game_summary
WHERE game_date >= '2025-10-22' AND NOT is_dnp"

# Backfill Phase 3 player_game_summary (picks up plus_minus fix)
# Look for existing backfill script first:
ls backfill_jobs/analytics/

# If no script exists, the Phase 3 processor can be re-triggered per date
# via the analytics processing pipeline
```

## Priority 3: Extend Feature Store Backfill to Full Season

Sessions 291-292 only backfilled Jan 6 - Feb 17. The training window starts Nov 2.

```bash
# Check what dates are missing before Jan 6
bq query --use_legacy_sql=false "
SELECT MIN(game_date) as earliest, MAX(game_date) as latest, COUNT(DISTINCT game_date) as dates
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= '2025-11-02'"

# Backfill earlier dates (may be blocked by missing team_defense_zone_analysis)
PYTHONPATH=. python backfill_jobs/precompute/ml_feature_store/ml_feature_store_precompute_backfill.py \
  --start-date 2025-11-02 --end-date 2026-01-05 --skip-preflight

# If blocked, check which Phase 4 data is missing:
bq query --use_legacy_sql=false "
SELECT MIN(game_date) as earliest, MAX(game_date) as latest
FROM nba_precompute.team_defense_zone_analysis"
```

## Priority 4: Retrain After Games Resume

Games resume Feb 19. Need 1-3 days of eval data.

```bash
# Check if games have been played (run Feb 20+)
bq query --use_legacy_sql=false "
SELECT game_date, COUNT(*) as games, MIN(game_status) as min_status
FROM nba_reference.nba_schedule
WHERE game_date >= '2026-02-19'
GROUP BY 1 ORDER BY 1 LIMIT 5"

# Retrain when eval data exists (Feb 20-21)
./bin/retrain.sh --promote --eval-days 3   # Short eval window initially
# Or more conservative:
./bin/retrain.sh --promote --eval-days 7   # Wait until Feb 26

# CRITICAL: All governance gates must pass before deploying
# The script outputs ALL GATES PASSED/FAILED
```

**Model age:** Currently 12 days (ROUTINE). Will be 14+ days by Feb 20 (OVERDUE). Retrain reminder will fire Monday Feb 24 if not done.

## Priority 5: Backfill Date-Keyed Tonight Player Exports

New date-keyed export paths were added in Session 292. Backfill historical dates for frontend browsing.

```bash
# Dry run first
PYTHONPATH=. python bin/backfill/backfill_tonight_player_exports.py --dry-run

# Full backfill (resumable, ~25 hours for full season)
PYTHONPATH=. python bin/backfill/backfill_tonight_player_exports.py --skip-existing
```

## Known Issues (Do NOT Investigate)

- **f4 (188 bugs):** `player_daily_cache.games_in_last_7_days` is NULL for 3% of players. Upstream cache processor gap. Blocked by quality gates.
- **f32 (331 bugs):** Bench players lack recent PPM data. Expected behavior. Blocked by quality gates.
- **features array column:** Deprecated, dual-written. Removal deferred (Phase 8, needs 2+ weeks stability).

## Recent Commits

```
c2c4dffb feat: add ft_attempts to last 10 games in tonight exports
e8c202a0 docs: Session 291+292 handoff
720520fc feat: add box score detail to player exports, date-keyed player pages
f96eb275 fix: NaN-safe feature helpers prevent BQ NULL → pandas NaN inconsistencies
1ff893f9 fix: exact-date composite_factors extraction, NaN-safe f29 opponent history
```

## Key Technical Context

**NaN-safe pattern (Session 292):** All feature helper methods now use `_is_valid_value()` which checks both `is None` AND `math.isnan()`. This prevents pandas NaN (from BQ NULL via LEFT JOIN) from leaking through `is not None` checks and causing dual-write divergence (array gets 0.0, column gets NULL).

**Backfill tip:** Use `--skip-preflight` flag to avoid the slow Phase 3 pre-flight BQ query. The pre-flight check is useful for fresh runs but unnecessary when re-running on already-processed dates.

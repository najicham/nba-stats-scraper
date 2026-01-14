# Comprehensive Handoff: Pipeline Reliability + Coverage Gap Investigation

**Date:** 2026-01-10
**Session:** 5 (Coverage Fix + Investigation)
**Priority:** High
**Status:** Partial fix complete (90.4% coverage), critical bugs identified

---

## Executive Summary

This session fixed the Jan 9 prediction coverage by:
1. Enabling DNP-aware completeness in the context processor
2. Loading missing boxscore data for 3 late games
3. Running the full prediction pipeline

**Coverage improved from 31.5% → 90.4%** but 14 players remain without predictions.

**Critical finding:** 4 players have context, features, AND betting lines but NO predictions. This indicates a **bug in the prediction system**, not a data issue.

---

## Current State

### Coverage Breakdown (Jan 9, 2026)

| Category | Count | Players | Root Cause |
|----------|-------|---------|------------|
| **With Predictions** | 132 | - | Working correctly |
| **UNKNOWN_REASON** | 4 | jamalmurray, kristapsporzingis, zaccharierisacher, tristandasilva | **BUG: Have all prerequisites, no prediction generated** |
| **NO_FEATURES** | 5 | brandoningram, marvinbagleyiii, ruihachimura, ziairewilliams, ochaiagbaji | Feature store not generating features despite context |
| **NOT_IN_PLAYER_CONTEXT** | 4 | jimmybutler, carltoncarrington, nicolasclaxton, robertwilliams | Context processor excluded them |
| **NOT_IN_REGISTRY** | 1 | vincentwilliamsjr | **BUG: Alias exists and works, but not being used** |

### Data State Verification

```
UNKNOWN_REASON Players (4 unique - CRITICAL BUG):
┌───────────────────┬─────────────┬──────────────┬────────────────┬──────────────┐
│   player_lookup   │ has_context │ has_features │ has_prediction │ context_team │
├───────────────────┼─────────────┼──────────────┼────────────────┼──────────────┤
│ jamalmurray       │ YES         │ YES          │ NO             │ DEN          │
│ kristapsporzingis │ YES         │ YES          │ NO             │ ATL          │
│ zaccharierisacher │ YES         │ YES          │ NO             │ ATL          │
│ tristandasilva    │ YES         │ YES          │ NO             │ ORL          │
└───────────────────┴─────────────┴──────────────┴────────────────┴──────────────┘
All 4 have betting lines from DraftKings and FanDuel.
This is a prediction system bug - it's filtering out valid players.
```

```
NO_FEATURES Players (5):
┌─────────────────┬─────────────┬──────────────┬──────────────┐
│  player_lookup  │ has_context │ has_features │ context_team │
├─────────────────┼─────────────┼──────────────┼──────────────┤
│ brandoningram   │ YES         │ NO           │ TOR          │
│ marvinbagleyiii │ YES         │ NO           │ WAS          │
│ ruihachimura    │ YES         │ NO           │ LAL          │
│ ziairewilliams  │ YES         │ NO           │ BKN          │
│ ochaiagbaji     │ YES         │ NO           │ TOR          │
└─────────────────┴─────────────┴──────────────┴──────────────┘
Feature store processor is skipping these despite context existing.
```

```
NOT_IN_PLAYER_CONTEXT Players (4):
┌───────────────────┬─────────────┬─────────────┐
│   player_lookup   │ has_context │ in_registry │
├───────────────────┼─────────────┼─────────────┤
│ jimmybutler       │ NO          │ YES         │
│ carltoncarrington │ NO          │ NO          │
│ nicolasclaxton    │ NO          │ NO          │
│ robertwilliams    │ NO          │ YES         │
└───────────────────┴─────────────┴─────────────┘
```

```
vincentwilliamsjr Alias (BUG):
┌───────────────────┬──────────────────────┬───────────────────────┬─────────────┐
│   alias_lookup    │ nba_canonical_lookup │ canonical_in_registry │ has_context │
├───────────────────┼──────────────────────┼───────────────────────┼─────────────┤
│ vincentwilliamsjr │ vincewilliamsjr      │ YES                   │ YES         │
└───────────────────┴──────────────────────┴───────────────────────┴─────────────┘
The alias exists and the canonical player has context, but the prediction
system is NOT resolving the alias when loading betting lines.
```

---

## Issues to Investigate (Priority Order)

### 1. CRITICAL: Prediction System Not Generating Predictions (4 players)

**Symptoms:**
- Players have context (YES)
- Players have features (YES, both v1 and v2)
- Players have betting lines (YES, multiple bookmakers)
- Players have NO prediction

**Affected:** Jamal Murray (DEN), Kristaps Porzingis (ATL), Zaccharie Risacher (ATL), Tristan da Silva (ORL)

**Impact:** High - these include star players with significant betting volume

**Investigation Steps:**
1. Read prediction backfill logs from the last run
2. Check if there's a filtering condition excluding these players
3. Look for confidence thresholds, data quality filters, or other exclusions
4. Check the prediction systems: `data_processors/prediction/`

**Files to Study:**
- `data_processors/prediction/player_prop_predictions_processor.py`
- `backfill_jobs/prediction/player_prop_predictions_backfill.py`
- `prediction_systems/` directory

**SQL to reproduce:**
```sql
-- Verify the bug
SELECT player_lookup,
  CASE WHEN ctx.player_lookup IS NOT NULL THEN 'YES' ELSE 'NO' END as has_context,
  CASE WHEN feat.player_lookup IS NOT NULL THEN 'YES' ELSE 'NO' END as has_features,
  CASE WHEN pred.player_lookup IS NOT NULL THEN 'YES' ELSE 'NO' END as has_prediction
FROM (SELECT 'jamalmurray' as player_lookup) p
LEFT JOIN `nba_analytics.upcoming_player_game_context` ctx USING(player_lookup)
LEFT JOIN `nba_predictions.ml_feature_store_v2` feat USING(player_lookup)
LEFT JOIN `nba_predictions.player_prop_predictions` pred USING(player_lookup)
WHERE ctx.game_date = '2026-01-09'
```

---

### 2. HIGH: Feature Store Not Generating Features (5 players)

**Symptoms:**
- Players have context (YES)
- Players have NO features

**Affected:** Brandon Ingram (TOR), Marvin Bagley III (WAS), Rui Hachimura (LAL), Ziaire Williams (BKN), Ochai Agbaji (TOR)

**Possible Causes:**
- Completeness check failure in feature store
- Missing historical data for feature calculation
- Data quality filter excluding them

**Investigation Steps:**
1. Check ML feature store logs for these players
2. Look for completeness or quality filters
3. Check if these players have sufficient historical data

**Files to Study:**
- `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py`
- `backfill_jobs/precompute/ml_feature_store/`

---

### 3. HIGH: Alias Not Being Used in Predictions (vincentwilliamsjr)

**Symptoms:**
- Alias exists: vincentwilliamsjr → vincewilliamsjr
- Canonical player is in registry and has context
- But coverage check shows NOT_IN_REGISTRY

**Root Cause:** The prediction system loads betting lines by player_lookup, but doesn't resolve aliases first.

**Investigation Steps:**
1. Trace how betting lines are loaded in the prediction system
2. Check if alias resolution happens before or after player lookup
3. Verify timing of alias creation vs prediction run

**Files to Study:**
- `tools/monitoring/check_prediction_coverage.py`
- Prediction system's player loading logic

---

### 4. MEDIUM: Context Processor Excluding Valid Players (4 players)

**Symptoms:**
- Players NOT in context despite being in registry (jimmybutler, robertwilliams)
- Players NOT in registry at all (carltoncarrington, nicolasclaxton)

**Investigation Steps:**
1. Check why Jimmy Butler and Robert Williams were excluded (trade situations? data gaps?)
2. Add Carlton Carrington and Nicolas Claxton to registry
3. Re-run context processor and verify they get context

**Files to Study:**
- `data_processors/analytics/upcoming_player_game_context/upcoming_player_game_context_processor.py`
- Player filtering logic around lines 1570-1600

---

### 5. MEDIUM: Late Game Scraper Timing

**Problem:** 3 West Coast games (GSW/SAC, LAL/MIL, POR/HOU) weren't captured because:
- Last scraper window: 09:05 UTC (1:05 AM PT)
- Games finish: ~06:30 UTC Jan 10 (10:30 PM PT Jan 9)

**Fix Needed:** Add `post_game_window_4` at 07:00-08:00 UTC (11 PM - 12 AM PT)

**Files to Modify:**
- `config/workflows.yaml` - add new window

---

### 6. MEDIUM: Streaming Buffer Protection Too Aggressive

**Problem:** BDL processor aborts entire batch if ANY game has streaming buffer conflicts, even for new games that have no conflicts.

**Fix Needed:** Modify processor to:
1. Skip conflicting games
2. Load new games that have no conflicts
3. Add `--force` flag for manual recovery

**Files to Modify:**
- `data_processors/raw/balldontlie/bdl_boxscores_processor.py` (lines 609-632)

---

### 7. LOW: Capture Tool Format Mismatch

**Problem:** `tools/fixtures/capture.py` outputs raw API format (`{"data": [...]}`) but processor expects wrapped format (`{"boxScores": [...]}`)

**Fix Needed:** Add transformation option to capture tool or document expected format.

---

## Is 90.4% Coverage Acceptable?

### Analysis

| Acceptable? | Reason |
|-------------|--------|
| **NO** | UNKNOWN_REASON gaps (4 players) are a **bug**, not a data limitation |
| **PARTIALLY** | NO_FEATURES gaps (5 players) may be recoverable with investigation |
| **PARTIALLY** | NOT_IN_CONTEXT gaps (4 players) are fixable with registry/context work |
| **YES** | Some gaps due to trades/injuries are expected edge cases |

### Recommendation

**90.4% is NOT acceptable as the final state** because:
1. 4 players with UNKNOWN_REASON have ALL prerequisites - this is a bug
2. Star players like Jamal Murray and Kristaps Porzingis should have predictions
3. These are high-volume betting players with real money impact

**Target should be 95%+** with only edge cases (traded players, injuries, data errors) remaining.

---

## Commits Made This Session

| Commit | Description |
|--------|-------------|
| `8bead18` | fix(processors): Enable DNP-aware completeness and fix DataFrame ambiguity |
| `e2f49ec` | docs(pipeline): Add session 5 summary with root cause analysis |

---

## Files to Study for Next Session

### Prediction System (CRITICAL)
```
data_processors/prediction/
├── player_prop_predictions_processor.py  # Main prediction logic
├── ...

prediction_systems/
├── base_prediction_system.py
├── moving_average_baseline.py
├── zone_matchup_v1.py
├── ensemble_v1.py
└── ...

backfill_jobs/prediction/
├── player_prop_predictions_backfill.py
```

### Feature Store
```
data_processors/precompute/ml_feature_store/
├── ml_feature_store_processor.py  # Feature generation
```

### Context Processor
```
data_processors/analytics/upcoming_player_game_context/
├── upcoming_player_game_context_processor.py  # Player filtering ~lines 1570-1600
```

### Coverage Check Tool
```
tools/monitoring/check_prediction_coverage.py  # Alias resolution issue
```

### BDL Processor
```
data_processors/raw/balldontlie/bdl_boxscores_processor.py  # Streaming buffer ~lines 609-632
```

### Workflow Config
```
config/workflows.yaml  # Add post_game_window_4
```

---

## Previous Documentation

| Document | Purpose |
|----------|---------|
| `docs/09-handoff/2026-01-10-COVERAGE-FIX-HANDOFF.md` | Circuit breaker fix details |
| `docs/09-handoff/2026-01-10-REGISTRY-AND-COVERAGE-HANDOFF.md` | Registry system completion |
| `docs/08-projects/current/pipeline-reliability-improvements/2026-01-10-DNP-AWARE-COMPLETENESS.md` | DNP-aware implementation |
| `docs/08-projects/current/pipeline-reliability-improvements/2026-01-10-SESSION-5-SUMMARY.md` | This session's root cause analysis |

---

## Quick Commands

### Check Coverage
```bash
python tools/monitoring/check_prediction_coverage.py --date 2026-01-09 --detailed
```

### Verify Data State for a Player
```sql
-- Check all tables for a player
SELECT 'context' as source, COUNT(*) as cnt
FROM `nba_analytics.upcoming_player_game_context`
WHERE player_lookup = 'jamalmurray' AND game_date = '2026-01-09'
UNION ALL
SELECT 'features', COUNT(*)
FROM `nba_predictions.ml_feature_store_v2`
WHERE player_lookup = 'jamalmurray' AND game_date = '2026-01-09'
UNION ALL
SELECT 'predictions', COUNT(*)
FROM `nba_predictions.player_prop_predictions`
WHERE player_lookup = 'jamalmurray' AND game_date = '2026-01-09'
UNION ALL
SELECT 'betting_lines', COUNT(*)
FROM `nba_raw.odds_api_player_points_props`
WHERE player_lookup = 'jamalmurray' AND game_date = '2026-01-09'
```

### Run Prediction Backfill with Debug
```bash
PYTHONPATH=. python backfill_jobs/prediction/player_prop_predictions_backfill.py \
  --start-date 2026-01-09 --end-date 2026-01-09 2>&1 | tee /tmp/pred_debug.log
```

---

## Summary of Next Steps

1. **CRITICAL**: Investigate prediction system bug (4 UNKNOWN_REASON players)
2. **HIGH**: Investigate feature store gaps (5 NO_FEATURES players)
3. **HIGH**: Fix alias resolution in prediction/coverage system
4. **MEDIUM**: Add missing players to registry (carltoncarrington, nicolasclaxton)
5. **MEDIUM**: Add late-game scraper window
6. **MEDIUM**: Improve streaming buffer handling
7. **LOW**: Document file formats / improve capture tool

---

**Author:** Claude Code (Opus 4.5)
**Last Updated:** 2026-01-10 20:30 ET

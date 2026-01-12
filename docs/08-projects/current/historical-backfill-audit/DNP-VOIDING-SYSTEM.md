# DNP/Injury Voiding System

**Created:** 2026-01-12 (Session 21)
**Status:** Implemented and Deployed

## Overview

This document describes the DNP (Did Not Play) voiding system that treats predictions for players who don't play like voided bets - similar to how sportsbooks handle these situations.

## Problem Statement

### The Issue
When a player doesn't play (DNP), their predictions were being counted as incorrect:
- A prediction of "OVER 24.5 points" for a player who scored 0 = WRONG
- A prediction of "UNDER 24.5 points" for a player who scored 0 = CORRECT

This is misleading because:
1. Sportsbooks void these bets entirely
2. It skews accuracy metrics (artificially inflates UNDER win rate)
3. High-confidence picks on star players who DNP drag down overall accuracy

### Real Impact (Jan 11, 2026)
Players like Joel Embiid, Brandon Ingram, and Paul George had:
- 89-93% confidence OVER predictions
- 0 actual points (DNP)
- Counted as "wrong" predictions

This single day's DNPs dropped win rate from ~50% to 45%.

## Solution

### Voiding Logic

Predictions are voided when:
```
actual_points = 0 AND (minutes_played = 0 OR minutes_played IS NULL)
```

### Void Reasons

| Reason | Description |
|--------|-------------|
| `dnp_injury_confirmed` | Player was OUT/DOUBTFUL in injury report |
| `dnp_late_scratch` | Player was QUESTIONABLE/PROBABLE but didn't play |
| `dnp_unknown` | No pre-game injury flag, unexpected DNP |

### Schema Changes

Added to `prediction_accuracy` table (v4):

```sql
is_voided BOOLEAN,                    -- TRUE = exclude from accuracy
void_reason STRING,                   -- dnp_injury_confirmed, dnp_late_scratch, dnp_unknown
pre_game_injury_flag BOOLEAN,         -- TRUE if flagged pre-game
pre_game_injury_status STRING,        -- OUT, DOUBTFUL, QUESTIONABLE, PROBABLE
injury_confirmed_postgame BOOLEAN     -- TRUE if DNP matched injury report
```

## Implementation

### Files Modified

1. **Schema**: `schemas/bigquery/nba_predictions/prediction_accuracy.sql`
   - Added 5 voiding fields

2. **Grading Processor**: `data_processors/grading/prediction_accuracy/prediction_accuracy_processor.py`
   - Added `load_injury_status_for_date()` - loads injury reports
   - Added `get_injury_status()` - cached injury lookup
   - Added `detect_dnp_voiding()` - determines if prediction should be voided
   - Modified `grade_prediction()` - now includes voiding fields
   - Modified `process_date()` - now returns voiding stats

### Injury Data Source

Uses `nba_raw.nbac_injury_report` table which contains:
- Multiple injury reports per day (tracked by report_date, report_hour)
- Player injury status: OUT, DOUBTFUL, QUESTIONABLE, PROBABLE, AVAILABLE
- Injury reason/category

## Usage

### Querying Net Accuracy (Excluding Voided)

```sql
-- Net accuracy (like sportsbook results)
SELECT
    game_date,
    SUM(CASE WHEN prediction_correct THEN 1 ELSE 0 END) as correct,
    COUNT(*) as total,
    ROUND(100.0 * SUM(CASE WHEN prediction_correct THEN 1 ELSE 0 END) / COUNT(*), 1) as net_win_rate
FROM `nba_predictions.prediction_accuracy`
WHERE is_voided = FALSE
    AND recommendation IN ('OVER', 'UNDER')
GROUP BY game_date
ORDER BY game_date DESC
```

### Checking Voiding Stats

```sql
SELECT
    void_reason,
    COUNT(*) as count,
    COUNT(DISTINCT player_lookup) as unique_players
FROM `nba_predictions.prediction_accuracy`
WHERE is_voided = TRUE
    AND game_date >= '2026-01-01'
GROUP BY void_reason
```

## Historical Analysis

### DNP Rates by Year

| Year | Total Predictions | DNP Count | DNP % |
|------|-------------------|-----------|-------|
| 2026 | 3,198 | 16 | 0.5% |
| 2025 | 59,273 | 11,251 | 19.0% |
| 2024 | 32,440 | 3 | 0.01% |
| 2023 | 26,649 | 0 | 0.0% |

**Note:** 2025 had abnormally high DNP rate (Nov: 41%, Dec: 30%) - this was a separate bug in the prediction system that has since been fixed.

### Jan 2026 Backfill Results

| Date | Graded | Voided | Net Accuracy |
|------|--------|--------|--------------|
| 2026-01-01 | 420 | 152 | N/A |
| 2026-01-02 | 988 | 0 | 60.9% |
| 2026-01-03 | 802 | 0 | 59.8% |
| 2026-01-04 | 794 | 1 | 55.1% |
| 2026-01-05 | 473 | 0 | 71.6% |
| 2026-01-06 | 357 | 0 | N/A |
| 2026-01-07 | 279 | 1 | 67.1% |
| 2026-01-08 | 132 | 0 | 44.8% |
| 2026-01-09 | 995 | 0 | 93.5% |
| 2026-01-10 | 905 | 0 | 86.1% |
| 2026-01-11 | 587 | 46 | 45.4% |
| **Total** | **6,732** | **200** | - |

## Backfill Strategy

### Priority 1: Jan 2026 (Done)
- All dates re-graded with voiding
- 200 predictions voided

### Priority 2: Nov-Dec 2025 - INVESTIGATED (Session 22)

**Root Cause Found:** NOT actual DNPs - this is a **BDL API data quality issue**.

The BDL API returned incorrect player-team assignments for 2025-26 season:
- Anthony Davis → DAL (should be LAL)
- Jimmy Butler → GSW (should be MIA)
- Jrue Holiday → POR (should be BOS)
- 125+ players have team mismatches

**Impact:**
- Nov 2025: 44% "null minutes" (7,371 predictions)
- Dec 2025: 31% "null minutes" (6,425 predictions)

**Decision:** Flag as data quality issue. Do NOT backfill voiding.
The voiding system works correctly for Jan 2026+ where BDL data quality is better

### Priority 3: Historical (2021-2024)
- Very low DNP rates (<0.1%)
- Optional backfill - minimal impact expected

## Pre-game Injury Flagging (v3.4) - Implemented Session 22

### Overview

Captures injury status AT PREDICTION TIME so we can distinguish:
- **Expected voids**: Player was flagged with injury concern before game (we had warning)
- **Surprise voids**: Player DNP'd without prior warning (late scratch)

### Schema Changes

Added to `player_prop_predictions` table (v3.4):

```sql
injury_status_at_prediction STRING,    -- OUT, DOUBTFUL, QUESTIONABLE, PROBABLE, or NULL
injury_flag_at_prediction BOOLEAN,     -- TRUE if any injury concern at prediction time
injury_reason_at_prediction STRING,    -- Injury reason text (e.g., "Left Knee - Soreness")
injury_checked_at TIMESTAMP            -- When injury status was checked
```

### How It Works

1. **At Prediction Time (Worker)**:
   - InjuryFilter queries `nbac_injury_report` for the player
   - Stores injury status, flag, and reason in the prediction record
   - Logs warnings for players with injury flags

2. **At Grading Time (Processor)**:
   - Reads captured injury status from predictions (if available)
   - Uses it to categorize voids as "expected" (had warning) or "surprise" (no warning)
   - Falls back to retroactive lookup for historical predictions

### Pre-game Visibility

The Phase 6 exporter (`tonight_player_exporter.py`) already includes injury status in the exported predictions JSON. Users can see injury status before games at:
- `game_context.injury_status`
- `game_context.injury_reason`

### Files Modified (Session 22)

1. **Schema**: `schemas/bigquery/predictions/01_player_prop_predictions.sql` - Added 4 injury tracking fields
2. **Worker**: `predictions/worker/worker.py` - Added InjuryFilter check and stores status
3. **Grading Processor**: `data_processors/grading/prediction_accuracy/prediction_accuracy_processor.py` - Uses captured status with fallback

## Future Enhancements

1. ~~**Pre-game flagging**: Store injury status at prediction time~~ ✅ DONE (Session 22)
2. **Early warning Slack alert**: Alert when making predictions for QUESTIONABLE players
3. **Dashboard**: Show voiding rates in daily health summary
4. **ML Training**: Exclude voided predictions from model training data

## Related Files

- Schema (predictions): `schemas/bigquery/predictions/01_player_prop_predictions.sql`
- Schema (accuracy): `schemas/bigquery/nba_predictions/prediction_accuracy.sql`
- Worker: `predictions/worker/worker.py`
- Grading Processor: `data_processors/grading/prediction_accuracy/prediction_accuracy_processor.py`
- Injury Filter: `predictions/shared/injury_filter.py`
- Injury data: `nba_raw.nbac_injury_report`
- Handoff: `docs/09-handoff/2026-01-12-SESSION-21-HANDOFF.md`

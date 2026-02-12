# Model Decay Protective Filters (Session 211)

## Problem Statement

The champion `catboost_v9` model (trained Nov 2 - Jan 8) has been stale for 34+ days and has dropped below breakeven for 2 consecutive weeks:

| Metric | Jan 18 | Feb 1 | Feb 8 |
|--------|--------|-------|-------|
| Edge 3+ HR | 67.3% | 39.4% | 42.1% |
| UNDER edge 3+ HR | — | 27.5% | — |

Key decay patterns:
- **UNDER collapse**: Champion UNDER edge 3-5 hit rate dropped to **27.5%** (week of Feb 1) — catastrophic
- **Light slates**: 1-4 game days showed **20.6% HR** vs 63.9% on medium slates (5-8 games)
- **Star decay**: Stars decayed -36.5pp (75% → 38.5%)

## Solution: Bridge Filters Until Q43 Promotion (~Feb 19-23)

Three protective filters implemented as a bridge while the Q43 quantile model accumulates enough shadow data for promotion.

### Filter 1: Light Slate RED Signal Override

**File:** `predictions/coordinator/signal_calculator.py`

When `slate_size <= 4` (1-4 scheduled games), the daily signal is forced to RED with explanation. This warns users to skip light slate days entirely.

**Mechanism:** CROSS JOIN to `nba_reference.nba_schedule` to count games, added as first CASE condition in `daily_signal` and `signal_explanation`.

### Filter 2: Champion UNDER Dampening

**File:** `predictions/worker/worker.py`

Champion model (`catboost_v9`) UNDER picks with edge < 5 are filtered as non-actionable. This effectively raises the UNDER threshold from 3 to 5 for the champion only.

**Scope:** Champion only. Does NOT affect Q43/Q45 quantile models or OVER picks.

### Filter 3: Star Filter Quantile Exemption

**File:** `predictions/worker/worker.py`

The existing `star_under_bias_suspect` filter (blocks UNDER on stars with edge >= 5) now exempts quantile models (system_id containing `_q4`). Quantile models don't exhibit the same star UNDER bias as the champion.

## Filter Chain (Post-Change)

```
1. confidence_tier_88_90         — All models
2. low_edge (< 3)               — All models
3. stale_model_under_dampening   — Champion only, UNDER, edge < 5 (NEW)
4. star_under_bias_suspect       — Non-quantile only, stars, UNDER, edge >= 5 (MODIFIED)
5. role_player_under_low_edge    — All models (existing)
6. hot_streak_under_risk         — All models (existing)
7. not_quality_ready             — All models (existing)
8. has_default_features          — All models (existing)
```

## Verification Queries

```sql
-- Check champion UNDER dampening
SELECT filter_reason, COUNT(*) FROM nba_predictions.player_prop_predictions
WHERE game_date >= CURRENT_DATE() AND system_id = 'catboost_v9'
GROUP BY 1;

-- Verify Q43/Q45 star UNDERs NOT filtered by star_under_bias_suspect
SELECT system_id, filter_reason, COUNT(*) FROM nba_predictions.player_prop_predictions
WHERE game_date >= CURRENT_DATE() AND system_id LIKE 'catboost_v9_q4%'
  AND recommendation = 'UNDER'
GROUP BY 1, 2;

-- Check slate_size populated in signals
SELECT game_date, daily_signal, slate_size, signal_explanation
FROM nba_predictions.daily_prediction_signals
WHERE game_date >= CURRENT_DATE() - 1;
```

## Rollback Plan

1. Remove `stale_model_under_dampening` filter block in `worker.py`
2. Revert star filter `_q4` exemption in `worker.py`
3. Remove CROSS JOIN + `slate_size` references in `signal_calculator.py`
4. Push to main (auto-deploy). Schema column `slate_size` can remain (nullable).

## Schema Change

```sql
ALTER TABLE `nba-props-platform.nba_predictions.daily_prediction_signals`
ADD COLUMN IF NOT EXISTS slate_size INT64
OPTIONS (description='Number of scheduled games for this date. Session 211.');
```

## Timeline

- **Now (Session 211):** Protective filters deployed
- **~Feb 19-23:** Q43 quantile model promotion (needs 10+ days shadow data)
- **Post-promotion:** Remove champion UNDER dampening (Q43 becomes champion)

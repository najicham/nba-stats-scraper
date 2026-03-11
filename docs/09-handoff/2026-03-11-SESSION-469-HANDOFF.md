# Session 469 Handoff — Health-Aware Weights, Directional Signals, Market Filter

**Date:** 2026-03-11
**Previous:** Session 468b (OVER edge floor 5.0, hot shooting block, discovery tools)

## What Was Done

### 1. Health-Aware Signal Weighting (New System)

Added `_health_multiplier()` method to `BestBetsAggregator`. Composite scoring now applies signal health regime multipliers:

| Regime | Behavioral Signal | Model-Dependent Signal |
|--------|-------------------|------------------------|
| HOT | 1.2x | 1.2x |
| NORMAL | 1.0x | 1.0x |
| COLD | 0.5x | 0.0x |

**Motivation:** `home_under` had 2.0 weight but 33.3% 7d HR (COLD regime). Static weights were boosting bad UNDER picks. Now self-correcting — signals regain full weight when HR recovers.

### 2. Direction-Specific book_disagreement

Split `book_disagreement` into directional variants:

| Signal | Direction | HR | N | Status |
|--------|-----------|-----|---|--------|
| `book_disagree_over` | OVER | 79.6% | 211 | Shadow (weight 3.0 in OVER scoring) |
| `book_disagree_under` | UNDER | — | — | Shadow (weight 1.5 in UNDER scoring) |

Both are in SHADOW_SIGNALS (don't count toward real_sc) while accumulating BB-level data. The original `book_disagreement` signal remains active for backward compatibility.

### 3. Promoted `over_line_rose_heavy` to Active Filter

OVER + BettingPros line rose >= 1.0 → **blocked** (was observation since Session 462).
- 38.9% HR (N=54, 5-season cross-validated)
- Fighting the market is consistently losing

### 4. Deployed v468 Changes (from previous session)

Pushed the previously-uncommitted Session 468b changes:
- OVER edge floor 4.0 → 5.0
- `hot_shooting_over_block` filter

## Implementation Details

| Change | File | Lines |
|--------|------|-------|
| `_health_multiplier()` method | `aggregator.py` | New method on `BestBetsAggregator` |
| Health-aware UNDER composite | `aggregator.py` | `UNDER_SIGNAL_WEIGHTS.get(t) * self._health_multiplier(t)` |
| Health-aware OVER composite | `aggregator.py` | `OVER_SIGNAL_WEIGHTS.get(t) * self._health_multiplier(t)` |
| `book_disagree_over` signal | `book_disagree_over.py` | New file |
| `book_disagree_under` signal | `book_disagree_under.py` | New file |
| Signal registration | `registry.py` | Added both new signals |
| OVER weight: `book_disagree_over: 3.0` | `aggregator.py` | OVER_SIGNAL_WEIGHTS |
| UNDER weight: `book_disagree_under: 1.5` | `aggregator.py` | UNDER_SIGNAL_WEIGHTS |
| Both in SHADOW_SIGNALS | `aggregator.py` | Excluded from real_sc |
| `over_line_rose_heavy` active | `aggregator.py` | Changed from obs to blocking |
| Algorithm version | `pipeline_merger.py` | `v469_health_aware_weights_line_rose_block` |
| Pick angles | `pick_angle_builder.py` | Added entries for both new signals |

### Test Results
- **254 passed, 0 failed** (+18 new tests)
- New test files: `test_book_disagree_directional.py` (9 tests), `test_health_aware_weights.py` (9 tests)

## Current State

### System Health at Deploy Time (Mar 11)

**BB Performance:** 37.5% 7d, 41.2% 14d, 45.7% 30d — prolonged downturn.
**Market:** TIGHT (Vegas MAE 4.43, model gap +0.68)
**COLD signals:** combo_3way, combo_he_ms (model-dep → 0.0x), home_under (behavioral → 0.5x), starter_under, low_line_over
**Bright spots:** HSE 83%, self_creation 78%, b2b_boost 75%, usage_surge 73%
**Rescue:** 50% HR (N=18) vs normal 36.4% — rescue outperforming organics

### Algorithm: `v469_health_aware_weights_line_rose_block`

Changes from v468:
- Health-aware signal weighting in composite scoring
- `book_disagree_over` (weight 3.0) and `book_disagree_under` (weight 1.5) shadow signals
- `over_line_rose_heavy` promoted to active blocking filter
- OVER edge floor 5.0 (from v468)
- `hot_shooting_over_block` (from v468)

### Deployment
- 2 pushes, all builds SUCCESS
- v468: prediction-worker, prediction-coordinator, phase6-export, post-grading-export, live-export
- v469: same 5 services

## Priority Tasks (Next Session)

### P0 — Monitor v469 Performance (CRITICAL)

**Context:** System is in a prolonged downturn — 37.5% 7d HR, 41.2% 14d, 45.7% 30d. v468+v469 deployed today with multiple fixes. 6 games tonight (Mar 11), full slate all week (6-10 games/day through Mar 18).

**Steps:**
1. Run `/daily-steering` to get fresh model health + BB performance
2. Check Mar 11 picks: `SELECT * FROM nba_predictions.signal_best_bets_picks WHERE game_date = '2026-03-11'`
3. Check if new filters fired:
   ```sql
   -- Did over_line_rose_heavy block anything?
   SELECT * FROM nba_predictions.best_bets_filtered_picks
   WHERE game_date = '2026-03-11' AND filter_reason = 'over_line_rose_heavy'

   -- Did hot_shooting_over_block fire?
   SELECT * FROM nba_predictions.best_bets_filtered_picks
   WHERE game_date = '2026-03-11' AND filter_reason = 'hot_shooting_over_block'

   -- Are book_disagree signals firing?
   SELECT signal_tag, COUNT(*) FROM nba_predictions.signal_best_bets_picks,
   UNNEST(signal_tags) AS signal_tag
   WHERE game_date >= '2026-03-11' AND signal_tag LIKE 'book_disagree%'
   GROUP BY 1
   ```
4. Grade Mar 11 results when available (grading runs ~9 AM ET next day)

**Decision gates:**
- v469 HR >= 50% over 3 days → keep
- v469 HR < 40% over 3 days → investigate whether new filters are helping or hurting
- If `over_line_rose_heavy` or `hot_shooting_over_block` blocked a winner → check CF HR

### P1 — Check Weekly Retrain Status (URGENT)

**Context:** 5 of 7 models are LOSING at edge 5+ (14d). The `weekly-retrain` CF fires every Monday 5 AM ET. It should have fired today (Mar 11).

**Steps:**
1. Check if retrain ran:
   ```bash
   gcloud functions logs read weekly-retrain --region=us-west2 --limit=20 --format="table(timestamp,severity,textPayload)" 2>&1
   ```
2. Check for new models in registry:
   ```sql
   SELECT model_id, model_family, created_at, enabled
   FROM nba_predictions.model_registry
   WHERE created_at >= '2026-03-10'
   ORDER BY created_at DESC
   ```
3. If retrain did NOT run, trigger manually: `./bin/retrain.sh --all --enable`
4. If retrain DID run, check governance gates passed:
   ```sql
   SELECT * FROM nba_predictions.model_registry
   WHERE created_at >= '2026-03-10' AND enabled = TRUE
   ```

**Why this matters:** The 37.5% 7d BB HR is partly driven by stale models. Edge 5+ HR across models:
- catboost_v12: 60% PROFITABLE
- v9_low_vegas: 57.1% MARGINAL
- ALL others: 40-50% LOSING
Fresh models with recent data should improve edge 5+ HR.

### P2 — Uncommitted Changes in Working Tree

Two files modified from a previous session are still uncommitted:
- `data_processors/publishing/best_bets_all_exporter.py` (136 lines changed — picks vanish fix from Session 468)
- `docs/02-operations/session-learnings.md` (20 lines — pre-existing entries)

**Action:** Review these changes. If they look correct (the exporter fix for picks vanishing after model disable), commit them:
```bash
git diff data_processors/publishing/best_bets_all_exporter.py  # Review
git add data_processors/publishing/best_bets_all_exporter.py docs/02-operations/session-learnings.md
git commit -m "fix: best_bets_all_exporter reads published_picks as fallback (Session 468)"
git push origin main
```

### P3 — Graduate book_disagree Signals (Check ~Mar 18)

When `book_disagree_over` reaches N >= 30 at BB level with HR >= 60%:
1. Remove `'book_disagree_over'` from `SHADOW_SIGNALS` in `aggregator.py`
2. This allows it to contribute to `real_sc` (currently excluded)
3. Run tests, bump algorithm version, deploy

Query to check readiness:
```sql
SELECT signal_tag, COUNT(*) as n,
  ROUND(100.0 * COUNTIF(pa.prediction_correct) / NULLIF(COUNT(*), 0), 1) as hr
FROM nba_predictions.signal_best_bets_picks bb,
UNNEST(bb.signal_tags) AS signal_tag
JOIN nba_predictions.prediction_accuracy pa
  ON bb.player_lookup = pa.player_lookup AND bb.game_date = pa.game_date AND bb.system_id = pa.system_id
WHERE signal_tag LIKE 'book_disagree%' AND pa.prediction_correct IS NOT NULL
GROUP BY 1
```

### P4 — Investigate starter_under 10.5% 7d HR

`starter_under` is in BASE_SIGNALS (no ranking impact, excluded from real_sc) but still fires for tracking at 10.5% 7d HR (N=21). This is the worst-performing signal by far. It's not directly harming picks, but worth understanding why it collapsed — could indicate a broader market regime shift for starter-tier UNDER.

### P5 — Season-End Planning

NBA regular season ends ~Apr 13. Consider:
- When to stop making picks (last 2 weeks = tanking teams, meaningless games)
- Season autopsy: `/season-autopsy` across full season for cross-day pattern mining
- Model versioning: what to preserve for 2026-27 pre-season

## Key Files

| File | Purpose |
|------|---------|
| `ml/signals/aggregator.py` | Health multiplier, weights, over_line_rose_heavy filter |
| `ml/signals/pipeline_merger.py` | ALGORITHM_VERSION |
| `ml/signals/book_disagree_over.py` | NEW — direction-specific OVER signal |
| `ml/signals/book_disagree_under.py` | NEW — direction-specific UNDER signal |
| `ml/signals/registry.py` | Signal registration |
| `tests/unit/signals/test_health_aware_weights.py` | NEW — health multiplier + filter tests |
| `tests/unit/signals/test_book_disagree_directional.py` | NEW — directional signal tests |

## What NOT to Do
- Don't remove `book_disagreement` (original) — still active, provides backward compatibility
- Don't promote `book_disagree_over`/`under` from SHADOW_SIGNALS until N >= 30 BB data
- Don't manually override health multipliers — the system is self-correcting
- Don't lower OVER floor below 5.0 without 2+ season validation

# Session 161: Model Evaluation Methodology & Subset Health Check

**Date:** 2026-02-08
**Focus:** Resolving the "star player bias" confusion, subset performance audit, pipeline gap analysis

## The Problem

Multiple sessions have reported contradictory findings about model bias:
- Sessions 45, 101, 102: "Stars are under-predicted by 9-11 points, model is broken"
- Session 124: "Stars are fine, bias is +0.1, the measurement was wrong"
- Session 161 daily validation: "Stars at -11.3 bias, 14.8% hit rate"

This kept recurring because the **wrong query was being used** in validation tools.

## Root Cause: Measurement Artifact

### The Wrong Way (tiering by `actual_points`)

```sql
-- DO NOT USE THIS
CASE WHEN actual_points >= 25 THEN 'Stars' ...
```

This classifies players by **what they scored that game**, creating survivorship bias:
- A 20 PPG starter who scores 30 becomes a "star" for that game
- The model correctly predicted ~21, but the query shows "-9 bias"
- By definition, everyone in the "25+ actual" bucket scored high, so predictions always look low

**Session 161 results with wrong method (7 days):**

| Tier (by actual) | Bias | Hit Rate |
|-------------------|------|----------|
| Stars (25+) | -11.3 | 14.8% |
| Starters (15-24) | -5.5 | 33.5% |
| Role (5-14) | +0.7 | 63.4% |
| Bench (<5) | +4.5 | 93.0% |

### The Right Way (tiering by `season_avg`)

```sql
-- USE THIS
WITH player_avgs AS (
  SELECT player_lookup, AVG(actual_points) as season_avg
  FROM nba_predictions.prediction_accuracy
  WHERE system_id = 'catboost_v9' AND game_date >= '2025-11-01'
  GROUP BY 1
)
CASE WHEN season_avg >= 25 THEN 'Stars' ...
```

This classifies players by **what they actually are** (season average), which is what the model sees.

**Session 161 results with correct method (14 days):**

| Tier (by season avg) | Bias | Hit Rate |
|----------------------|------|----------|
| Stars (25+ avg) | -0.3 | 54.8% |
| Starters (15-24 avg) | -2.0 | 51.7% |
| Role (8-14 avg) | -1.3 | 51.1% |
| Bench (<8 avg) | -0.3 | 50.0% |

**With edge >= 3 filter (14 days):**

| Tier (by season avg) | N | Bias | Hit Rate |
|----------------------|---|------|----------|
| Stars (25+ avg) | 31 | -2.6 | 51.6% |
| Starters (15-24 avg) | 121 | -4.0 | 50.4% |
| Role (8-14 avg) | 131 | -2.9 | 54.2% |
| Bench (<8 avg) | 28 | -3.6 | 60.7% |

### The Over/Under Split Explains Everything

Using actual_points tiers, the star OVER vs UNDER split reveals the artifact:

| Stars (by actual) | N | Hit Rate |
|--------------------|---|----------|
| OVER bets | 25 | **92.0%** |
| UNDER bets | 91 | **7.7%** |

Stars by actual points are players who scored high. The model predicted lower (closer to average). So most bets were UNDER (model < line), and since these players scored high, those UNDERs all lost. The few OVER bets (model > line, on players who scored even higher) won overwhelmingly.

This is textbook regression-to-the-mean in the evaluation, not the model.

## Why This Kept Happening

1. The `/validate-daily` skill has model bias checks that use `actual_points` tiers
2. Multiple sessions independently "discovered" this bias using the same wrong query
3. Session 124 documented the fix but the validation skill wasn't updated
4. New sessions ran the old validation and re-raised the same alarm

### Action: Update Validation Skill

The `/validate-daily` skill's Phase 0.466 and Phase 0.55 model bias checks need to be updated to use `season_avg` methodology. See `TIER-BIAS-METHODOLOGY.md` in the `session-124-model-naming-refresh` project directory.

## Breakout Classifier Context

The breakout classifier was NOT added because the model is biased against stars. It was added because:

- **Role player UNDER bets lose money** at 42-45% hit rate
- ~17% of role player games are "breakouts" (1.5x their season average)
- The model's point predictions are well-calibrated for role players (bias -1.3)
- But occasional breakout games make UNDER bets unreliable for this tier
- The classifier flags these risky games so the system can avoid UNDER bets on breakout-risk players

## What Actually Needs Improvement

Based on correct methodology, the model's calibration is good but there are real areas for improvement:

1. **Overall hit rate at 50-55%** — below the 55%+ target, especially for starters
2. **Slight negative bias across all tiers** (-0.3 to -4.0) — model slightly under-predicts everyone
3. **Edge >= 3 filter is critical** — without it, predictions are near-random
4. **Subset filtering adds significant value** (see below)

## Subset Performance Audit

### Season-Long Performance (Jan 9 - Feb 6, 28 dates)

| Subset | Picks | Wins | Hit Rate | ROI |
|--------|-------|------|----------|-----|
| Top 3 | 26 | 23 | **88.5%** | +62.0% |
| Top 5 | 58 | 48 | **82.8%** | +62.9% |
| High Edge OVER | 93 | 77 | **82.8%** | +25.4% |
| Top Pick | 11 | 9 | **81.8%** | +56.2% |
| Green Light | 151 | 113 | **74.8%** | +58.0% |
| Ultra High Edge | 87 | 64 | **73.6%** | +29.0% |
| High Edge All | 213 | 144 | **67.6%** | +35.0% |
| All Picks | 517 | 315 | **60.9%** | +10.2% |

All 8 subsets are profitable. Key insight: **OVER direction filter is the dominant signal** (High Edge OVER 82.8% vs High Edge All 67.6%).

### Subset Data Quality Issues

1. **All data is from backfill** — Every row in `current_subset_picks` was created on 2026-02-08 with `trigger_source = 'backfill'`. This means grading is based on retrospective prediction snapshots, not live pre-game picks.

2. **No data for Feb 7 or Feb 8** — Latest subset picks are from Feb 6. Pipeline was broken (Phase 2→3 orchestrator crash due to missing PyYAML).

3. **No training data contamination risk** — The subset system only reads from `player_prop_predictions` (inference data). It does not affect the V9 training pipeline. Backfilled subset picks don't change predictions or model training.

### Today's Game Coverage

**4 games today (Feb 8):** NYK@BOS (in progress), MIA@WAS, IND@TOR, LAC@MIN

| Game | Predictions | First Created | Pre-Game | Actionable |
|------|------------|---------------|----------|------------|
| NYK @ BOS | 13 active | 15:03 UTC | Mostly yes | 2 (derrickwhite, karlanthonytowns) |
| MIA @ WAS | 7 active | ~17:00 UTC | TBD | TBD |
| IND @ TOR | 14 active | ~17:00 UTC | TBD | TBD |
| LAC @ MIN | 13 active | ~17:00 UTC | TBD | TBD |

**NYK@BOS:** We got predictions ~1 hour before game time (16:58 UTC for most, one at 15:03). However:
- Only 2 of 13 are actionable (edge >= 3)
- No subset picks were materialized (pipeline broken)
- Signal is RED (UNDER_HEAVY), so signal-filtered subsets (Top 3/5, Green Light) would have had zero picks anyway

**We did NOT fully get ahead of this game** — predictions existed but subsets weren't materialized, and the game had almost no actionable picks due to low edges.

## Plan to Improve

### Immediate (This Week)
1. **Update `/validate-daily` skill** — Replace `actual_points` tier queries with `season_avg` methodology
2. **Monitor Phase 2→3 trigger** — Fixed in Session 161 (PyYAML). Verify it fires on next game day.
3. **Backfill subset picks for Feb 7-8** — Run after pipeline stabilizes

### Short-Term (Next 2 Weeks)
4. **Ensure subsets materialize daily** — The SubsetMaterializer should run every time Phase 5→6 triggers. Verify it's in the orchestrator's export types.
5. **Add pre-game timing validation** — Alert if predictions aren't materialized N hours before first tip.
6. **V9 February retrain** — Address the slight negative bias (-2 to -4) with updated training data.

### Medium-Term
7. **Breakout classifier V3** — Add contextual features (star_teammate_out, fg_pct_last_game) to improve high-confidence predictions.
8. **Evaluate OVER-only strategy** — The OVER direction filter is the strongest signal (82.8%). Consider whether UNDER bets add or subtract value.

## Reference

- Session 124 methodology: `docs/08-projects/current/session-124-model-naming-refresh/TIER-BIAS-METHODOLOGY.md`
- Subset redesign (Session 154): `docs/08-projects/current/subset-redesign/00-SUBSET-REFERENCE.md`
- Model bias investigation: `docs/08-projects/current/feature-mismatch-investigation/MODEL-BIAS-INVESTIGATION.md`
- Breakout classifier: See CLAUDE.md [Keyword: BREAKOUT]

---
*Session 161 — Co-Authored-By: Claude Opus 4.6*

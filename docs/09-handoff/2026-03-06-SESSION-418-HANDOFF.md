# Session 418 Handoff — Pipeline Fixes + Player Profile Signals Shipped

**Date:** 2026-03-06 (morning)
**Type:** Pipeline fixes, signal implementation, daily ops
**Builds on:** Session 417 (player deep dive research)

---

## What This Session Did

### 1. Fixed Broken Pipeline (P0)

#### model_performance_daily stuck at Mar 2
- **Root cause:** Session 417's `brier_stats` comma fix was committed (`7877212a`) but `post-grading-export` CF hadn't redeployed until this session's push triggered auto-deploy.
- **Fix:** Manually backfilled Mar 3-5: `PYTHONPATH=. python ml/analysis/model_performance.py --backfill --start 2026-03-03` — wrote 143 rows.
- **Status:** Fixed. Auto-deploy now has the correct code. Next scheduled run should succeed.

#### Grading service bugs
- `game_datetime_utc` column doesn't exist in `nba_schedule` → fixed to `CAST(MIN(game_date) AS TIMESTAMP)` in `subset_grading_processor.py:240`
- `shared/validation/__init__.py` eagerly imported `scraper_config_validator` which requires `yaml` (missing in grading CF runtime) → fixed with lazy `__getattr__` imports

#### Grading completion rate (NOT a new issue)
- Grading completion declining: 41% (Feb 20) → 7% (Mar 5) across full fleet
- **Best bets picks ARE graded** (11/13 on Mar 5) — the grading service prioritizes differently
- Not urgent but worth investigating if it degrades further

### 2. Implemented Player Profile Signals (P4)

Three new signal/filter additions based on Session 417's research findings:

| Signal | Type | Trigger | Backtest HR | N | Mode |
|--------|------|---------|-------------|---|------|
| `bounce_back_over` | Positive | Bad miss (<70% of line) + AWAY + model OVER | 56.2% raw, 60%+ with model | 379-700 | SHADOW |
| `over_streak_reversion_under` | Positive | 4+ overs in last 5 games + model UNDER | 56% UNDER | 366 | SHADOW |
| `under_after_streak` | Negative filter | 3+ consecutive unders + model UNDER + edge < 5.0 | 44.7% (anti-signal) | 515 | **ACTIVE** |

**Key insight behind these:** Our model has a blind spot on streak players. After 3 consecutive unders, it calls UNDER 2.4x more than OVER — but those UNDER calls only hit 44.7%. The bounce-back overwhelms the model's trend-chasing.

#### Infrastructure added
- `prev_game_context` CTE in `supplemental_data.py` — fetches each player's most recent game stats (points, line, FG%, ratio, minutes) from `player_game_summary`
- `prop_over_streak` (f53) and `over_rate_last_10` (f55) added to `book_stats` CTE
- All wired through `_enrich_pred()` as: `prev_game_ratio`, `prev_game_fg_pct`, `prev_game_points`, `prev_game_line`, `prev_game_minutes`, `prop_over_streak`, `over_rate_last_10`

### 3. Committed Session 417 Work

- `bin/analysis/player_deep_dive.py` — 9-module player analysis tool
- `docs/08-projects/current/player-deep-dive/` — 5 docs (overview, Curry findings, systematization plan, signal findings, implementation plan)
- Full research: 10 exploitable findings from player scoring distributions
- Cross-season stability: over/under rates r=0.14 (NOT stable), variance r=0.64 (STABLE)

### 4. Daily Steering Report

#### Best Bets Performance
| Period | W-L | HR |
|--------|-----|-----|
| Last 7d | 15-10 | 60.0% |
| Last 14d | 23-14 | 62.2% |
| Last 30d | 36-26 | 58.1% |

**Yesterday (Mar 5): 8-3 (72.7%)** — best day in weeks.

#### Market Regime — All GREEN
| Metric | Value | Status |
|--------|-------|--------|
| Compression | 1.000 | GREEN |
| 7d avg max edge | 6.4 | YELLOW |
| OVER 14d | 60.9% (N=23) | GREEN |
| UNDER 14d | 64.3% (N=14) | GREEN |
| Direction divergence | 3.4pp | GREEN |
| Residual bias | -0.2 pts | GREEN |

#### Model Health (as of Mar 5 after backfill)
- 4 HEALTHY, 1 WATCH, 2 DEGRADING, 11+ BLOCKED
- Best performers: lgbm_v12_noveg_train1201 (71.4% 7d), catboost_v12_noveg_60d_vw025 (66.7%)
- Base catboost_v12: BLOCKED (49.2% 7d)

#### Today's Picks (Mar 6)
Only 1 pick generated: **Jerami Grant UNDER 19.5** (edge 3.2, signals: starter_under, projection_consensus_under, blowout_risk_under)

---

## Files Changed

| File | Changes |
|------|---------|
| `ml/signals/bounce_back_over.py` | **NEW** — bounce-back OVER signal |
| `ml/signals/over_streak_reversion_under.py` | **NEW** — over-streak reversion UNDER signal |
| `ml/signals/supplemental_data.py` | Added `prev_game_context` CTE, `prop_over_streak`, `over_rate_last_10` |
| `ml/signals/registry.py` | Registered 2 new signals (51 total) |
| `ml/signals/aggregator.py` | Added `under_after_streak` active filter |
| `ml/signals/pick_angle_builder.py` | Added angle templates for 2 new signals |
| `data_processors/grading/subset_grading/subset_grading_processor.py` | Fixed `game_datetime_utc` → `game_date` |
| `shared/validation/__init__.py` | Lazy imports to avoid yaml dependency |
| `bin/analysis/player_deep_dive.py` | **NEW** — 9-module player analysis tool |
| `docs/08-projects/current/player-deep-dive/` | **NEW** — 5 research docs |
| `docs/09-handoff/2026-03-06-SESSION-417-HANDOFF.md` | Session 417 handoff |

## Commits

```
770d6007 feat: player profile signals — bounce_back_over, over_streak_reversion, under_after_streak filter
cb94f1b1 fix: grading bugs — game_datetime_utc missing column, yaml lazy import
362eb482 feat: player deep dive analysis tool and signal discovery
```

---

## What's Deploying

All 3 commits pushed to main. Cloud Build auto-deploys triggered (5 builds). Key services affected:
- **prediction-worker** — new signals + supplemental data changes
- **nba-scrapers** — was 5 commits behind, now current
- **Cloud Functions** — grading fixes + post-grading-export brier_stats fix

---

## Monitoring Dates

| What | Review Date | Criteria |
|------|-------------|----------|
| `bounce_back_over` shadow | Mar 19 | HR >= 55% at N >= 30 → promote |
| `over_streak_reversion_under` shadow | Mar 19 | HR >= 55% at N >= 30 → promote |
| `under_after_streak` filter | Mar 19 | Counterfactual HR — verify blocked picks are losers |
| `blowout_risk_under` | Mar 13 | 16.7% signal HR, 50% BB HR (N=4). Demote to obs if BB HR < 50% at N >= 10 |
| `starter_under` | Mar 13 | 38.7% signal HR, 66.7% BB HR (N=3). Same criteria |
| Rescue cap review | Mar 12 | HR < 55% → tighten, > 60% → loosen |

---

## Priority Actions for Next Session

### P1: Grade Mar 5 Late Games
2 best bets picks from Mar 5 still ungraded (Nolan Traore, Cody Williams — late games). Check if grading has caught up.

### P2: Verify Signal Deployment
After builds complete, check Cloud Run logs for:
- `bounce_back_over` and `over_streak_reversion_under` appearing in signal evaluation
- `under_after_streak` filter counting in aggregator logs
- `prev_game_context` data loading without errors

```bash
# Check worker logs after deployment
gcloud run services logs read prediction-worker --region=us-west2 --limit=50 2>&1 | grep -E "bounce_back|under_after_streak|over_streak|prev_game"
```

### P3: Batch Player Deep Dives
Run `player_deep_dive.py` for all 262 players with 50+ graded predictions.

```bash
bq query --format=csv "SELECT player_lookup FROM (
  SELECT player_lookup, COUNT(*) as n
  FROM nba_predictions.prediction_accuracy
  WHERE game_date >= '2025-10-01' AND has_prop_line = TRUE AND prediction_correct IS NOT NULL
  GROUP BY 1 HAVING COUNT(*) >= 50
) ORDER BY n DESC" | tail -n +2 | while read player; do
  python bin/analysis/player_deep_dive.py "$player" --output "results/player_profiles/${player}.md"
done
```

### P4: Implement Remaining P1 Signals (from Session 417 plan)
Still planned but not yet built:
- `bad_shooting_bounce_over` — FG% < 35% last game → 54.5% over next (N=220). Needs `prev_game_fg_pct` (already wired).
- Tier-based direction preferences — Star=UNDER (59.2%), Starter=OVER (61.1%), Role=UNDER (60.0%). Needs player tier classification.

### P5: Investigate Grading Completion Rate
Declining from 41% → 7% across fleet. Best bets are graded but fleet-wide metrics increasingly stale. Low priority unless BB grading degrades.

---

## Key Context for Continuing

- **Algorithm version:** `v418_player_profiles` — 3 changes from this session
- **Signal count:** 51 registered (28 active + 22 shadow), 19 active + 1 obs negative filters
- **Market regime:** All GREEN, no compression. System performing well (62.2% 14d).
- **Player deep dive research:** Full findings in `docs/08-projects/current/player-deep-dive/03-SIGNAL-FINDINGS.md`
- **Implementation plan:** Remaining items in `docs/08-projects/current/player-deep-dive/04-IMPLEMENTATION-PLAN.md`
- **win_flag always FALSE:** `player_game_summary.win_flag` is broken for ALL data. Use `plus_minus > 0`.
- **is_dnp NULL for old records:** Always filter `(is_dnp IS NULL OR is_dnp = FALSE)`.

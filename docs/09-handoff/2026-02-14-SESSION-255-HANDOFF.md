# Session 255 Handoff — Signal Exploration + Best Bets Production Setup

**Date:** 2026-02-14
**Model:** Claude Opus 4.6
**Status:** Code complete. BQ tables created + backfilled. Pushed to main.

---

## What Was Done

### 1. Signal Exploration — Tested 4, Accepted 2

Explored new signal ideas for the Signal Discovery Framework. Each signal is a class in `ml/signals/` that evaluates predictions and returns a qualify/no-qualify verdict.

**Accepted:**
- **`cold_snap`** (`ml/signals/cold_snap.py`) — Player went UNDER their points line 3+ consecutive games. Regression to mean suggests OVER. **64.3% HR** across two eval windows (W3, W4). Decay-resistant: held at 64.3% even during W4 model decay when `high_edge` crashed to 43.9%.
- **`blowout_recovery`** (`ml/signals/blowout_recovery.py`) — Player's previous game minutes were 6+ below their season average (blowout, foul trouble, etc.). Bounce back OVER. **56.4% HR** across 121 picks, profitable in every window including W4 decay.

**Rejected (files kept with STATUS: REJECTED in docstring):**
- **`hot_streak`** (`ml/signals/hot_streak.py`) — Model correct 3+ consecutive games. **47.5% HR** — below 52.4% breakeven. Segmented analysis showed no profitable player tier (Stars 42.1%, Mid 50.0%, Role 49.5%). Model rolling features already capture momentum.
- **`rest_advantage`** (`ml/signals/rest_advantage.py`) — 3+ days since last game. **50.8% HR** — essentially breakeven. W2 looked promising (60.2%) but collapsed in W3/W4. Market prices rest efficiently.

**Segmentation analysis tool:** `ml/experiments/signal_segment_analysis.py`

### 2. Best Bets Subset — Renamed + Production Tables

- **Renamed** "Signal Picks" (id=26) to **"Best Bets"** everywhere:
  - `shared/config/subset_public_names.py`: key `signal_picks` -> `best_bets`, name "Best Bets"
  - `data_processors/publishing/signal_annotator.py`: `SIGNAL_PICKS_SUBSET_ID = 'best_bets'`
- **No naming conflict** with existing subset display names
- **GCS path note:** Signal best bets export uses `v1/signal-best-bets/{date}.json`. The legacy `best_bets_exporter.py` uses `v1/best-bets/{date}.json`. Both coexist. Frontend migration to point at `v1/signal-best-bets/` is a separate task.

### 3. Production Supplemental Data

Added queries to `ml/signals/supplemental_data.py` so cold_snap and blowout_recovery work in production:
- **Streak data CTE** (from `prediction_accuracy`): LAG values for prior 5 games' actual over/under outcomes
- **`prev_minutes`** (from `player_game_summary` via `latest_stats`): previous game minutes for blowout_recovery
- **`rest_days`** (computed as DATE_DIFF from latest game): days since player's last game

### 4. BQ Tables Created + Backfilled

**Tables created (already done, do NOT re-run):**
```sql
nba_predictions.pick_signal_tags           -- Signal annotations on ALL predictions
nba_predictions.signal_best_bets_picks     -- Curated top 5 best bets per day
nba_predictions.v_signal_performance       -- View: per-signal hit rate and ROI
```

**Subset definition inserted (already done, do NOT re-insert):**
```sql
INSERT INTO nba_predictions.dynamic_subset_definitions
(subset_id, subset_name, system_id, is_active, min_edge, top_n, use_ranking)
VALUES ('best_bets', 'Best Bets', 'catboost_v9', TRUE, 0, 5, TRUE)
```

**Backfill completed:**
- 35 dates (2026-01-09 to 2026-02-12)
- 2,130 predictions annotated in `pick_signal_tags`
- 120 best bets picks in `signal_best_bets_picks` (24 dates with healthy model)
- Model health gate correctly blocked Feb 3-12 (decay period)

---

## Key Numbers

| Metric | Value |
|--------|-------|
| **Best Bets overall HR** | **67.8%** (80/118 graded picks) |
| **Best Bets dates** | 24 (model-healthy days only) |
| cold_snap HR (30d view) | 61.1% (18 picks) |
| blowout_recovery HR (30d view) | 54.6% (97 picks) |
| 3pt_bounce HR (30d view) | 62.5% (16 picks) |
| Baseline V9 edge 3+ HR | 59.1% |
| Breakeven at -110 | 52.4% |

---

## What's NOT Done

### Review Remaining Prototype Signals

`build_default_registry()` has 21 signals total (8 core + 13 remaining prototypes). Two harmful prototypes were already removed from the registry this session:
- `prop_value_gap_extreme` — 12.5% HR, -76.1% ROI (REMOVED, file marked REJECTED)
- `edge_spread_optimal` — 47.4% HR, -9.4% ROI (REMOVED, file marked REJECTED)

The remaining 13 prototypes mostly had 0 qualifying picks during backfill (missing supplemental data like player_tier, is_home, FG% stats). They're harmless but untested. Next session should add missing supplemental data and evaluate them, or remove any that can't be tested.

### Cloud Function Redeploy

These Cloud Functions need redeploying to activate the signal pipeline:
- `post-grading-export` (backfills actuals into `signal_best_bets_picks`)
- `phase5-to-phase6-orchestrator` (added `signal-best-bets` to export types)

### Frontend Integration

The Best Bets subset needs its own section on playerprops.io, separate from the regular subset picker.

**API endpoint:** `v1/signal-best-bets/{date}.json`

JSON format:
```json
{
  "date": "2026-02-14",
  "model_health": {"status": "healthy", "hit_rate_7d": 58.3, "graded_count": 45},
  "picks": [
    {
      "rank": 1,
      "player": "Player Name",
      "player_lookup": "player_lookup_key",
      "team": "LAL",
      "opponent": "BOS",
      "prediction": 24.5,
      "line": 20.5,
      "direction": "OVER",
      "edge": 4.0,
      "signals": ["high_edge", "blowout_recovery"],
      "signal_count": 2,
      "composite_score": 0.625
    }
  ],
  "total_picks": 5,
  "signals_evaluated": ["high_edge", "3pt_bounce", "minutes_surge", "cold_snap", "blowout_recovery"]
}
```

**Signal badge display names:**
| Tag | Display Name | Description |
|-----|-------------|-------------|
| `high_edge` | High Edge | Model edge 5+ points |
| `3pt_bounce` | 3PT Bounce | Cold 3PT shooter due for regression |
| `minutes_surge` | Minutes Surge | Getting significantly more playing time |
| `cold_snap` | Cold Snap | Went UNDER 3+ straight, due for OVER |
| `blowout_recovery` | Blowout Recovery | Low minutes last game, bounce back |

**Model health indicator:** When `model_health.status = 'blocked'`, show "No picks today" instead of empty list.

**Performance display queries:**
```sql
-- Daily Best Bets performance
SELECT game_date, COUNT(*) AS picks,
  COUNTIF(prediction_correct) AS wins,
  COUNT(*) - COUNTIF(prediction_correct) AS losses,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) AS hit_rate
FROM nba_predictions.signal_best_bets_picks
WHERE game_date >= '2026-01-09' AND prediction_correct IS NOT NULL
GROUP BY game_date ORDER BY game_date;

-- Weekly rolling performance
SELECT DATE_TRUNC(game_date, WEEK) AS week,
  COUNT(*) AS picks,
  COUNTIF(prediction_correct) AS wins,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) AS hit_rate,
  ROUND(100.0 * (COUNTIF(prediction_correct) * 100
    - (COUNT(*) - COUNTIF(prediction_correct)) * 110) / (COUNT(*) * 110), 1) AS roi
FROM nba_predictions.signal_best_bets_picks
WHERE prediction_correct IS NOT NULL
GROUP BY 1 ORDER BY 1;

-- Per-signal performance (30d rolling)
SELECT * FROM nba_predictions.v_signal_performance ORDER BY hit_rate DESC;

-- Best Bets with full details
SELECT game_date, rank, player_name, team_abbr, opponent_team_abbr,
  predicted_points, line_value, recommendation, edge, signal_tags,
  actual_points, prediction_correct
FROM nba_predictions.signal_best_bets_picks
WHERE game_date >= '2026-01-09'
ORDER BY game_date DESC, rank;
```

---

## Files Changed

### Modified
| File | Change |
|------|--------|
| `shared/config/subset_public_names.py` | `signal_picks` -> `best_bets`, "Best Bets" |
| `data_processors/publishing/signal_annotator.py` | `SIGNAL_PICKS_SUBSET_ID = 'best_bets'` |
| `ml/signals/registry.py` | Added ColdSnapSignal, BlowoutRecoverySignal + prototypes |
| `ml/signals/supplemental_data.py` | Added streak, prev_minutes, rest_days queries |
| `ml/experiments/signal_backtest.py` | Added streak_data CTE, rest/recovery wiring |
| `docs/08-projects/current/signal-discovery-framework/01-BACKTEST-RESULTS.md` | Full update |
| `docs/08-projects/current/signal-discovery-framework/02-ARCHITECTURE.md` | Updated naming + checklist |
| `docs/02-operations/system-features.md` | Added Signal Framework section |
| `ml/experiments/quick_retrain.py` | Added --min-ppg, --max-ppg, --lines-only-train (Session 253) |

### Created
| File | Purpose |
|------|---------|
| `ml/signals/cold_snap.py` | ACCEPTED signal (64.3% HR) |
| `ml/signals/blowout_recovery.py` | ACCEPTED signal (56.4% HR) |
| `ml/signals/hot_streak.py` | REJECTED signal (documented, 47.5% HR) |
| `ml/signals/rest_advantage.py` | REJECTED signal (documented, 50.8% HR) |
| `ml/experiments/signal_backfill.py` | Backfill script for historical signal annotations |
| `ml/experiments/signal_segment_analysis.py` | Player tier segmentation analysis |

### BQ Tables (already created, do not re-run)
| Table | Status |
|-------|--------|
| `nba_predictions.pick_signal_tags` | Created + backfilled (2,130 rows) |
| `nba_predictions.signal_best_bets_picks` | Created + backfilled (120 rows) |
| `nba_predictions.v_signal_performance` | View created |
| `dynamic_subset_definitions` row `best_bets` | Inserted |

---

## Best Bets Performance Over Time

Run this query to see how picks performed day by day:

```sql
SELECT
  game_date,
  COUNT(*) AS picks,
  COUNTIF(prediction_correct) AS wins,
  COUNT(*) - COUNTIF(prediction_correct) AS losses,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) AS hit_rate,
  ROUND(100.0 * (COUNTIF(prediction_correct) * 100
    - (COUNT(*) - COUNTIF(prediction_correct)) * 110) / (COUNT(*) * 110), 1) AS roi,
  -- Cumulative
  SUM(COUNTIF(prediction_correct)) OVER (ORDER BY game_date) AS cum_wins,
  SUM(COUNT(*)) OVER (ORDER BY game_date) AS cum_picks,
  ROUND(100.0 * SUM(COUNTIF(prediction_correct)) OVER (ORDER BY game_date)
    / SUM(COUNT(*)) OVER (ORDER BY game_date), 1) AS cum_hit_rate
FROM nba_predictions.signal_best_bets_picks
WHERE prediction_correct IS NOT NULL
GROUP BY game_date
ORDER BY game_date;
```

Weekly summary:
```sql
SELECT
  DATE_TRUNC(game_date, WEEK(MONDAY)) AS week_start,
  COUNT(*) AS picks,
  COUNTIF(prediction_correct) AS wins,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) AS hit_rate,
  ROUND(100.0 * (COUNTIF(prediction_correct) * 100
    - (COUNT(*) - COUNTIF(prediction_correct)) * 110) / (COUNT(*) * 110), 1) AS roi
FROM nba_predictions.signal_best_bets_picks
WHERE prediction_correct IS NOT NULL
GROUP BY 1 ORDER BY 1;
```

---

## Dead Ends (Don't Revisit)

| Signal | Why It Failed | Session |
|--------|---------------|---------|
| `hot_streak` | 47.5% HR. Model features capture momentum. No segment profitable. | 255 |
| `rest_advantage` | 50.8% HR. Market prices rest efficiently. Inconsistent. | 255 |
| `prop_value_gap_extreme` | 12.5% HR, -76.1% ROI. Extreme edge = model error, not market inefficiency. | 255 |
| `edge_spread_optimal` | 47.4% HR, -9.4% ROI. Confidence band filtering doesn't add value. | 255 |
| `pace_up` | 0 qualifying picks. Threshold too restrictive. | 254 |
| Edge Classifier (Model 2) | AUC < 0.50. Pre-game features can't discriminate edges. | 230 |

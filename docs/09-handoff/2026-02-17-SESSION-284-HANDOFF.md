# Session 284 Handoff — Production Implementation of Replay Findings

**Date:** 2026-02-17
**Focus:** Deploy season replay findings to production before games resume Feb 19

---

## What Was Done

### 1. Player Blacklist (NEW: `ml/signals/player_blacklist.py`)
- `compute_player_blacklist()` queries `prediction_accuracy` for season-to-date per-player win/loss stats
- Thresholds: `min_picks=8`, `hr_threshold=40.0` (strict less-than: exactly 40% = NOT blacklisted)
- Non-blocking: catches all exceptions, returns empty set on failure
- Logs summary (N evaluated, N blacklisted, top 5 worst)
- Season replay proved **+$10,450 P&L** improvement

### 2. Avoid-Familiar Filter
- Players with 6+ games vs their current opponent are excluded from best bets
- Added `_query_games_vs_opponent()` helper in exporter — queries season game counts from `player_game_summary`
- Enriches prediction dicts with `games_vs_opponent` field before passing to aggregator
- Season replay proved **+$1,780 P&L** improvement when stacked with other filters

### 3. Removed rel_edge>=30% Filter
- Previously blocked picks where |edge|/line >= 30%
- Season replay showed this was blocking picks with **62.8% combined HR** (above breakeven)
- In 2025-26 specifically, it blocked **65.5% HR** picks — our best tier
- Comment left in code explaining removal rationale

### 4. High-Conviction Edge>=5 Angle
- Added `_high_conviction_angle()` to `ml/signals/pick_angle_builder.py`
- Picks with edge >= 5 now get angle: "High conviction: edge X.X pts (65.6% HR at edge 5+)"
- Positioned as #2 priority angle (after confidence, before subset membership)

### 5. JSON Output Metadata
- `player_blacklist` field added to signal-best-bets JSON:
  - `count`, `evaluated`, `hr_threshold`, `min_picks`, `players` (top 10 worst)

### 6. Algorithm Version Bump
- `ALGORITHM_VERSION = 'v284_blacklist_familiar_reledge'`

---

## Files Changed

| File | Change |
|------|--------|
| `ml/signals/player_blacklist.py` | **NEW** — compute_player_blacklist() |
| `ml/signals/aggregator.py` | Added blacklist + avoid-familiar filters, removed rel_edge |
| `data_processors/publishing/signal_best_bets_exporter.py` | Added blacklist, games_vs_opponent, JSON metadata |
| `ml/signals/pick_angle_builder.py` | Added high-conviction edge>=5 angle |
| `ml/signals/__init__.py` | Added compute_player_blacklist export |
| `tests/unit/signals/__init__.py` | **NEW** — test package |
| `tests/unit/signals/test_player_blacklist.py` | **NEW** — 23 tests |
| `docs/09-handoff/START-NEXT-SESSION-HERE.md` | Updated with session 284 status |

---

## Aggregator Filter Pipeline (Current Order)

1. **Player blacklist** — <40% HR on 8+ edge-3+ picks (Session 284)
2. **Signal count floor** — MIN_SIGNAL_COUNT=2 (Session 259)
3. **Confidence floor** — model-specific, e.g. V12 >= 0.90 (Session 260)
4. **Feature quality floor** — quality < 85 skip (Session 278)
5. **Bench UNDER block** — UNDER + line < 12 skip (Session 278)
6. **Avoid familiar** — 6+ games vs opponent skip (Session 284)
7. **ANTI_PATTERN combo block** — from combo registry (Session 259)

**Removed:** rel_edge>=30% (Session 284 — was blocking 62.8% HR picks)

---

## Tests

```bash
# Run all 23 tests
PYTHONPATH=. pytest tests/unit/signals/test_player_blacklist.py -v

# Test classes:
# - TestComputePlayerBlacklist (11 tests) — blacklist computation
# - TestAggregatorBlacklistIntegration (4 tests) — aggregator respects blacklist
# - TestAvoidFamiliarFilter (4 tests) — games_vs_opponent filter
# - TestRelEdgeFilterRemoved (1 test) — high rel_edge no longer blocked
# - TestHighConvictionAngle (3 tests) — edge>=5 angle in pick builder
```

---

## Also Implemented (Commit 3)

| Item | P&L Impact | Change |
|------|-----------|--------|
| 42-day rolling training window | +$5,370 | `bin/retrain.sh` — `ROLLING_WINDOW_DAYS=42` replaces fixed start |
| 7-day retrain cadence | +$7,670 | `retrain_reminder/main.py` — thresholds 7/10/14 (was 10/14/21) |
| V12 quantile min edge to 4 | HR +5.1pp | `catboost_monthly.py` — quantile models use edge >= 4 |

---

## Verification (Feb 19)

1. Push to main (auto-deploys)
2. On Feb 19, check `v1/signal-best-bets/{date}.json`:
   - `player_blacklist.count` > 0 (players being blocked)
   - `algorithm_version` = `v284_blacklist_familiar_reledge`
   - `angles` contain "High conviction" for edge>=5 picks
3. Monitor: are blacklisted players truly losing? Check with:
   ```sql
   SELECT player_lookup, hit_rate, total_picks
   FROM ... -- blacklist query from player_blacklist.py
   ```

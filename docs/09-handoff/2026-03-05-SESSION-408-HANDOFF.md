# Session 408 Handoff — pace_v1 Experiment (DEAD END) + TeamRankings Scraper Fix

**Date:** 2026-03-05
**Type:** Feature experiment, scraper bug fix, infrastructure improvement
**Commits:** `d8daa4af`, `92a2beb9`

---

## What This Session Did

### 1. Built & Ran pace_v1 Experiment (DEAD END)

Executed the first entry in the experiment grid: `pace_v1` — TeamRankings team pace and efficiency features.

**Part A (pace-only, 3 features):**
- Backfilled 43,881 rows (14,627 player-games x 3 features)
- 5-seed evaluation: avg 74.8% HR(3+) (n≈14), but same-seed baseline comparison shows **-18.2pp HR(3+)**
- All 3 pace features <1% importance in every seed — model ignores them
- **Root cause:** Redundant with existing Phase 3 features (f7: pace_score, f14: opponent_pace, f22: team_pace)

**Part B (full, 5 features incl. efficiency):**
- Fixed TeamRankings scraper to capture efficiency data (see below)
- Backfilled 73,135 rows (14,627 x 5 features)
- 5-seed evaluation: same-seed comparison shows **+0.0pp HR(3+)**
- Efficiency features also <1% importance — seasonal averages don't add signal

**Verdict:** All 5 TeamRankings features are dead ends. Added to `model-dead-ends.md`. Skip `pace_x_tracking_v1` experiment (both components dead).

### 2. Fixed TeamRankings Efficiency Scraper

**Bug:** `teamrankings_stats.py:251` validated efficiency with `90 <= val <= 130`, but TeamRankings reports per-possession values (e.g., `1.176`), not per-100 (e.g., `117.6`). All efficiency values silently rejected.

**Fix:** Changed range to `0.5 <= val <= 2.0`, multiply by 100 for conventional format.

**Verification:** 30/30 teams now have all 3 stats (pace, offensive_efficiency, defensive_efficiency). Example: BOS off=116.2, def=108.7.

### 3. Improved Backfill Infrastructure

| Fix | Detail |
|-----|--------|
| NaN filtering | `_write_rows()` now filters NaN values (pandas NULL→NaN passes `is not None`) |
| `--no-clear` flag | Skips DELETE when BQ streaming buffer blocks (90-min window) |
| GROUP BY dedup | Query uses `MAX()` aggregation to handle multiple scrapes/day |

### 4. Experiment Grid Established

Updated `docs/08-projects/current/model-evaluation-and-selection/EXPERIMENT-GRID.md` with:
- Full results for pace_v1 (both Part A and Part B)
- Execution protocol (backfill → verify → 5-seed → compare)
- Decision criteria (promote signal ≥2pp, production feature ≥3pp, dead end <1pp)
- Known constraints and dead ends registry

---

## What Still Needs Investigation (Next Session)

### P0: Verify Worker Fix from Session 407
The worker crash fix was deployed but we haven't verified predictions are flowing:
```sql
SELECT system_id, COUNT(*) FROM nba_predictions.player_prop_predictions
WHERE game_date >= CURRENT_DATE() - 1
GROUP BY 1 ORDER BY 2 DESC
```

### P1: Combo Signals Stopped Firing (88.2% HR!)
`combo_3way` and `combo_he_ms` have 88.2% HR (15-2) but stopped firing after Feb 11. Need to investigate why minutes_surge threshold isn't qualifying.

### P1: Pick Volume (2/day, target 4-8)
Critically low. Edge compression + strict filters = few picks. Monitor as post-ASB recovery continues.

### P2: Next Experiments (Tier 2, ~Apr 5)
Need ~30 days of daily-varying data accumulation before running:
- **`projections_v1`** — HIGHEST priority. projection_delta is daily-varying, directional, independent source.
- **`sharp_money_v1`** — VSiN betting splits (game-level applied to players)
- **`dvp_v1`** — Defense-vs-position (semi-static)

### P2: Shadow Signal Status
| Signal | Status | Action |
|--------|--------|--------|
| projection_consensus | Ready (single-source NF) | Verify firing after worker fix |
| predicted_pace_over | Firing (2x Mar 4) | Monitor |
| sharp_money/dvp_favorable | Not firing | Investigate thresholds |
| combo_3way/he_ms | Stopped Feb 11 | **Investigate minutes_surge** |

### P3: Fleet Diversity Problem
All 145 model pairs r ≥ 0.95. Zero diversity. Fundamental limit of same-feature training.

---

## Files Changed

| File | Change |
|------|--------|
| `scrapers/external/teamrankings_stats.py:251` | Fix efficiency range (0.5-2.0, *100) |
| `bin/backfill_experiment_features.py` | NaN filter, --no-clear, GROUP BY dedup |
| `docs/08-projects/current/model-evaluation-and-selection/EXPERIMENT-GRID.md` | Full results |
| `docs/06-reference/model-dead-ends.md` | Added pace+efficiency, tracking stats |

---

## Key Numbers

| Metric | Value | Notes |
|--------|-------|-------|
| pace_v1 pace-only HR(3+) delta | -18.2pp (same-seed) | DEAD END |
| pace_v1 full HR(3+) delta | +0.0pp (same-seed) | DEAD END |
| Feature importance (all 5) | <1% every seed | Model ignores them |
| TeamRankings efficiency coverage | 30/30 teams | Scraper fixed |
| Experiment table rows | ~117K | pace_v1 data in BQ |
| Auto-deploy | SUCCESS | nba-scrapers + 2 services |

---

## Don't Do

- Don't re-test pace features — thoroughly dead across 10 seeds
- Don't test pace_x_tracking_v1 — both components are dead ends
- Don't run Tier 2 experiments yet — need 30 days data accumulation (~Apr 5)
- Don't add features to production feature store — use experiment table only
- Don't remove negative filters — they add +13.7pp value

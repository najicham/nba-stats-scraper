# Session 284 Handoff — Production Implementation of Replay Findings

**Date:** 2026-02-17
**Focus:** Deploy ALL 6 season replay findings to production before games resume Feb 19
**Commits:** 6 (all pushed, auto-deploying via Cloud Build)

---

## What Was Done (6 Commits)

### Commit 1: Player Blacklist (`ml/signals/player_blacklist.py` — NEW)
- `compute_player_blacklist()` queries `prediction_accuracy` for season-to-date per-player stats
- Thresholds: `min_picks=8`, `hr_threshold=40.0` (strict `<`: exactly 40% = NOT blacklisted)
- Non-blocking: catches all exceptions, returns empty set on failure
- Season replay proved **+$10,450 P&L** improvement

### Commit 2: Avoid-Familiar + Rel_Edge Removal + High-Conviction Angle
- **Avoid-familiar filter:** players with 6+ games vs opponent → skip (+$1,780 P&L)
- **Removed rel_edge>=30% filter:** was blocking 62.8% HR picks (above breakeven)
- **High-conviction edge>=5 angle:** "65.6% HR at edge 5+" in pick angle builder
- `ALGORITHM_VERSION = 'v284_blacklist_familiar_reledge'`

### Commit 3: Retrain Cadence + Rolling Window + V12 Edge
- `bin/retrain.sh`: `ROLLING_WINDOW_DAYS=42` replaces fixed `TRAINING_START` (+$5,370 P&L)
- `retrain_reminder/main.py`: thresholds 7/10/14d (was 10/14/21) for 7-day cadence (+$7,670 P&L)
- `catboost_monthly.py`: V12 quantile models use `edge >= 4` (HR +5.1pp)

### Commit 4: CLAUDE.md Updates
- Updated pre-filter pipeline docs, retrain cadence/reminder thresholds

### Commit 5: Prior-Session Files
- Session 280-283 handoffs, replay findings doc, experiment scripts

### Commit 6: Direction Health Monitoring (Observation-Only)
- `_query_direction_health()` queries 14d rolling HR by OVER vs UNDER
- `direction_health` field added to signal-best-bets JSON output
- Warning angle when pick's direction HR < 50% ("below breakeven")
- Phase 1: observe only, hard-gating deferred until we have live data

---

## All Files Changed

| File | Change |
|------|--------|
| `ml/signals/player_blacklist.py` | **NEW** — compute_player_blacklist() |
| `ml/signals/aggregator.py` | Blacklist + avoid-familiar filters, rel_edge removal, version bump |
| `ml/signals/pick_angle_builder.py` | High-conviction edge>=5, direction health warning |
| `ml/signals/__init__.py` | Added compute_player_blacklist export |
| `data_processors/publishing/signal_best_bets_exporter.py` | Blacklist, games_vs_opponent, direction health, JSON metadata |
| `predictions/worker/prediction_systems/catboost_monthly.py` | V12 quantile edge >= 4 |
| `bin/retrain.sh` | 42-day rolling window |
| `orchestration/cloud_functions/retrain_reminder/main.py` | 7-day cadence thresholds |
| `bin/infrastructure/setup_retrain_reminder.sh` | Updated comments |
| `CLAUDE.md` | Updated signal filters, retrain cadence |
| `tests/unit/signals/__init__.py` | **NEW** |
| `tests/unit/signals/test_player_blacklist.py` | **NEW** — 25 tests |
| `docs/09-handoff/START-NEXT-SESSION-HERE.md` | Updated |
| `docs/08-projects/current/season-replay-analysis/00-FINDINGS.md` | Prior session |
| `docs/09-handoff/2026-02-17-SESSION-{280,282,283}-HANDOFF.md` | Prior sessions |
| `ml/experiments/{season_replay_full,analyze_*}.py` | Prior session scripts |

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

## Total P&L Impact

| Change | P&L Impact |
|--------|-----------|
| Player blacklist | +$10,450 |
| 7-day retrain cadence | +$7,670 |
| 42-day rolling window | +$5,370 |
| Avoid-familiar | +$1,780 |
| Remove rel_edge | Positive (unblocks 62.8% HR picks) |
| V12 quantile edge>=4 | HR +5.1pp |
| **Total estimated** | **+$25,270+** |

---

## Tests

```bash
PYTHONPATH=. pytest tests/unit/signals/test_player_blacklist.py -v
# 25 tests across 7 test classes:
# - TestComputePlayerBlacklist (11) — blacklist computation
# - TestAggregatorBlacklistIntegration (4) — aggregator respects blacklist
# - TestAvoidFamiliarFilter (4) — games_vs_opponent filter
# - TestRelEdgeFilterRemoved (1) — high rel_edge no longer blocked
# - TestHighConvictionAngle (3) — edge>=5 angle
# - TestDirectionHealthWarning (2) — OVER/UNDER HR warning
```

---

## Verification Checklist (Feb 19)

All code pushed and auto-deploying. On Feb 19 morning:

- [ ] `gcloud builds list` — confirm all builds SUCCESS
- [ ] `./bin/check-deployment-drift.sh --verbose` — no drift
- [ ] `/validate-daily` — pipeline healthy
- [ ] Check `v1/signal-best-bets/{date}.json`:
  - `player_blacklist.count` > 0
  - `direction_health.over_hr_14d` and `under_hr_14d` populated
  - `algorithm_version` = `v284_blacklist_familiar_reledge`
  - `angles` contain "High conviction" for edge>=5 picks
- [ ] All 6 models generate predictions
- [ ] `dual_agree` and `model_consensus_v9_v12` fire in signals

---

## Next Session Priorities

### Priority 1: Feb 19 Monitoring
- Track aggregator top-5 HR daily (target: 62%+ with new filters)
- Monitor blacklisted players — are they truly losing?
- Check direction_health data — is OVER or UNDER trending poorly?
- Validate avoid-familiar filter is blocking expected players

### Priority 2: Further Experiments
- **Adaptive direction gating** — if direction_health shows OVER < 45%, add hard gate (data from Phase 1)
- **Per-model edge thresholds** — V9 MAE at edge>=5, others at edge>=3
- **Blacklist within consensus only** — more targeted blocking
- **High conviction tier** — surface edge>=5 picks separately in API
- **Min training days sweep** — test 14d/21d with 7d cadence

### Priority 3: Operational
- Run first retrain with new 42-day rolling window: `./bin/retrain.sh --all --dry-run`
- Verify retrain-reminder fires correctly with 7-day thresholds

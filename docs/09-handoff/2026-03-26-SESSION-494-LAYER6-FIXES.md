# Session 494 Handoff — Layer 6 Structural Fixes + Monitoring Gaps

**Date:** 2026-03-26
**Previous session:** Session 493 (prediction_accuracy JOIN fixes, duplicate picks root cause)
**Commit:** `0ad2bd66`

---

## What Was Done

Session 494 completed all deferred Layer 6 work from Session 493. Single commit: `0ad2bd66`. No regressions.

---

## Changes (commit `0ad2bd66`)

### Data Pipeline Hardening

**1. `signal_best_bets_exporter.py` — DELETE failure gate (HIGH)**

Added `delete_succeeded` flag to `_write_to_bigquery` and `_write_filtered_picks`. If the DELETE throws, the function logs the error and returns early. Previously, a failed DELETE would silently fall through to the INSERT — appending records on top of stale rows and creating duplicate picks. This is the exact failure mode that caused the Session 493 incident.

**2. `signal_best_bets_exporter.py` — atomic writes for filtered picks (MEDIUM)**

`_write_filtered_picks` replaced streaming insert (`insert_rows_json`) with `load_table_from_json` + `WriteDisposition.WRITE_TRUNCATE` partition decorator. Consistent with the codebase's batch-over-streaming principle (see CLAUDE.md). Timeout increased from 30s to 60s.

**3. `best_bets_all_exporter.py` — row-level fallback (MEDIUM)**

The UNION ALL fallback between `signal_best_bets_picks` and `best_bets_published_picks` was using a date-level `NOT IN` guard (`game_date NOT IN signal_dates`). This silently dropped published picks for players not covered by the signal pipeline when ANY signal picks existed for that date. Changed to a row-level `NOT EXISTS` guard keyed on `(player_lookup, game_date)`. The `signal_dates` CTE was removed.

---

### Monitoring Additions

**4. `pipeline_canary_queries.py` — GCS all.json duplicate picks canary**

New function `check_all_json_duplicate_picks`. Downloads `gs://nba-props-platform-api/v1/best-bets/all.json`, scans all picks across today and weekly history, and fails on any duplicate `(player_lookup, game_date)` pair. Zero tolerance. Registered in `main()` unconditionally — fires every 30 minutes with the rest of the canaries.

**5. `pipeline_canary_queries.py` — fleet diversity canary**

New function `check_fleet_diversity`. Queries the model registry for all enabled/active models, classifies by family (lgbm / catboost / xgb / other), and fails if all models are the same family or if zero non-LGBM models are present. Enforces the Session 487 lesson: an all-LGBM fleet makes `combo_3way` and `book_disagreement` impossible to fire (both require cross-model disagreement).

**6. `model_correlation.py` — diversity summary**

Added `print_fleet_diversity_summary()`. Prints a per-family model breakdown and emits a warning when r≥0.95 clone pairs are detected. Runs automatically on every invocation.

---

### Code Quality / Documentation

**7. `feature_extractor.py` — V16 feature guard**

Added `AND recommendation IN ('OVER', 'UNDER')` guard for V16 features (indices 55-56). Added a comment explaining why `system_id` cannot be filtered in the batch extraction context without a major architecture refactor (15+ ThreadPoolExecutor tasks would need the parameter threaded through).

**8. `quality_scorer.py` — FEATURE_COUNT documentation**

Documented why `FEATURE_COUNT=54` (not 60): features 54-59 lack corresponding BQ quality schema columns. This is intentional two-level truncation, not a bug. Resolves the apparent mismatch between `quality_scorer.py` (54) and `ml_feature_store_processor.py` (60).

**9. `aggregator.py` — observation filter audit block**

Added a structured audit comment cataloguing all 30 observation-mode filters into 3 categories (A/B/C). See the Observation Filter Audit section below.

**10. `SIGNAL-INVENTORY.md`**

Updated observation filter count from 11 to 30.

**11. `check-deployment-drift.sh`**

Fixed stale service name `nba-phase1-scrapers` → `nba-scrapers`. The service was renamed; the drift script was still checking the old name. All 7 Cloud Run services from CLAUDE.md are now covered.

---

### Items Confirmed (no code change needed)

- `AUTO_DISABLE_ENABLED=true` confirmed set on the `decay-detection` Cloud Function.
- `FEATURE_COUNT` mismatch between `quality_scorer.py` and `ml_feature_store_processor.py` is intentional design, not a latent bug.

---

## Observation Filter Audit Results

All 30 observation-mode filters catalogued in `aggregator.py`. Do NOT act on these without running BQ queries against `filter_counterfactual_daily` first. The CF HR numbers below come from the 5-season simulator (Session 461) or pre-Session 494 ad hoc queries — they need current-season verification.

**Query to run before acting:**
```sql
SELECT
  filter_name,
  AVG(cf_hr) AS avg_cf_hr,
  SUM(n_blocked) AS total_n,
  COUNT(DISTINCT game_date) AS n_days
FROM nba_predictions.filter_counterfactual_daily
WHERE game_date >= '2025-11-01'
GROUP BY 1
ORDER BY total_n DESC
```

### Category A — Accumulating data, no action yet (14 filters)

Filters added recently (2026-03-xx) or with N < 30. Leave in observation.

### Category B — Flag for promotion review (5 filters, N is large enough)

These filters are blocking picks with HR below 52.4% breakeven. Promotion threshold: N≥30 AND CF HR ≥55% for 7 consecutive days per the auto-demote logic.

| Filter | CF HR | N | Notes |
|--------|-------|---|-------|
| `monday_over_obs` | 49.0% | 251 | Blocks OVER on Mondays; consistently sub-breakeven |
| `home_over_obs` | 49.7% | 4,278 | Largest N, strongest case for promotion to active |
| `hot_shooting_reversion_obs` | 59.2% UNDER HR | 250 | UNDER signal candidate, not a blocker — consider flipping to UNDER signal |
| `player_under_suppression_obs` | TBD | TBD | Added 2026-03-24 — needs BQ verification |
| `under_star_away` | 73% post-ASB | TBD | Was demoted in toxic Feb window. Check if recovery is sustained before re-promotion |

### Category C — Blocking winners, consider removal (11 filters, CF HR too high)

These filters are blocking picks that WOULD WIN. Removal or inversion is warranted once current-season N is confirmed.

| Filter | CF HR | N | Notes |
|--------|-------|---|-------|
| `neg_pm_streak_obs` | 64.5% | 758 | Strongest removal case — blocks 64.5% winners |
| `line_dropped_over_obs` | 60.0% | 477 | Smart money is BULLISH on these; filter is wrong direction |
| `flat_trend_under_obs` | 59.2% | 211 | Marginal case — verify current season |
| `ft_variance_under_obs` | 56.0% | large | 5-season validated (Session 461 simulator) |
| `familiar_matchup_obs` | 54.4% | large | 5-season validated (Session 461 simulator) |
| `b2b_under_block_obs` | 54.0% | large | 5-season validated (Session 461 simulator) |
| `line_jumped_under_obs` | 100% | 5 | Very low N — wait for N≥30 |
| `high_skew_over_block_obs` | 75% | 4 | Very low N — wait for N≥30 |
| `bench_under_obs` | 100% | 2 | Very low N — wait for N≥30 |
| `opponent_under_block` | 52.4% | 21 | Borderline; needs more data |
| `opponent_depleted_under` | 83.3% | 6 | Very low N — wait for N≥30 |

---

## Remaining Work (next session priorities)

### 1. Observation filter promotions/removals (BQ verification required first)

Run the query above against `filter_counterfactual_daily`. Immediate action candidates once verified:

- **Remove `neg_pm_streak_obs`** — CF HR 64.5%, N=758. Strongest case in the codebase.
- **Promote `home_over_obs` to active** — HR 49.7%, N=4,278. Largest N of any observation filter.
- **Remove `line_dropped_over_obs`** — CF HR 60.0%, N=477. Market is bullish on these picks.
- **Remove `ft_variance_under_obs`, `familiar_matchup_obs`, `b2b_under_block_obs`** — all 5-season validated as blocking winners (Session 461).

### 2. MLB launch (URGENT — Opening Day is 2026-03-27)

Runbook: `docs/08-projects/current/mlb-2026-season-strategy/07-LAUNCH-RUNBOOK.md`

Steps:
1. Retrain MLB model on current data
2. Manual deploy: `gcloud builds submit --config cloudbuild-mlb-worker.yaml`
3. Verify traffic routing: `gcloud run services describe` (new revisions may not auto-route)
4. Confirm scheduler targeting `nba-scrapers` not legacy `nba-phase1-scrapers`

### 3. Feature extractor system_id threading (LOW priority, deferred)

V16 features 55-56 use `MAX(line_value)` across all systems in batch context. Full fix requires threading `system_id` through 15+ ThreadPoolExecutor tasks in `feature_extractor.py`. Only affects players with multi-system line disagreements. Low urgency.

---

## End of Session Checklist

- [x] DELETE failure gate added to `signal_best_bets_exporter.py`
- [x] Atomic writes for filtered picks (`load_table_from_json` + WRITE_TRUNCATE)
- [x] Row-level fallback in `best_bets_all_exporter.py`
- [x] GCS all.json duplicate picks canary added
- [x] Fleet diversity canary added
- [x] `model_correlation.py` diversity summary added
- [x] `feature_extractor.py` V16 guard + architecture comment
- [x] `quality_scorer.py` FEATURE_COUNT documented
- [x] `aggregator.py` observation filter audit block (30 filters catalogued)
- [x] `SIGNAL-INVENTORY.md` updated (11 → 30 observation filters)
- [x] `check-deployment-drift.sh` service name fixed (`nba-phase1-scrapers` → `nba-scrapers`)
- [x] Pushed to main (`0ad2bd66`), auto-deploy triggered
- [ ] Observation filter promotions/removals (needs BQ verification)
- [ ] MLB launch (Opening Day 2026-03-27)

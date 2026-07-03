# Fleet Diversity Gate

**Status:** Implemented (validator + CI-ready check). Not wired to auto-disable.
**Owner:** Model governance
**Created:** 2026-07-03

## Problem

The best-bets **cross-model consensus signals** only fire when the *enabled* model fleet
contains **decorrelated model families**. If every enabled model outputs near-identical
predictions, those signals silently produce **zero picks** — the fleet looks healthy, but a
whole class of high-HR signals is dead.

This has happened: **Session 487** — all enabled models drifted to `r >= 0.95` LGBM clones,
and `book_disagreement` / cross-model agreement collapsed for ~2 days before anyone noticed.

Diversity was **monitored** but never **enforced at enable-time**:
- `bin/analysis/model_correlation.py` — pairwise correlation report (manual, ad-hoc).
- `check_fleet_diversity()` in `bin/monitoring/pipeline_canary_queries.py` — a *runtime
  canary* (framework-only, alerts after the fact).
- `weekly_retrain` only re-fits **already-enabled** families — it can never *restore* lost
  diversity, so once the fleet collapses it stays collapsed.

There was no pre-enable / CI gate. This project adds one.

## Which signals this protects (and which it does NOT)

Protects the genuinely **cross-MODEL** consensus signals:
- `book_disagreement` (best-bets rescue signal)
- `xm_diverse_agreement`, `xm_consensus_3plus`, `xm_consensus_4plus`,
  `xm_quantile_agreement_under`, `xm_mae_plus_quantile_over`
  (defined in `shared/config/cross_model_subsets.py` / `CrossModelScorer`)

These need multiple **decorrelated families / feature-sets** agreeing to fire.
`xm_diverse_agreement` explicitly requires **two different feature-sets** to agree.

**Does NOT protect `combo_3way`.** `combo_3way` is single-MODEL (verified in prior review)
— fleet diversity is irrelevant to it. Do not justify this gate with `combo_3way`.

## The correlation budget

A fleet **FAILS** the budget if **either** rule is violated:

**(A) Pairwise-clone budget** *(prediction-vector, degrades gracefully off-season)*
- No pair of enabled models may have prediction-vector Pearson **r >= 0.95** on a recent
  held-out slate.
- Requires >= 10 overlapping player-date predictions to trust a pair.
- **Skipped with a clear message when no recent slate exists** (off-season / break). The
  family-diversity floor below still governs in that case.

**(B) Family-diversity floor** *(registry metadata — always runs, works off-season)*
- **>= 1 enabled model whose ML framework is NOT CatBoost** (i.e. an LGBM/XGBoost/other),
  AND
- **>= 2 distinct feature-sets** among enabled models.

Framework is classified from `model_id` (`lgbm`/`xgb`/`catboost`/`other`), mirroring the
existing canary. Feature-set is read from the `model_registry.feature_set` column when
populated, otherwise derived from `model_id` via
`shared.config.cross_model_subsets.classify_system_id()`.

### Thresholds (single source, in the validator)

| Constant | Value | Meaning |
|---|---|---|
| `CLONE_R` | 0.95 | pairwise Pearson r at/above = clone |
| `MIN_OVERLAP` | 10 | min overlapping player-dates to score a pair |
| `MIN_NON_CATBOOST` | 1 | min enabled non-CatBoost models |
| `MIN_FEATURE_SETS` | 2 | min distinct feature-sets among enabled models |

## What it is / isn't

- It is a **VALIDATION**: prints `WARNING`/`FAIL`, **exits non-zero**. Suitable to run
  pre-enable or in CI.
- It is **NOT** an auto-disabler. Session 488 lesson: automated fleet mutation on thin
  signals is dangerous. Resolve violations by hand.

## How to run

```bash
# Full gate (metadata floor + correlation budget)
PYTHONPATH=. .venv/bin/python bin/validation/validate_fleet_diversity.py

# Wider correlation slate
PYTHONPATH=. .venv/bin/python bin/validation/validate_fleet_diversity.py --days 21

# Metadata-only (skip prediction-vector correlation; always safe off-season)
PYTHONPATH=. .venv/bin/python bin/validation/validate_fleet_diversity.py --skip-correlation
```

Exit `0` = budget satisfied, `1` = budget violated (or hard error).

**Recommended usage:** run before enabling/promoting any model, and add to CI. `bq` CLI
hangs in the WSL dev env — this script uses the Python BigQuery client (no `bq`).

## Current fleet state (2026-07-03, off-season)

The gate flagged a **real latent diversity collapse** on the *current* enabled fleet:

| model_id | framework | feature_set |
|---|---|---|
| `catboost_v12_noveg_train1205_0403` | catboost | v12_noveg |
| `lgbm_v12_noveg_train0206_0402` | lgbm | v12_noveg |
| `xgb_v12_noveg_train0206_0402` | xgb | v12_noveg |

- **Framework diversity: OK** — catboost + lgbm + xgb (passes the non-CatBoost floor).
- **Feature-set diversity: VIOLATED** — all three are `v12_noveg` → only **1** distinct
  feature-set (floor requires >= 2). `xm_diverse_agreement` (needs two feature-sets to
  agree) is structurally unable to fire with this fleet, despite three different
  frameworks *looking* diverse.
- **Correlation budget: SKIPPED** — off-season, no recent slate. Degraded gracefully.

**Interpretation:** three frameworks trained on the *same* feature contract are far more
correlated than they appear from framework labels alone. This is exactly the blind spot the
metadata floor closes without needing live prediction vectors. **Season-open action:** enable
at least one model on a different feature contract (e.g. a V9 or V16-family model) so the
cross-model / diverse-agreement signals have decorrelated inputs, then re-run the full gate
(correlation budget) on a live slate to confirm no `r >= 0.95` clone pair remains.

## Files

- `bin/validation/validate_fleet_diversity.py` — the gate (this project's deliverable).
- Reads: `nba_predictions.model_registry`, `nba_predictions.player_prop_predictions`,
  `shared/config/cross_model_subsets.py`.
- Related (unchanged): `bin/analysis/model_correlation.py`,
  `bin/monitoring/pipeline_canary_queries.py::check_fleet_diversity`,
  `bin/validation/validate_model_registry.py`.

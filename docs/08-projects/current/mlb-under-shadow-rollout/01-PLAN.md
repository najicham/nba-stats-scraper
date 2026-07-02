# MLB UNDER shadow rollout — execution plan

**Decision context:** `00-OVERVIEW.md`, `03-DECISIONS.md`
**Evidence:** `02-AGENT-FINDINGS.md`

Three phases. Phase 0 is pre-work that must ship before shadow produces useful data. Phase 1 ships shadow + monitoring. Phase 2 is the graduation decision after 45 days. Phase 3 (Quantile retrain) is deferred.

---

## Phase 0 — Pre-work (sequenced, must complete before Phase 1)

### Step 1 — Repair UNDER signal pipeline (~6h)

**Problem:** `UNDER_MIN_SIGNALS=3` is structurally unreachable today. Of 5 weighted signals, only 2 fire.

**Files:**
- `ml/signals/mlb/best_bets_exporter.py:122-129` — `UNDER_SIGNAL_WEIGHTS` dict
- `ml/signals/mlb/registry.py` — signal registration (search `is_shadow=True`)
- `ml/signals/mlb/signals.py` — signal class definitions
- `predictions/mlb/supplemental_loader.py:120-162` — supplemental feature load

**Changes:**

| Action | Signal | Why |
|---|---|---|
| Promote shadow → active | `k_rate_reversion_under` | NBA analogue `hot_3pt_under` = 62.5% HR 5-season. Already coded. |
| Promote shadow → active | `short_starter_under` | Structural: `ip_avg_last_5 < 5.0` → pitchers physically can't reach line |
| Promote shadow → active | `cumulative_arm_stress_under` | Fatigue compound: `pitch_count_avg >= 100 AND games_30d >= 6` |
| Remove from weights | `pitch_count_limit_under` | Field `pitch_count_limit` never populated anywhere |
| Remove from weights | `weather_cold_under` | Still shadow — inconsistent to weight a non-firing signal |
| Wire data feed | `velocity_drop_under` | `velocity_change` is referenced but never populated from `mlb_analytics.pitcher_rolling_statcast` |

**New `UNDER_SIGNAL_WEIGHTS` (5 working entries):**
```python
UNDER_SIGNAL_WEIGHTS = {
    'velocity_drop_under': 2.0,          # NOW FIRES (after wire fix)
    'short_rest_under': 1.5,             # already firing
    'high_variance_under': 1.5,          # already firing
    'k_rate_reversion_under': 2.5,       # promoted
    'short_starter_under': 1.5,          # promoted
    'cumulative_arm_stress_under': 1.5,  # promoted
}
```

**Verification:** After deploy, run for 3 game days and confirm `signal_count` distribution on UNDER candidates includes values >= 3.

---

### Step 2 — Add UNDER negative filters (~3h)

**Problem:** Zero UNDER-targeted negative filters exist. Memory's "6 OVER-targeted filters" was partly wrong (3 OVER-only + 3 bidirectional).

**Files:**
- `ml/signals/mlb/signals.py` — new filter classes after line ~709
- `ml/signals/mlb/registry.py:38-40,183-189` — register new filters

**Two new filters (from Agent 5's cross-season analysis):**

```python
class HighLineUnderBlock(MLBNegativeFilter):
    """Block UNDER picks on high lines with marginal edge.
    Trigger: line >= 7.0 AND edge < 1.5 AND recommendation == 'UNDER'
    Rationale: 2025 walk-forward showed 47-53% HR on this archetype (N~34).
    """
    tag = 'high_line_under_block'

class EliteK9UnderBlock(MLBNegativeFilter):
    """Block UNDER picks on elite-K pitchers at moderate lines.
    Trigger: season_k_per_9 >= 9.5 AND line >= 6.5 AND recommendation == 'UNDER'
    Rationale: Biggest cross-season collapse — 96.9% HR (2024) -> 65.2% HR (2025).
    Market caught up to elite-K pitcher pricing; UNDER no longer a free roll.
    """
    tag = 'elite_k9_under_block'
```

**Note:** Both ship as ACTIVE (not observation). Cross-season degradation is the canonical signal that an archetype filter is justified — these aren't speculative.

**Verification:** After deploy, query `mlb_predictions.best_bets_filter_audit` and confirm both filter tags appear with `filter_result='BLOCKED'` on next slate where they apply.

---

### Step 3 — Fix direction-hardcoded bookkeeping (~3h)

**Problem:** Three analytics modules hardcode `recommendation='OVER'`. Without fixing them, shadow UNDER HR is invisible to dashboards/monitors.

**Files:**
- `ml/analysis/mlb_model_performance.py:85-98` — replace hardcoded OVER with parameterized direction; emit `n_under_7d/14d/30d` and `under_hr_*` columns
- `ml/analysis/mlb_league_macro.py:324` — add `pct_under` alongside `pct_over`
- `data_processors/publishing/mlb/mlb_results_exporter.py:146` — split metrics by direction in published JSON
- `data_processors/publishing/mlb/mlb_predictions_exporter.py:128` — same

**BQ schema migration:**
```sql
ALTER TABLE `nba-props-platform.mlb_predictions.model_performance_daily`
  ADD COLUMN n_under_7d INT64,
  ADD COLUMN n_under_14d INT64,
  ADD COLUMN n_under_30d INT64,
  ADD COLUMN under_hr_7d NUMERIC(4,3),
  ADD COLUMN under_hr_14d NUMERIC(4,3),
  ADD COLUMN under_hr_30d NUMERIC(4,3);

ALTER TABLE `nba-props-platform.mlb_predictions.league_macro_daily`
  ADD COLUMN pct_under NUMERIC(4,3);
```

**Verification:** Backfill last 30 days of `model_performance_daily` with UNDER columns and confirm non-zero N for periods where UNDER picks existed (the brief shadow window from Phase 1).

---

## Phase 1 — Ship shadow (after Phase 0 deployed and verified)

### Step 4 — Shadow mode implementation (~4h)

**Approach:** Reuse `mlb_predictions.blacklist_shadow_picks` with a `shadow_reason` discriminator (Agent 6's recommendation — simpler than a new table).

**BQ migration:**
```sql
ALTER TABLE `nba-props-platform.mlb_predictions.blacklist_shadow_picks`
  ADD COLUMN shadow_reason STRING;

UPDATE `nba-props-platform.mlb_predictions.blacklist_shadow_picks`
  SET shadow_reason = 'blacklist'
  WHERE shadow_reason IS NULL;
```

**Code changes — `ml/signals/mlb/best_bets_exporter.py`:**

1. New env var separate from `MLB_UNDER_ENABLED`:
```python
UNDER_SHADOW_ENABLED = os.environ.get('MLB_UNDER_SHADOW', 'true').lower() == 'true'
```

2. Lines 287, 306-329 — always include UNDER in `allowed_directions` when `UNDER_SHADOW_ENABLED OR UNDER_ENABLED`. Tag each UNDER pred with `_shadow_only = not UNDER_ENABLED`.

3. After ranking (line ~589), partition:
```python
publish_picks = [p for p in ranked_picks if not p.get('_shadow_only')]
shadow_under_picks = [p for p in ranked_picks if p.get('_shadow_only')]
```

4. Use `publish_picks` for `top_picks[:MAX_PICKS_PER_DAY]` and ultra/overlay logic. Shadow UNDER picks skip ultra/overlay.

5. New `_write_shadow_under_picks(picks, game_date)` method — mirrors `_write_best_bets` but writes to `blacklist_shadow_picks` with `shadow_reason='under_shadow'`. Use scoped DELETE on `(game_date, pitcher_lookup, system_id, shadow_reason)` so it doesn't trample blacklist shadow rows.

6. Lines 642-647 — add `if not dry_run and shadow_under_picks: self._write_shadow_under_picks(...)`.

**Approximate diff size:** ~80 LOC including new write method.

**Frontend impact:** Zero. `data_processors/publishing/mlb/mlb_best_bets_exporter.py` queries `signal_best_bets_picks` only; shadow rows never reach GCS.

---

### Step 5 — Log-everything mode for ranking discovery (~2h)

**User decision:** UNDER ranking will be redesigned from scratch using shadow data. Until 30d of data exists, do not rank — just log everything.

**Changes — `ml/signals/mlb/best_bets_exporter.py`:**

- When `_shadow_only=True`, skip the `MAX_PICKS_PER_DAY` truncation (write all qualified picks)
- Skip the `UNDER_SIGNAL_WEIGHTS` quality sort for shadow UNDER (write in arbitrary order with `rank=NULL`)
- Add structured columns to shadow rows that the post-hoc ranker discovery will use:
  - `archetype_tags` (ARRAY<STRING>): `'elite_k9'`, `'high_line'`, `'away'`, `'short_rest'`, etc. — computed at write time from features
  - All raw signal confidences (already in `signal_results`)
  - Edge bucket label (`'0.75-1.0'`, `'1.0-1.5'`, etc.)

**Discovery deliverable (Day 30):** `scripts/mlb/discovery/under_ranking_scanner.py` — scans shadow UNDER picks across feature × signal-set combinations, finds the empirical ranking that maximizes HR within each daily slate. Modeled after NBA's `scripts/nba/training/discovery/feature_scanner.py`.

---

### Step 6 — Daily monitor CF (~3h)

**New CF:** `cloud_functions/mlb_under_shadow_monitor/main.py`

**Scheduler:** `deployment/scheduler/mlb/monitoring-schedules.yaml`
```yaml
- name: mlb-under-shadow-monitor
  schedule: "30 14 * 3-10 *"  # 9:30 AM ET, March-October (after Phase 5b grading)
  topic: # direct Cloud Function HTTP trigger
  target: mlb-under-shadow-monitor
```

**Logic:**
```python
# Query last 7d and 30d shadow UNDER HR from blacklist_shadow_picks WHERE shadow_reason='under_shadow'
# Trigger conditions (either):
#   - 7d HR < 50% (N >= 14)
#   - No shadow UNDER picks 5+ consecutive days (pipeline dead)
# Alert via shared/alerts/rate_limiter.py with 24h GCS dedup
# Slack channel: #nba-alerts (via existing mlb-alert-forwarder CF)
```

**Auto-deploy:** Add to `cloudbuild-functions.yaml` so push-to-main deploys it.

---

### Step 7 — Historical backfill bootstrap (~2h)

**Problem:** 45 days of live shadow is a lot of waiting. Backfilling 2024-2025 historical predictions gives ~200 graded UNDER picks on day 1.

**Caveat from Agent 1:** Walk-forward output isn't in BQ. Backfill goes through `prediction_accuracy` directly (which has features via feature-store join), not via re-running the model.

**New script:** `scripts/mlb/shadow_under_backfill.py`

```
For each game_date in 2024-04-01 .. 2025-09-30:
    1. Load predictions from prediction_accuracy where recommendation IN ('OVER','UNDER')
    2. Load features from ml_feature_store_v2 (or pitcher_loader equivalent)
    3. Call MLBBestBetsExporter.export(dry_run=True) with UNDER_SHADOW=true injected
    4. Write resulting shadow UNDER picks to blacklist_shadow_picks with shadow_reason='under_shadow_backfill'
    5. Grade against pitcher_strikeouts.actual_strikeouts
```

**Runtime:** ~3 minutes for full 2024-2025 history.

**Note the discriminator:** Use `shadow_reason='under_shadow_backfill'` (not `'under_shadow'`) so we can separate live vs replayed picks in graduation analysis.

---

## Phase 2 — Graduation decision (Day 47 from Phase 1 ship)

**Promotion gate (ALL must pass):**

| Criterion | Threshold |
|---|---|
| Sample size | N >= 60 graded shadow UNDER picks |
| Rolling 45-day HR | >= 56.0% |
| Monthly consistency | No bucket < 50% (min N=10/month) |
| Vig-adjusted ROI | >= +3.0% |

**Live flip (only when gate passes):**
```bash
gcloud run services update mlb-prediction-worker \
  --region=us-west2 --project=nba-props-platform \
  --update-env-vars=MLB_UNDER_ENABLED=true
```

**Keep shadow ON for 14 more days post-flip** (parity check — `MLB_UNDER_SHADOW=true` remains default).

**If gate fails:** Document why in `02-AGENT-FINDINGS.md` addendum, keep shadow running, revisit at Day 90.

---

## Phase 3 — Quantile-loss retrain (DEFERRED)

Agent 3 recommends changing `train_regressor_v2.py:83` from `'RMSE'` to `'Quantile:alpha=0.5'` to fix the structural OVER bias. Walk-forward expectation: OVER-prediction rate drops 60% → 53-55%, UNDER picks become statistically available at edge >= 0.75.

**Why deferred:** Model swap is a separate change with its own governance gates. Doing it before shadow lets us A/B (RMSE shadow UNDER vs Quantile shadow UNDER). Do it AFTER shadow has 30 days of data.

---

## Total effort to data flowing

| Phase | Effort | Calendar |
|---|---|---|
| Steps 1-3 (signals + filters + bookkeeping) | ~12h | 2 working days |
| Steps 4-7 (shadow + ranking-log + monitor + backfill) | ~11h | 2 working days |
| **Subtotal — pre-flip work** | **~23h** | **~3-4 working days** |
| Shadow collection | passive | 45 days |
| Graduation decision | ~2h | Day 47 |

---

## What this plan does NOT touch

- The CatBoost regressor model (Phase 3, deferred)
- OVER pipeline — no changes
- `MAX_PICKS_PER_DAY` — stays 5 (shared quota per `03-DECISIONS.md`)
- `MLB_UNDER_ENABLED` env var — stays false. Shadow uses new `MLB_UNDER_SHADOW` flag
- Frontend code — zero changes until graduation

## Rollback at each phase

| Phase | Rollback |
|---|---|
| Phase 0 (signals/filters/bookkeeping) | Revert the commit. Schema migrations are additive — no data loss. |
| Phase 1 (shadow live) | `gcloud run services update mlb-prediction-worker --update-env-vars=MLB_UNDER_SHADOW=false`. Picks stop within ~5 min. Shadow rows remain in BQ for analysis. |
| Phase 2 (UNDER live in prod) | `--update-env-vars=MLB_UNDER_ENABLED=false`. Reverts to OVER-only within ~5 min. |

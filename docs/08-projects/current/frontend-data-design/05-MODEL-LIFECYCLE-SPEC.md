# Model Lifecycle & Multi-Model Architecture — Admin Dashboard

**Status:** Spec for frontend review. Backend data ships with this spec.

## The Core Concept

We don't have one model. We have **6-10 active models** running simultaneously, all generating predictions every day. Best bets picks the highest-edge prediction across ALL of them for each player. When we retrain, the old model doesn't die — it keeps running alongside the new one.

This means the admin dashboard needs to show **model lineage** (what replaced what), **coexistence** (which models are actively contributing), and **lifecycle stage** (shadow vs production vs deprecated).

---

## Model Families

Models are grouped into **families** by architecture + loss function:

| Family | Architecture | Loss | Notes |
|--------|-------------|------|-------|
| `v9_mae` | 33 features | RMSE | Champion family. Most battle-tested. |
| `v12_noveg_mae` | 50 features | RMSE | More features, sometimes better. Shadow. |
| `v9_q43` | 33 features | Quantile (α=0.43) | Tends to predict slightly under. Good for UNDER picks. |
| `v9_q45` | 33 features | Quantile (α=0.45) | Slightly less aggressive than Q43. |
| `v12_q43` | 50 features | Quantile (α=0.43) | V12 + quantile combo. |
| `v12_q45` | 50 features | Quantile (α=0.45) | V12 + quantile combo. |

Each family can have **multiple generations** (retrains). When we retrain `v9_mae`, the new model gets a new `model_id` but stays in the `v9_mae` family. The old one transitions from `production` → `deprecated` but keeps running.

---

## Lifecycle Stages

```
CREATION ──→ SHADOW ──→ PRODUCTION ──→ DEPRECATED
   │            │           │              │
   │         enabled     champion       still runs
   │        generates    drives          (graded for
   │       predictions  best bets       comparison)
   │       (graded,    (promoted
   │        tracked)    manually)
   │
   └── If gates fail: never enabled, dead end
```

Each model in `dashboard.json` has these lifecycle fields:

```jsonc
{
  "model_id": "catboost_v9_33f_train20260106-20260205_20260218_223530",
  "family": "v9_mae",

  // Lifecycle
  "registry_status": "production",     // "active" (shadow) | "production" | "deprecated"
  "is_production": true,               // THE champion model
  "enabled": true,                     // generating predictions daily
  "parent_model_id": "catboost_v9_train1102_0205",  // what this model replaced (null if first)
  "production_start": "2026-02-19",    // when promoted (null if never promoted)
  "production_end": null,              // when replaced (null if still production)

  // Performance (live, rolling)
  "state": "HEALTHY",                  // decay state machine: HEALTHY → WATCH → DEGRADING → BLOCKED
  "hr_7d": 62.5,
  "hr_14d": 59.1,
  "hr_30d": 61.0,
  "n_7d": 48,
  "n_14d": 93,
  "n_30d": 180,
  "days_since_training": 3,

  // Training details (static, set at creation)
  "training_start": "2026-01-06",      // what data the model learned from
  "training_end": "2026-02-05",
  "eval_mae": 4.83,                    // mean absolute error at evaluation time
  "eval_hr_edge3": 66.7,              // hit rate on edge 3+ at evaluation time
  "feature_count": 33,
  "loss_function": "RMSE",            // "RMSE" for MAE models, "Quantile" for quantile
  "quantile_alpha": null               // 0.43 or 0.45 for quantile models, null for MAE
}
```

---

## How Best Bets Uses Multiple Models

This is the key thing to understand: **best bets picks are NOT just from the champion model.**

The aggregator queries ALL enabled models for each player, takes the **highest edge prediction** across all of them, then applies filters. So a best bet pick might come from V9 Q43 or V12, not just the champion V9 MAE.

Each pick in the dashboard already tells you which model it came from:

```jsonc
{
  "source_model": "catboost_v9_q43_train1102_0125",  // which model's prediction won
  "source_family": "v9_q43",
  "n_models_eligible": 3,                             // how many models had edge 5+ for this player
  "champion_edge": 4.1,                               // champion's edge (might be lower than winner)
  "direction_conflict": false                          // true if models disagreed on OVER/UNDER
}
```

---

## Suggested UI: Model Health Section

### Option A: Family-Grouped Table

Group models by family. Within each family, show current + previous generation.

```
v9_mae (Champion Family)
┌──────────────────────────────────────────────────────────────────────────────┐
│ ★ catboost_v9_...0218  PRODUCTION  HEALTHY  62.5%  3d old   Jan 6 - Feb 5  │
│   catboost_v9_...1102  deprecated  HEALTHY  58.1%  25d old  Nov 2 - Feb 5  │
│                        ↑ replaced by above on Feb 19                        │
└──────────────────────────────────────────────────────────────────────────────┘

v9_q43 (Quantile)
┌──────────────────────────────────────────────────────────────────────────────┐
│   catboost_v9_q43_...  shadow      INSUFF   55.2%  25d old  Nov 2 - Jan 25 │
└──────────────────────────────────────────────────────────────────────────────┘

v12_noveg_mae
┌──────────────────────────────────────────────────────────────────────────────┐
│   catboost_v12_...     shadow      HEALTHY  69.2%  14d old  Nov 2 - Feb 5  │
└──────────────────────────────────────────────────────────────────────────────┘
```

### Option B: Flat Table with Family Column

Simpler — just a flat sortable table with a family column and status badges.

| Model | Family | Status | State | 7d HR | 14d HR | Age | Training Window | Loss |
|-------|--------|--------|-------|-------|--------|-----|-----------------|------|
| ★ catboost_v9_...0218 | v9_mae | PRODUCTION | HEALTHY | 62.5% | 59.1% | 3d | Jan 6 - Feb 5 | RMSE |
| catboost_v9_...1102 | v9_mae | deprecated | HEALTHY | 58.1% | 56.2% | 25d | Nov 2 - Feb 5 | RMSE |
| catboost_v12_... | v12_mae | shadow | HEALTHY | 69.2% | 67.1% | 14d | Nov 2 - Feb 5 | RMSE |
| catboost_v9_q43_... | v9_q43 | shadow | INSUFF | 55.2% | 57.8% | 25d | Nov 2 - Jan 25 | Q43 |

### Status Badges

| `registry_status` | Badge | Color | Meaning |
|-------------------|-------|-------|---------|
| `production` | ★ PRODUCTION | green | Champion — drives best bets ranking |
| `active` | SHADOW | blue | Running alongside, being evaluated |
| `deprecated` | DEPRECATED | gray | Replaced, still running for comparison |

| `state` (decay) | Badge | Color | Meaning |
|-----------------|-------|-------|---------|
| `HEALTHY` | HEALTHY | green | 58%+ hit rate |
| `WATCH` | WATCH | yellow | 55-58% — monitor closely |
| `DEGRADING` | DEGRADING | orange | 52.4-55% — consider retrain |
| `BLOCKED` | BLOCKED | red | Below breakeven |
| `INSUFFICIENT_DATA` | INSUFF | gray | <10 graded picks in window |

---

## Lineage Tracking

When `parent_model_id` is not null, the model replaced another:

```
catboost_v9_...0218 (production, Feb 19 - present)
  └── replaced: catboost_v9_...1102 (deprecated, Jan 30 - Feb 19)
        └── replaced: catboost_v9_feb_retrain (deprecated, Jan 15 - Jan 30)
```

The frontend can build this tree from `parent_model_id` chains. For the initial build, a simple "Replaced: {parent}" line under the model row is sufficient.

---

## What "Active" Means for Best Bets

The number of models contributing to today's picks is visible in the `n_models_eligible` field on each pick. For the dashboard status bar:

```
Models: 8 active, 1 champion | 3 contributed to today's picks | Oldest: 25d
```

Compute from `model_health`:
- Active = count where `enabled == true`
- Champion = the one with `is_production == true`
- Contributing = unique `source_model` values across today's picks
- Oldest = max `days_since_training`

---

## Frontend Decisions (Resolved)

1. **Option A: Family-grouped table.** Group by family with `Object.groupBy(family)`. Family header + indented rows. With 6-10 models, a flat table is a wall of similar-looking rows; grouping makes the key question instantly scannable: "how is each architecture doing, and which generation is live?"

2. **One-liner lineage only.** Show "Replaced catboost_v9_...1102 on Feb 19". No full chain — the daily check-in use case doesn't need it. Data is there via `parent_model_id` if a "show full history" expander is ever needed.

3. **Family badge + short ID suffix + tooltip.** Show `v9_mae` badge, then `...0218` (last 4-6 chars of the ID). Full model_id on hover/tooltip. The long ID is only useful for grep-ing logs.

4. **Subtle stale highlight.** The age badge already color-codes (green/yellow/red), so no extra badge. If `days_since_training > 14`, give the entire model row a faint yellow left-border (warning stripe). Draws the eye without adding another badge. Same pattern as Key Angles on the Tonight page.

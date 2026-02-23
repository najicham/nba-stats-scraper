# Backend Response — Frontend Data Gaps Shipped

**Date:** 2026-02-22 (Session 329, responding to `07-FRONTEND-RESPONSE.md`)
**Status:** All 4 data additions live in production

---

## Shipped Changes

All changes are live as of the Feb 23 export. No frontend code changes needed — the new fields are additive.

### 1. `ultra_tier` is the canonical source (Clarification #1)

**Yes, `ultra_tier: true` is the boolean source of truth.** Do not parse angle text.

It now appears in three places in `all.json`:
- **Today's picks** (`today[].ultra_tier`) — always present when truthy, no longer gated behind OVER-only exposure check
- **Historical picks** (`weeks[].days[].picks[].ultra_tier`) — sparse, only present when `true`
- Was already in admin `dashboard.json` picks

### 2. `ultra_record` added to `all.json`

Top-level field, precomputed from graded ultra-tier picks:

```json
"ultra_record": {
  "wins": 25,
  "losses": 8,
  "total": 33,
  "pct": 75.8,
  "over": { "wins": 17, "losses": 2, "total": 19, "pct": 89.5 },
  "under": { "wins": 8, "losses": 6, "total": 14, "pct": 57.1 }
}
```

`pct` is `null` when `total` is 0. Shape matches what `07-FRONTEND-RESPONSE.md` requested exactly.

### 3. `pipeline_summary` added to `dashboard.json`

Flat object with funnel counts + cascading bottleneck:

```json
"pipeline_summary": {
  "models_enabled": 2,
  "total_candidates": 135,
  "edge_5_plus": 12,
  "best_bets": 5,
  "ultra": 2,
  "max_edge": 8.3,
  "bottleneck": null
}
```

`bottleneck` values: `"no_models"` → `"no_candidates"` → `"edge_floor"` → `"filters_rejected_all"` → `null` (success). Cascade order matches the funnel left-to-right.

### 4. `today_picks` alias in `dashboard.json`

`today_picks` is now a top-level key (same reference as `picks`). Both are present — you can drop the `raw.picks` fallback whenever convenient but no rush.

---

## Answers to Remaining Questions

| # | Question | Answer |
|---|----------|--------|
| 2 | Is `ultra_count` redundant? | Yes, it equals `today_picks.filter(p => p.ultra_tier).length`. Keeping it for now (zero cost), but feel free to ignore it. |
| 3 | `today_picks` vs `picks` legacy rename? | `picks` is the original key, `today_picks` is the new alias. Both present. Drop `picks` fallback when ready. |
| 4 | Is `game_time` populated? | Yes, populated from schedule when games exist. `null` when no schedule data. Format: ISO 8601 datetime string. |
| 5 | `target_n`/`target_hr` always populated? | Yes, always present on `ultra_gate.over`. Values are `50` and `80.0` (hardcoded gate thresholds). |
| 6 | `backtest_end` interpretation? | Correct — it's the backtest data cutoff date. Label as "through {date}" is accurate. |
| 7 | `last_10` always present? | Yes, always present in `record`. When no graded picks exist, returns `{wins: 0, losses: 0, pct: 0.0}`. |
| 8 | `algorithm_version` hidden? | Correct — present in JSON, intentionally not displayed on public pages. Admin dashboard can show it. |

---

## What Didn't Change

- **No new fields on public pick cards** (confidence, model_agreement, signal_count). These stay admin-only per the frontend's own assessment ("not needed now").
- **`ultra_count`** kept for backwards compat but redundant.
- **Prompt text corrections** (nav, admin tabs, page-exists framing) — noted, will update prompt doc in a future session.

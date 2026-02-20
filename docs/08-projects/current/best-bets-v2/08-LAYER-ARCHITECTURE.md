# Layer Architecture — Subset Materialization & Best Bets

**Created:** Session 311 (2026-02-20)
**Status:** Definitive reference for the 3-layer subset architecture

## Overview

The system uses a **3-layer materialization pattern** that runs in sequence during Phase 6 Publishing, plus a **Best Bets output** that curates the final user-facing picks.

```
Layer 1 (Per-Model) → Layer 2 (Cross-Model) → Layer 3 (Signal) → Best Bets Output
```

All 3 layers write to the same `current_subset_picks` table. Best Bets writes to its own table (`signal_best_bets_picks`) + GCS JSON.

## Layer Summary

| Layer | What | Materializer | system_id | Table | Write Strategy |
|-------|------|-------------|-----------|-------|----------------|
| **L1** | Per-model subsets (edge/confidence/direction) | `SubsetMaterializer` | Model-specific (e.g. `catboost_v9`) | `current_subset_picks` | Append-only (version_id) |
| **L2** | Cross-model observation (consensus patterns) | `CrossModelSubsetMaterializer` | `cross_model` | `current_subset_picks` | Delete-then-write |
| **L3** | Signal subsets (pick-level signal patterns) | `SignalSubsetMaterializer` | `signal_subset` | `current_subset_picks` | Delete-then-write |
| **Output** | Best Bets (user-facing curated picks) | `SignalBestBetsExporter` | Champion | `signal_best_bets_picks` + GCS JSON | Upsert |

### Key Distinctions

- **Best Bets is the output (product), not a layer.** Layers are observation/tracking; Best Bets is the selection algorithm.
- All 3 layers share the same BQ table (`current_subset_picks`), graded by `SubsetGradingProcessor` (system_id-agnostic).
- A single pick can appear in all 3 layers + best bets — each provides a different lens on the same prediction.
- Layers 2-3 use delete-then-write (only latest matters). Layer 1 is append-only (version history preserved).

## Orchestration Flow

**File:** `backfill_jobs/publishing/daily_export.py`

```
1. SubsetMaterializer.materialize()           → L1 rows + version_id
2. CrossModelSubsetMaterializer.materialize()  → L2 rows
3. AllSubsetsPicksExporter.export()            → GCS v1/picks/{date}.json (reads from L1+L2)
4. SignalBestBetsExporter.export()             → Evaluates signals → L3 rows + best bets JSON
```

Non-fatal: L2, L3, and signal failures don't block the export (logged, not raised).

## Layer 1: Per-Model Subsets

**File:** `data_processors/publishing/subset_materializer.py`
**Class:** `SubsetMaterializer`

Queries definitions from `dynamic_subset_definitions`, groups by system_id, filters predictions per subset criteria (min_edge, min_confidence, direction, signal_condition, pct_over ranges).

**Subset examples:** Top Pick, Top 3, Top 5, Green Light, Ultra High Edge, High Edge OVER, All Picks (per model)

**Quality filter:** `feature_quality_score >= 85%` by default. "all_predictions" subsets use `min_quality=0`.

**Stale system_id resolution (Session 311):** Before grouping, resolves stale definition system_ids by classifying both definitions and active predictions into model families (`v9_mae`, `v9_q43`, etc.) via `classify_system_id()`. This means Q43/Q45 subsets work correctly even when definitions reference old model names.

## Layer 2: Cross-Model Observation Subsets

**File:** `data_processors/publishing/cross_model_subset_materializer.py`
**Class:** `CrossModelSubsetMaterializer`

Discovers all active models dynamically (no hardcoded system_ids), queries all models' predictions, pivots by (player, game) to find cross-model agreement.

**5 subsets:**

| Subset ID | Rule | Notes |
|-----------|------|-------|
| `xm_consensus_3plus` | 3+ models agree, all edge >= 3 | Direction-agnostic |
| `xm_consensus_4plus` | 4+ models agree, all edge >= 3 | Higher confidence |
| `xm_quantile_agreement_under` | All quantile models → UNDER | UNDER specialist |
| `xm_mae_plus_quantile_over` | MAE + quantile agree → OVER | Diverse loss confirmation |
| `xm_diverse_agreement` | V9 + V12 agree, both edge >= 3 | Feature set diversity |

**Dynamic model discovery:** Uses `discover_models()` from `shared/config/cross_model_subsets.py`. Models classified into 6 families by pattern matching. Survives retrains without code changes.

## Layer 3: Signal-Based Subsets

**File:** `data_processors/publishing/signal_subset_materializer.py`
**Class:** `SignalSubsetMaterializer`

Runs AFTER signal evaluation (receives pre-computed signal results). Curates only the strongest signal patterns.

**4 subsets:**

| Subset ID | Rule | Backtest HR |
|-----------|------|-------------|
| `signal_combo_he_ms` | combo_he_ms fires (High Edge + Minutes Surge) | 94.9% |
| `signal_combo_3way` | combo_3way fires (ESO + HE + MS, OVER-only) | 95.5% |
| `signal_bench_under` | bench_under fires + edge >= 5 | 76.9% |
| `signal_high_count` | 4+ qualifying signals + edge >= 5 | 85.7% |

**Called from:** `SignalBestBetsExporter` (not independently orchestrated).

## Best Bets Output

**File:** `data_processors/publishing/signal_best_bets_exporter.py`
**Class:** `SignalBestBetsExporter`

The user-facing product. Edge-first selection: `edge 5+ → negative filters → rank by edge → top 5`.

**Algorithm (Session 297):**
1. Query predictions from ALL CatBoost families (multi-source, Session 307)
2. Pick highest-edge prediction per player across models
3. Evaluate all signals via registry
4. Materialize signal subsets (L3)
5. Compute cross-model consensus
6. Apply negative filters (blacklist, avoid-familiar, UNDER edge 7+ block, etc.)
7. Rank by edge, take top picks
8. Build pick angles (human-readable reasoning)
9. Write to BQ + GCS

**Output:** `v1/signal-best-bets/{date}.json` + `signal_best_bets_picks` table

## DB Table Naming Rationale

Two performance-tracking tables exist with seemingly inconsistent names:

| Table | Tracks | Purpose |
|-------|--------|---------|
| `model_performance_daily` | Decay state machine (HEALTHY → WATCH → DEGRADING → BLOCKED) | Production model steering |
| `signal_health_daily` | Regime (HOT / NORMAL / COLD) per signal per timeframe | Signal selection + frontend display |

**Decision (Session 311): Leave as-is.** The naming difference reflects a real semantic distinction — one tracks model decay states, the other tracks signal health regimes. Renaming `signal_health_daily` to match would touch 162+ references across 40+ files, 4 Cloud Functions, 4 CLI skills, and frontend-facing GCS URLs with no user-facing benefit.

---

## Frontend Grouping Design

The admin subset page groups picks by layer using tabs:

### TAB 1: MODEL VIEW (Layer 1)

```
V9 Champion (catboost_v9)
├── Top Pick / Top 3 / Top 5 / Green Light / Ultra High Edge
├── High Edge All / High Edge OVER
└── All Picks

V9 Q43 (catboost_v9_q43_*)  [UNDER specialist]
├── Q43 UNDER Top 3 / Q43 UNDER All
└── Q43 All Picks

V9 Q45 (catboost_v9_q45_*)  [UNDER specialist]
└── Q45 UNDER Top 3 / Q45 All Picks

V12 Nova (catboost_v12*)
├── Nova Top Pick / Top 3 / Top 5 / Green Light
├── Nova High Edge All / High Edge OVER
└── Nova All Picks

V12 Q43/Q45 (v12q43, v12q45)
└── V12 Q43/Q45 All Picks / UNDER Top 3

Low-Vegas (catboost_v9_low_vegas_*)
└── Low-Vegas High Edge / UNDER / All
```

### TAB 2: CROSS-MODEL VIEW (Layer 2)

```
Consensus
├── xm_consensus_3plus (3+ models agree, edge 3+)
└── xm_consensus_4plus (4+ models agree)

Strategy
├── xm_quantile_agreement_under (all quantile → UNDER)
└── xm_mae_plus_quantile_over (MAE + quantile → OVER)

Diversity
└── xm_diverse_agreement (V9 + V12 agree)
```

### TAB 3: SIGNAL VIEW (Layer 3)

```
Combo Signals
├── signal_combo_he_ms (94.9% HR)
└── signal_combo_3way (95.5% HR, OVER only)

Pattern Signals
└── signal_bench_under (76.9% HR)

Multi-Signal
└── signal_high_count (4+ signals, 85.7% HR)
```

### Pick Badges

Each pick card shows layer provenance badges:
- L1: "V9 Top 3", "Ultra High Edge"
- L2: "4+ Consensus", "Quantile UNDER"
- L3: "HE+MS Combo", "3-Way Combo"

### Implementation Notes

This is a **frontend-only change**. The backend data already supports this grouping:
- `current_subset_picks`: Contains all L1/L2/L3 rows with `subset_id` and `system_id`
- `signal_best_bets_picks`: Contains `qualifying_subsets` for badge provenance
- `AllSubsetsPicksExporter`: Already groups by model in `v1/picks/{date}.json`

The tabs/badges would consume existing data — no new backend work required.

## Key Files Reference

| File | Layer | Purpose |
|------|-------|---------|
| `data_processors/publishing/subset_materializer.py` | L1 | Per-model subset materialization |
| `data_processors/publishing/cross_model_subset_materializer.py` | L2 | Cross-model observation subsets |
| `data_processors/publishing/signal_subset_materializer.py` | L3 | Signal-based subsets |
| `data_processors/publishing/signal_best_bets_exporter.py` | Output | Best bets curation + export |
| `data_processors/publishing/all_subsets_picks_exporter.py` | Export | Consolidated subsets GCS export |
| `backfill_jobs/publishing/daily_export.py` | Orchestration | Calls all materializers + exporters |
| `shared/config/cross_model_subsets.py` | Config | Model family classification + L2 definitions |
| `shared/config/subset_public_names.py` | Config | Human-readable subset names |
| `nba_predictions.dynamic_subset_definitions` | BQ Table | L1 subset filter definitions |
| `nba_predictions.current_subset_picks` | BQ Table | All L1/L2/L3 materialized picks |
| `nba_predictions.signal_best_bets_picks` | BQ Table | Best bets picks (graded) |

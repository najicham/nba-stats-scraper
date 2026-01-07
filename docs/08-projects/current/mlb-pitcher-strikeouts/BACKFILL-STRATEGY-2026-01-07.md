# MLB Pitcher Strikeouts - Backfill Strategy

**Date**: 2026-01-07
**Status**: Planning
**Decision**: Two-phase approach (local first, formalize later)

---

## Context: How NBA Backfills Actually Work

After studying the codebase and completed project docs:

### Infrastructure vs Reality

| What Exists | What's Actually Used |
|-------------|---------------------|
| 52 Cloud Run backfill jobs | Rarely used for backfills |
| Local execution scripts | **Primary method** |
| Parallel workers (10-25) | Critical for performance |
| Checkpointing | Essential for long runs |

### Why Local is Preferred

1. **Better observability** - Real-time log monitoring
2. **Easy control** - Pause/resume/kill anytime
3. **Worker tuning** - Adjust mid-execution
4. **No alert cascade** - Backfills don't trigger pipelines

### NBA Backfill Performance (918 dates)

| Phase | Time | Workers |
|-------|------|---------|
| Analytics | 24 hours | 15 |
| Precompute | 30 hours | 10-15 |
| Predictions | 6.5 hours | 5-8 |
| **Total** | ~42 hours | Local |

---

## MLB Backfill Requirements

### Important: Current Date is January 7, 2026

Available complete seasons:
- **2025 season**: March 27 - September 28, 2025 ✅ (MOST RECENT)
- **2024 season**: March 28 - September 29, 2024 ✅
- **2026 season**: Starts late March 2026 (NOT YET)

### Data Collection Order

1. **2025 first** - Most recent, most relevant for 2026 predictions
2. **2024 second** - Additional training data

### Data We Need Per Season

| Dataset | Source | Volume | Purpose |
|---------|--------|--------|---------|
| Game boxscores | MLB Stats API | ~2,400/season | Lineups + Pitcher Ks |
| Batter K rates | pybaseball | ~500/season | Bottom-up formula |
| Pitcher season stats | pybaseball | ~350/season | Feature vector |
| Platoon splits | Statcast | ~500/season | K% vs LHP/RHP |

### Estimated Time

**2025 Season Only** (~2,430 games):
- Data collection: 2-4 hours (API rate limits)
- Feature calculation: 1-2 hours
- ML training: 1-2 hours
- **Total**: ~6 hours

**Both 2025 + 2024** (~4,860 games):
- Data collection: 4-8 hours
- Feature calculation: 2-4 hours
- ML training: 2-3 hours
- **Total**: ~12 hours

---

## Proposed Strategy

### Phase A: Local Scripts (This Week)

**Goal**: Collect 2024 season data and train initial model

**Approach**:
1. Extend `baseline_validation.py` for full season collection
2. Add checkpointing for resume capability
3. Store in local JSON files first
4. Load to BigQuery after validation
5. Run ML training

**Files to Create**:
```
scripts/mlb/
├── baseline_validation.py     # Already created
├── collect_season_data.py     # Full season collection
├── calculate_k_rates.py       # Batter K rates with splits
├── prepare_training_data.py   # Feature vector generation
└── train_pitcher_model.py     # XGBoost training
```

**Advantages**:
- Start TODAY
- Fast iteration
- Easy debugging
- No deployment overhead

### Phase B: Formal Backfill Jobs (Before Season)

**Goal**: Production-ready infrastructure for ongoing use

**Approach**:
1. Create `backfill_jobs/mlb/` directory structure
2. Match NBA patterns (class-based, deploy.sh, job-config.env)
3. Add Cloud Run deployment for automation
4. Integrate with notification system

**Directory Structure**:
```
backfill_jobs/mlb/
├── scrapers/
│   ├── mlb_boxscores/
│   │   ├── mlb_boxscores_scraper_backfill.py
│   │   ├── deploy.sh
│   │   └── job-config.env
│   └── mlb_pitcher_stats/
├── raw/
│   ├── mlb_lineups/
│   └── mlb_pitcher_stats/
├── analytics/
│   ├── pitcher_game_summary/
│   └── batter_game_summary/
├── precompute/
│   ├── pitcher_features/
│   └── lineup_k_analysis/
└── README.md
```

**When to Do This**:
- After Phase A proves the approach works
- Before MLB season starts (March 2026)
- If we need automated daily collection

---

## Implementation Plan

### Week 1: Local Data Collection

| Day | Task | Output |
|-----|------|--------|
| 1 | Extend baseline script for full season | `collect_season_data.py` |
| 2 | Collect 2024 season boxscores | `/tmp/mlb_2024_boxscores.json` |
| 3 | Calculate batter K rates with platoon splits | `/tmp/mlb_2024_k_rates.json` |
| 4 | Generate feature vectors for all starts | `/tmp/mlb_2024_features.json` |
| 5 | Train XGBoost model | `models/mlb_pitcher_ks_v1.json` |

### Week 2: Validation & Enhancement

| Day | Task | Output |
|-----|------|--------|
| 1-2 | Validate model accuracy on holdout | Accuracy report |
| 3 | Add platoon splits to features | Enhanced K rates |
| 4 | Retrain with enhanced features | Model v2 |
| 5 | Document findings | Updated docs |

### Week 3+: Formalize (If Needed)

- Create formal backfill job structure
- Deploy to Cloud Run
- Set up daily collection for 2025 spring training

---

## Script Specifications

### collect_season.py (CREATED)

```python
"""
Collect MLB season data with BigQuery storage.

Usage:
    # Collect 2025 season (RECOMMENDED - most recent)
    python scripts/mlb/collect_season.py --season 2025

    # Collect 2024 season (additional training data)
    python scripts/mlb/collect_season.py --season 2024

    # Collect specific month
    python scripts/mlb/collect_season.py --season 2025 --month 8

    # Resume from checkpoint
    python scripts/mlb/collect_season.py --season 2025 --resume

    # Dry run
    python scripts/mlb/collect_season.py --season 2025 --dry-run --limit 10

Features:
- Checkpointing (auto-resume on failure)
- Rate limiting (respect MLB Stats API)
- Platoon splits from Statcast
- BigQuery storage (mlb_raw tables)
- Progress tracking
"""
```

**Key Features**:
- Collects lineups + pitcher Ks from MLB Stats API
- Loads batter K rates with platoon splits from pybaseball/Statcast
- Stores directly to BigQuery (mlb_game_lineups, mlb_lineup_batters)
- Auto-checkpointing every 10 dates

### calculate_k_rates.py

```python
"""
Calculate batter K rates from pybaseball/Statcast.

Usage:
    python scripts/mlb/calculate_k_rates.py --season 2024
    python scripts/mlb/calculate_k_rates.py --season 2024 --with-splits

Features:
- Overall K% from FanGraphs
- Platoon splits (vs LHP / vs RHP) from Statcast
- Team-level aggregates
"""
```

### prepare_training_data.py

```python
"""
Generate feature vectors for ML training.

Usage:
    python scripts/mlb/prepare_training_data.py \
        --boxscores /tmp/mlb_2024_boxscores.json \
        --k-rates /tmp/mlb_2024_k_rates.json \
        --output /tmp/mlb_2024_training.json

Features:
- Match lineups to K rates
- Calculate bottom-up expected Ks
- Generate 35-feature vectors
- Split train/val/test chronologically
"""
```

### train_pitcher_model.py

```python
"""
Train XGBoost model for pitcher strikeouts.

Usage:
    python scripts/mlb/train_pitcher_model.py \
        --training-data /tmp/mlb_2024_training.json \
        --output models/mlb_pitcher_ks_v1.json

Features:
- Chronological train/val/test split
- Hyperparameter tuning
- Feature importance analysis
- Model versioning
- Compare to baseline (bottom-up formula)
"""
```

---

## Decision Points

### When to Move to Phase B?

Move to formal backfill jobs when:
1. Local scripts prove the approach works
2. We need daily automated collection
3. Before MLB season starts
4. If we're sharing with team members

### When to Use Cloud Run?

Use Cloud Run only if:
1. Need scheduled daily execution
2. Need longer runtime than local allows
3. Multiple people need to trigger backfills
4. For production pipeline integration

---

## Questions for User

1. **Start with 2024 only or all 3 seasons (2022-2024)?**
   - Recommendation: 2024 first, add more if needed

2. **Store in local files or BigQuery first?**
   - Recommendation: Local JSON first, load to BQ after validation

3. **Include platoon splits in first pass or add later?**
   - Recommendation: Basic K rates first, add splits in v2

4. **Should I start building `collect_season_data.py` now?**

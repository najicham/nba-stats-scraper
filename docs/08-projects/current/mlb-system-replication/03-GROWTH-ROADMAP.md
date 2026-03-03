# MLB Dual-Track Growth Roadmap

> **Purpose:** Phased roadmap for two MLB prediction markets — pitcher strikeouts (existing infrastructure) and team game total O/U (new build). Each track has clear gates, milestones, and what NOT to build per phase.

---

## Track A: Pitcher Strikeouts (Build on Existing)

### Existing Infrastructure

Track A starts with significant infrastructure already built:

| Component | Status | Details |
|-----------|--------|---------|
| Scrapers | 27 active | BDL (13), MLB Stats API (3), Odds API (8), External (3), Statcast (1) |
| Raw processors | 9 | Phase 2 pipeline |
| Analytics processors | 2 | Phase 3 — `pitcher_game_summary` (9,800+ rows) |
| Precompute processors | 3 | Phase 4 — 35-feature store (`v2_35features`) |
| Feature store | Populated | `mlb_precompute.pitcher_ml_features` |
| Prediction worker | 24K lines | Multi-model + shadow mode support |
| Trained models | 12+ | V1-V4, XGBoost-based, in `/models/mlb/` |
| Grading pipeline | Built | Cloud Functions deployed |
| Publishing pipeline | Built | Phase 6 export |
| Orchestration | Built | Phase transition Cloud Functions |
| Deploy scripts | Built | `bin/deploy-service.sh` compatible |
| RedFlagConfig | Validated | Min IP, career starts, SwStr%, rest thresholds |
| Drift analysis | Done | `docs/08-projects/current/mlb-pitcher-strikeouts/MODEL-DRIFT-ANALYSIS-JUL-AUG-2025.md` |

### Phase 0: Historical Simulation & Validation (3-5 weeks, pre-Opening Day)

**Entry gate:** Existing infrastructure audit passes, 2025 data gaps filled.

**Activities:**
- Audit existing models and features for quality — which of the 12+ models still work?
- Walk-forward simulation using existing trained models on 2025 data
- Training window optimization (21/42/63/84 day windows)
- Signal and filter discovery from historical predictions
- Edge threshold recalibration — existing config uses 0.5 K (NBA uses 3.0 pts, find MLB sweet spot)
- Compare existing XGBoost V1/V1.6 against fresh CatBoost models

**Deliverables:**
- `mlb_season_replay.py` adapted from existing `bin/testing/mlb/replay_mlb_pipeline.py`
- `ml/signals/mlb/` signal implementations
- Findings document with optimal configs and dead ends

**Exit gate:**
- [ ] 120+ game-dates simulated
- [ ] Best config >= 55% HR on walk-forward holdout
- [ ] 5+ filters and 3+ signals validated against historical data
- [ ] Optimal training window and retrain cadence identified
- [ ] Existing models vs fresh CatBoost comparison documented
- [ ] Edge threshold calibrated for strikeout market

### Phase 1: MVP (Weeks 1-4 live, late March-April)

**Entry gate:** Phase 0 complete, champion model selected (existing or retrained).

**What this phase is:** Mostly deploying and validating what already exists, not building new.

**Components:**
- Best model from Phase 0 audit (existing V1/V1.6 or fresh CatBoost)
- Minimal filter stack:
  - Edge floor (calibrated in Phase 0)
  - Quality floor (quality_score < 85 blocked)
  - Pitcher blacklist (< 40% HR on 8+ picks)
  - Opener filter (from existing RedFlagConfig — min IP, career starts)
- Existing grading pipeline
- Existing publishing pipeline
- Daily manual review of picks

**Exit gate:**
- [ ] 7+ consecutive days with no manual intervention required
- [ ] 100+ graded picks
- [ ] HR above 52.4% breakeven
- [ ] No critical data quality issues

### Phase 2: Foundation (Weeks 5-12, May-June)

**Entry gate:** 200+ graded predictions, Phase 1 stable.

**Components:**
- Second model in shadow (existing V1.6 or fresh CatBoost — whichever wasn't Phase 1 champion)
- First 5-8 signals deployed (validated in Phase 0 simulation)
- Signal count gate (min signals >= 3, matching NBA pattern)
- Decay detection state machine (HEALTHY → WATCH → DEGRADING → BLOCKED)
- Model governance gates adapted from NBA:
  1. High-edge HR >= 55% (adjusted from NBA's 60% for strikeout market)
  2. Sample size >= 50 graded high-edge picks
  3. No critical directional bias (OVER/UNDER within +/- 5pp)
  4. MAE improvement vs baseline
- First retrain cycle executed

**Exit gate:**
- [ ] 2+ models tracked (1 production, 1+ shadow)
- [ ] 5+ signals active with HR tracking
- [ ] 500+ graded picks
- [ ] Decay detection operational
- [ ] First retrain completed with governance gates passing

### Phase 3: Maturity (Weeks 13-24, June-August)

**Components:**
- Multi-model fleet (4-8 models) with per-model profiling
- Full filter stack (10+ filters) — direction × edge band, home/away, rest days, lineup strength
- Signal count gate enforced
- Ultra bets layer (internal-only until N >= 50 at 80%+ HR)
- Automated retraining on cadence (7-14 day, calibrated in Phase 0)
- Full monitoring: deployment drift, pipeline canary, grading gaps, decay detection
- Model HR-weighted selection (from NBA Session 365 pattern)

**Exit gate:**
- [ ] 4+ models in fleet
- [ ] 10+ filters active
- [ ] 8+ signals active
- [ ] 1,500+ graded picks
- [ ] Best bets HR >= 60%
- [ ] Ultra bets layer operational (internal)

### Phase 4: Optimization (Weeks 25+, September onward)

**Components:**
- Cross-season validation (2024/2025/2026 data)
- Fleet lifecycle automation (auto-disable BLOCKED models)
- Postseason handling (different dynamics — shorter rest, limited rotation)
- Signal firing canary (detect silent signal death — NBA Session 387 lesson)
- Public ultra bets exposure (if gate met: N >= 50, HR >= 80%)

**Exit gate:**
- [ ] Cross-season validated (best config works on 2+ seasons)
- [ ] Profitable over full 2026 season
- [ ] Automated fleet management operational

---

## Track B: Team Game Total Over/Under (Build from Scratch)

### Market Definition

**What we're predicting:** Total runs scored by both teams combined, compared to bookmaker's game total line.

**Architecture:** Identical to NBA player props and pitcher strikeouts:
- `predicted_total_runs - game_total_line = edge`
- Positive edge → OVER (model thinks more runs than line)
- Negative edge → UNDER (model thinks fewer runs than line)
- Same filter stack → signal count → best bets pipeline

### What Already Exists vs What Needs to Be Built

| Component | Status | Notes |
|-----------|--------|-------|
| Game lines scraper | EXISTS | `scrapers/mlb/oddsapi/mlb_game_lines.py` |
| Game lines processor | EXISTS | `data_processors/raw/mlb/mlb_game_lines_processor.py` |
| Historical game lines | EXISTS | `mlb_raw.oddsa_game_lines` + `mlb_raw.oddsa_game_lines_his` |
| Box scores | EXISTS | `mlb_raw.bdl_box_scores` (team-level runs, hits, errors) |
| Team season stats | EXISTS | `mlb_raw.bdl_team_season_stats` |
| Schedule | EXISTS | `mlb_raw.mlb_schedule` with probable pitchers |
| Ballpark factors | EXISTS | `mlb_ballpark_factors` scraper |
| Weather data | EXISTS | `mlb_weather` scraper |
| Team game summary | **NEEDS BUILD** | New analytics processor: team runs, hits, ERA, bullpen usage per game |
| Team feature store | **NEEDS BUILD** | New `team_ml_features` table with team-level feature vectors |
| Team feature contract | **NEEDS BUILD** | ~20-25 features (offense, pitching, park, weather) |
| Team prediction system | **NEEDS BUILD** | Extend existing MLB worker or create separate |
| Team grading pipeline | **NEEDS BUILD** | Actual total runs vs predicted total runs |
| Team signals & filters | **NEEDS BUILD** | Team-level patterns, park effects, weather effects |

### Phase 0: Design & Historical Backfill (Weeks 1-4, concurrent with Track A Phase 0)

**Entry gate:** Track A Phase 0 started (shared data backfill benefits both tracks).

**Activities:**
- Design team feature contract (~20-25 features):
  - Home/Away SP quality (ERA, WHIP, K/9, recent ERA last 3/5 starts)
  - Home/Away team offense (OPS, wOBA, runs/game last 10, OPS vs LHP/RHP)
  - Bullpen state (home/away bullpen ERA, rest days, recent innings)
  - Park factors (run factor, HR factor)
  - Weather (temperature, wind speed/direction, humidity)
  - Vegas (game total line, home ML implied probability)
  - Historical (SP career ERA at this park, team vs opposing SP)
  - Season context (month, day/night, interleague)
- Backfill 2025 game results + team stats + game lines
- Build `team_game_summary` analytics processor
- Build `team_ml_features` feature store
- Train initial model on backfilled data

**Exit gate:**
- [ ] Feature contract documented with 20+ features
- [ ] `team_game_summary` analytics processor built and tested
- [ ] `team_ml_features` feature store populated for Apr-Sep 2025
- [ ] Initial CatBoost model trained
- [ ] Walk-forward simulation framework ready

### Phase 1: First Model & Simulation (Weeks 5-8)

**Entry gate:** Feature store populated, initial model trained.

**Activities:**
- Walk-forward simulation on 2025 data (6 monthly windows)
- Edge threshold discovery (what's the game total equivalent of NBA's edge >= 3?)
- Feature importance analysis — which features actually matter?
- Directional analysis (OVER vs UNDER by month, park, weather)
- Training window optimization (42/63/84/120 days)

**Exit gate:**
- [ ] Optimal training config identified
- [ ] HR above 52.4% breakeven on holdout data
- [ ] Dead ends documented (feature sets that don't work, etc.)
- [ ] Edge threshold calibrated
- [ ] OVER/UNDER directional patterns documented

### Phase 2: MVP Live (Weeks 9-12, concurrent with Track A Phase 2)

**Entry gate:** Phase 1 simulation results validated, HR above breakeven.

**Components:**
- Single champion model from Phase 1
- 3 basic filters:
  - Edge floor (calibrated in Phase 1)
  - Quality floor
  - Signal count gate (min signals >= 2, lower than Track A initially)
- Grading pipeline
- Daily publishing

**Exit gate:**
- [ ] 100+ graded predictions
- [ ] HR above 52.4% breakeven
- [ ] No critical data quality issues
- [ ] Pipeline runs without manual intervention

### Phase 3: Foundation (Weeks 13-20, concurrent with Track A Phase 3)

**Components:**
- Second model in shadow (different training window or feature set)
- First 5+ signals deployed
- Decay detection state machine
- Model governance gates
- First retrain cycle

**Exit gate:**
- [ ] 2+ models tracked
- [ ] 5+ signals active
- [ ] 500+ graded picks
- [ ] Decay detection operational

### Phase 4: Maturity (Weeks 21+)

**Components:**
- Multi-model fleet (3-5 models)
- Full filter stack (8+ filters)
- Ultra bets layer
- Merge monitoring infrastructure with Track A (shared alerting, dashboards)
- Cross-season validation

**Exit gate:**
- [ ] 3+ models in fleet
- [ ] 8+ signals active
- [ ] 1,000+ graded picks
- [ ] Best bets HR >= 58%

---

## Timeline Summary

| Calendar Period | Track A (Pitcher Ks) | Track B (Team Game Total) |
|-----------------|---------------------|---------------------------|
| **March** | Phase 0: Simulate 2025 season | Phase 0: Design + backfill |
| **Late March-April** | Phase 1: MVP live | Phase 1: Simulate 2025 season |
| **May-June** | Phase 2: Foundation | Phase 2: MVP live |
| **June-August** | Phase 3: Maturity | Phase 3: Foundation |
| **September+** | Phase 4: Optimization | Phase 4: Maturity |

Track B is ~4-8 weeks behind Track A because it starts from scratch. Shared infrastructure (scrapers, BQ datasets, monitoring, alerting) accelerates Track B.

---

## What NOT to Build Per Phase

### Phase 0-1 (Both Tracks)
- No multi-model fleet — single champion only
- No ultra bets — need 50+ picks at 80%+ first
- No per-model profiling — need multiple models first
- No automated retraining — manual retrain with governance gates
- No fleet lifecycle automation

### Phase 2 (Both Tracks)
- No ultra bets — still accumulating data
- No full filter stack — keep it simple, let patterns emerge
- No cross-season validation — need full season first

### Phase 3 (Both Tracks)
- No cross-season validation — need full season first
- No fleet lifecycle automation — manual model management

### Track B Specifically
- No signals until 200+ graded predictions — need data to discover patterns
- No filter stack until patterns emerge from live data — don't assume NBA patterns transfer
- No multi-model until single model is validated above breakeven

---

## Shared Infrastructure

Both tracks benefit from shared components:

| Component | Owner | Both Tracks Use |
|-----------|-------|-----------------|
| BigQuery datasets | Shared | `mlb_raw`, `mlb_analytics`, `mlb_precompute`, `mlb_predictions` |
| Scraper framework | Shared | `ScraperBase`, GCS export, Pub/Sub |
| Monitoring | Shared | Deployment drift, pipeline canary, Slack alerts |
| Model governance | Shared | Governance gates, decay detection |
| Best bets pipeline | Shared | Filter stack → signal count → edge ranking |
| Publishing | Shared | Phase 6 GCS JSON export |
| Grading | Shared | prediction_accuracy pattern |

Track B can reuse Track A's operational lessons (retrain cadence, decay thresholds, filter validation methodology) to accelerate past the learning curve.

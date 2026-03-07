# MLB Pitcher Strikeouts - Master Plan (2026 Season)

**Created:** 2026-03-06
**Updated:** 2026-03-06 (post-review)
**Season Start:** 2026-03-27 (21 days)
**Goal:** Run profitable MLB pitcher strikeout predictions with NBA-grade infrastructure

---

## Critical Findings from Architecture Review

The following issues were identified during review and must be addressed:

### Blocking Issues (Must Fix Before Launch)

1. **Default feature contamination** — MLB predictors silently substitute default values via `FEATURE_DEFAULTS` dicts. Walk-forward training uses `fillna(X.median())`. NBA's zero-tolerance system is the single most impactful quality improvement. Must add default counting + blocking.

2. **Grading processor lacks void handling** — No logic for rain-shortened games, postponements, or suspended games. Sportsbooks void pitcher props when pitcher doesn't complete minimum innings. Grading will produce incorrect results without void logic.

3. **Statcast backfill gap (Jul-Sep 2025)** — Current Statcast data only covers through Jun 2025. Walk-forward simulation cannot evaluate the Jul-Aug drift period without this data.

4. **Grading uses row-by-row DML UPDATE** — Will lock during catch-up grading (same anti-pattern NBA CLAUDE.md warns against).

### High Priority Improvements (Before Opening Day)

5. **Catcher framing feature** — Elite framers add 1-2 called strikes/game. Data freely available from Baseball Savant. Higher impact than initially estimated.

6. **Pitch count limit tracking** — Teams cap young pitchers at 80-85 pitches, directly capping K upside. Critical negative filter.

7. **CLV tracking** — Best diagnostic for model quality. NBA took months to learn this; apply immediately for MLB.

8. **Split signals into active (8) vs shadow (6)** — Starting all 14 active violates NBA lesson that signals need 30+ days before promotion.

9. **Market efficiency monitoring** — Root cause of Jul-Aug 2025 drift. Need early warning system.

10. **Edge threshold sweep** — Test 0.5, 0.75, 1.0, 1.5, 2.0 K in walk-forward. Don't assume 1.0.

### Medium Priority (First 2 Weeks of Season)

11. **Bullpen tiredness feature** — Tired bullpen = longer starter outing = more Ks
12. **Day-after-night feature** for opposing team — well-documented fatigue effect on hitter K rates
13. **Early hook UNDER signal** — Managers with short leash cap K upside
14. **Test training windows 90d and 120d** — 56d = only ~11 starts per pitcher, may be too thin
15. **September mode config** — Call-ups need stricter filters

### De-prioritized

16. **Reddit scraping** — Low ROI vs engineering effort. Community sentiment is noisy. Time better spent on quantitative signals (catcher framing, pitch count limits, bullpen state). Keep as shadow/experimental.

---

## Executive Summary

We have a **half-built MLB system** — scrapers, raw processing, analytics, and basic models exist, but the prediction quality layer (signals, best bets, grading, monitoring) that makes NBA profitable is entirely missing. BDL is unreliable and must be replaced. V1.6 model shows 69.9% accuracy in shadow mode but hasn't been promoted.

**The plan:** Replace BDL, port NBA's proven architecture, run a full walk-forward simulation on 2025 season data, and launch with proper infrastructure for 2026.

---

## Phase 0: Data Source Migration (BDL Replacement)

**Timeline:** Week 1 (Mar 6-12)
**Why:** BDL is unreliable. Every downstream system depends on clean data.

### Current BDL Dependencies & Replacements

| BDL Scraper | Data | Replacement Source | Effort |
|-------------|------|--------------------|--------|
| `mlb_pitcher_stats` | Per-game K, IP, ER | **MLB Stats API game feed** (already built) | 1 day |
| `mlb_batter_stats` | Per-game batter Ks | **MLB Stats API game feed** | 1 day |
| `mlb_games` | Game results/scores | **MLB Stats API schedule** (already built) | Done |
| `mlb_box_scores` | Final box scores | **MLB Stats API game feed** | 1 day |
| `mlb_active_players` | Rosters | **MLB Stats API** | 1 day |
| `mlb_injuries` | IL status | **MLB Stats API** + ESPN injury API | 2 days |
| `mlb_player_splits` | Home/away, vs LHP/RHP | **pybaseball** (FanGraphs) | 3 days |
| `mlb_player_versus` | Pitcher vs batter history | **pybaseball** (Baseball Reference) | 3 days |
| `mlb_season_stats` | YTD aggregates | **MLB Stats API** season stats endpoint | 1 day |
| `mlb_standings` | League standings | **MLB Stats API** standings endpoint | 0.5 day |
| `mlb_team_season_stats` | Team aggregates | **MLB Stats API** | 1 day |
| `mlb_teams` | Team metadata | **MLB Stats API** | Done |
| `mlb_live_box_scores` | In-game updates | **MLB Stats API game feed** | 1 day |

### New Data Sources to Add

| Source | Data | Why | Effort |
|--------|------|-----|--------|
| **pybaseball** (Statcast) | SwStr%, chase rate, velocity, spin | Leading K indicators — CRITICAL for V2 | 2 days |
| **pybaseball** (FanGraphs) | Season splits, advanced metrics | Replaces BDL splits + adds depth | 2 days |
| **Reddit r/sportsbook, r/baseball** | Community angles, sharp money discussion | Same approach as NBA community scraping | 3 days |
| **Action Network / Covers** | Consensus picks, public betting % | Market sentiment signal | 2 days |

### pybaseball Integration

```bash
# Already in .venv but NOT in requirements.txt
pip install pybaseball>=0.5.0
```

Key functions:
- `statcast_pitcher(start_dt, end_dt, player_id)` — pitch-level data
- `pitching_stats(season, qual=1)` — FanGraphs season stats
- `batting_stats(season, qual=1)` — FanGraphs batting (for opponent K rates)
- `playerid_lookup(last, first)` — cross-reference player IDs

### Migration Strategy

1. Build new scrapers alongside BDL (don't delete BDL yet)
2. Run both in parallel for 1 week, validate data matches
3. Promote MLB Stats API + pybaseball as primary
4. Disable BDL scrapers (keep code for reference)

### New BigQuery Tables

```sql
-- Replace BDL tables with authoritative sources
mlb_raw.mlbapi_pitcher_stats     -- From MLB Stats API game feed
mlb_raw.mlbapi_batter_stats      -- From MLB Stats API game feed
mlb_raw.mlbapi_injuries          -- MLB Stats API + ESPN
mlb_raw.pybaseball_statcast      -- Statcast pitch-level aggregates
mlb_raw.pybaseball_fangraphs     -- FanGraphs season/split stats
mlb_raw.reddit_mlb_discussion    -- Reddit community angles
```

---

## Phase 1: Port NBA Architecture to MLB

**Timeline:** Week 2-3 (Mar 13-26)
**Why:** NBA's infrastructure is what makes it profitable. MLB has none of it.

### 1.1 Prediction Accuracy Table (CRITICAL)

NBA has `prediction_accuracy` with 419K+ records. MLB has grading fields embedded in the predictions table — this is wrong.

```sql
CREATE TABLE mlb_predictions.prediction_accuracy (
  prediction_id STRING,
  game_date DATE,
  game_id STRING,
  pitcher_lookup STRING,
  pitcher_name STRING,
  system_id STRING,            -- 'v1_baseline', 'v1_6_rolling', 'ensemble_v1'
  predicted_strikeouts FLOAT64,
  actual_strikeouts INT64,
  line_value FLOAT64,
  recommendation STRING,       -- 'OVER', 'UNDER'
  prediction_correct BOOL,
  absolute_error FLOAT64,
  signed_error FLOAT64,        -- bias tracking
  has_prop_line BOOL,
  is_voided BOOL,
  void_reason STRING,
  confidence FLOAT64,
  edge FLOAT64,
  feature_quality_score FLOAT64,
  created_at TIMESTAMP
)
PARTITION BY game_date
CLUSTER BY system_id, pitcher_lookup;
```

### 1.2 Model Registry & Performance Tracking

```sql
CREATE TABLE mlb_predictions.model_registry (
  model_id STRING,
  system_id STRING,
  model_type STRING,           -- 'xgboost', 'catboost', 'lightgbm'
  feature_version STRING,
  status STRING,               -- 'training', 'shadow', 'production', 'disabled'
  trained_at TIMESTAMP,
  training_window_days INT64,
  training_samples INT64,
  test_accuracy FLOAT64,
  test_mae FLOAT64,
  vegas_bias FLOAT64,
  gcs_path STRING,
  sha256_hash STRING,
  created_at TIMESTAMP
);

CREATE TABLE mlb_predictions.model_performance_daily (
  game_date DATE,
  system_id STRING,
  hr_7d FLOAT64,
  hr_14d FLOAT64,
  hr_30d FLOAT64,
  mae_7d FLOAT64,
  mae_14d FLOAT64,
  samples_7d INT64,
  brier_score_7d FLOAT64,
  decay_state STRING,          -- 'HEALTHY', 'WATCH', 'DEGRADING', 'BLOCKED'
  created_at TIMESTAMP
)
PARTITION BY game_date
CLUSTER BY system_id;
```

### 1.3 Signal System (Adapt from NBA)

**MLB-specific signals to build:**

| Signal | Logic | NBA Analog |
|--------|-------|------------|
| `high_edge` | Edge >= 1.0 K | Same |
| `swstr_surge` | SwStr% last 3 > season avg + 2% | `hot_form_over` |
| `velocity_drop_under` | FB velocity down 1.5+ mph | New — MLB-specific |
| `umpire_k_friendly` | Umpire K-rate top 25% | New — MLB-specific |
| `ballpark_k_boost` | Park K-factor > 1.05 | New — MLB-specific |
| `opponent_k_prone` | Team K-rate top 25% | `dvp_favorable` |
| `short_rest_under` | < 4 days rest | `rest_advantage_2d` |
| `line_movement_over` | Line dropped 0.5+ from open | `sharp_line_drop_under` |
| `weather_cold_under` | Temp < 50F | New — MLB-specific |
| `platoon_advantage` | Pitcher hand vs lineup handedness | New — MLB-specific |
| `ace_pitcher_over` | Top 20% K/9 pitcher | `starter_under` analog |
| `bullpen_game_skip` | Opener/bullpen game | Negative filter |
| `il_return_skip` | First start back from IL | Negative filter |
| `high_variance_under` | K std > 3.5 last 10 | `volatile_scoring_over` analog |

```sql
CREATE TABLE mlb_predictions.signal_health_daily (
  game_date DATE,
  signal_name STRING,
  hr_7d FLOAT64,
  hr_14d FLOAT64,
  hr_30d FLOAT64,
  hr_season FLOAT64,
  sample_count_7d INT64,
  regime STRING,               -- 'HOT', 'NORMAL', 'COLD'
  created_at TIMESTAMP
)
PARTITION BY game_date
CLUSTER BY signal_name;
```

### 1.4 Best Bets Pipeline

Port the NBA `signal_best_bets_exporter.py` pattern:

```
Predictions → Edge Filter (1.0+ K) → Negative Filters → Signal Annotation →
Signal Count Gate (2+ real signals) → Rank by edge (OVER) / signal quality (UNDER) →
Pick Angles → Publish to GCS
```

```sql
CREATE TABLE mlb_predictions.signal_best_bets_picks (
  game_date DATE,
  pitcher_lookup STRING,
  pitcher_name STRING,
  team STRING,
  opponent STRING,
  recommendation STRING,
  line_value FLOAT64,
  predicted_strikeouts FLOAT64,
  edge FLOAT64,
  confidence FLOAT64,
  signal_count INT64,
  signals ARRAY<STRING>,
  pick_angles ARRAY<STRING>,
  algorithm_version STRING,
  created_at TIMESTAMP
)
PARTITION BY game_date
CLUSTER BY pitcher_lookup;

CREATE TABLE mlb_predictions.best_bets_filter_audit (
  game_date DATE,
  pitcher_lookup STRING,
  system_id STRING,
  filter_name STRING,
  filter_result STRING,        -- 'PASSED', 'BLOCKED'
  filter_reason STRING,
  created_at TIMESTAMP
)
PARTITION BY game_date;
```

### 1.5 Feature Store Upgrade

Current MLB feature store has 35 features. Need to add:

| New Feature | Source | Priority |
|-------------|--------|----------|
| `swstr_pct_last_3` | Statcast via pybaseball | P0 |
| `swstr_pct_last_5` | Statcast | P0 |
| `fb_velocity_last_3` | Statcast | P0 |
| `velocity_trend` | Statcast (recent - season) | P0 |
| `chase_rate_last_3` | Statcast | P1 |
| `csw_pct_last_3` | Statcast (called+swinging strikes/pitch) | P1 |
| `umpire_k_rate` | Umpire stats scraper | P1 |
| `wind_speed` | Weather scraper | P1 |
| `temperature` | Weather scraper | P1 |
| `opponent_k_rate_7d` | Rolling team K rate | P1 |
| `lineup_avg_k_rate` | Sum of announced lineup K rates | P2 |
| `opening_line` | First scraped line | P2 |
| `line_movement` | Current - opening line | P2 |
| `public_bet_pct` | Action Network / community | P2 |

Also need per-feature quality tracking (feature_N_quality, feature_N_source columns) like NBA.

### 1.6 Experiment Feature Store

```sql
CREATE TABLE mlb_predictions.ml_feature_store_experiment (
  pitcher_lookup STRING,
  game_date DATE,
  experiment_id STRING,
  feature_name STRING,
  feature_value FLOAT64,
  created_at TIMESTAMP
)
PARTITION BY game_date
CLUSTER BY experiment_id, pitcher_lookup;
```

---

## Phase 2: Model Architecture

**Timeline:** Weeks 2-4 (Mar 13 - Apr 3)
**Why:** Current models are basic XGBoost. Need NBA-grade CatBoost with governance.

### 2.1 Model Fleet (Port from NBA)

| System | Model | Purpose |
|--------|-------|---------|
| **CatBoost V1 MAE** | CatBoost regressor | Predict strikeout count |
| **CatBoost V1 Classifier** | CatBoost classifier | Predict OVER/UNDER probability |
| **CatBoost V1 Q43** | CatBoost quantile (0.43) | Conservative estimate |
| **CatBoost V1 Q57** | CatBoost quantile (0.57) | Aggressive estimate |
| **Moving Average** | Weighted 3/5/10 game avg | Baseline system |
| **XGBoost V1.6** | Current best (69.9%) | Incumbent champion |

### 2.2 Training Infrastructure

Port `quick_retrain.py` for MLB:

```python
# mlb/training/quick_retrain_mlb.py
# Key adaptations from NBA:
- Training window: 42-56 days (test both; MLB has ~5 starts/month vs NBA daily)
- Feature contract: mlb_feature_contract.py (35+ features)
- Governance gates:
  - Duplicate check
  - Vegas bias +/- 0.5 K (tighter than NBA's 1.5 pts)
  - HR >= 60% at edge 1.0+
  - N >= 30 graded
  - MAE improvement vs champion
- Output: GCS model + registry entry
```

### 2.3 Governance Gates

| Gate | Threshold | Rationale |
|------|-----------|-----------|
| Duplicate check | No same-day retrain | Prevent accidents |
| Vegas bias | +/- 0.5 K | Tighter than NBA (smaller scale) |
| HR at edge 1.0+ | >= 60% | Minimum profitability |
| Sample size | N >= 30 graded | Statistical significance |
| No direction bias | OVER/UNDER within 10pp | Balanced recommendations |
| MAE improvement | <= champion MAE | No regression |
| Tier bias | No pitcher tier > +/- 10pp | Fair across ace/mid/back-end |

---

## Phase 3: Walk-Forward 2025 Season Simulation

**Timeline:** Weeks 3-5 (Mar 20 - Apr 6)
**Why:** Before going live, replay 2025 as if it were real-time to learn retraining cadence and signal behavior.

### 3.1 Simulation Design

```
For each game_date in 2025 season (Apr 1 - Sep 28):
  1. Build feature store using ONLY data available before game_date
  2. Run all prediction systems
  3. Apply signal system
  4. Select best bets
  5. Grade against actual results
  6. Every 14 days: simulate retrain decision
  7. Track: HR, MAE, edge calibration, signal health, model decay
```

### 3.2 Key Questions to Answer

1. **Optimal training window:** Is 42 or 56 days better for MLB? (5 starts/month vs NBA daily)
2. **Retrain cadence:** Every 2 weeks? Monthly? Only on decay detection?
3. **When does model drift?** We know Jul-Aug 2025 was bad (56-59% HR). Would retraining have caught it?
4. **Which signals are predictive?** Run all proposed signals on 2025 data, measure lift
5. **Edge calibration:** At what edge threshold is MLB profitable? (NBA = 3.0+)
6. **Filter effectiveness:** Which negative filters actually improve HR?
7. **All-Star Break impact:** Is there an MLB equivalent of NBA's toxic window?

### 3.3 Walk-Forward Script

```bash
# Extend existing walk-forward validation
PYTHONPATH=. python mlb/training/walk_forward_simulation.py \
  --start-date 2025-04-01 \
  --end-date 2025-09-28 \
  --retrain-interval 14 \
  --training-window 56 \
  --output-dir results/mlb_walkforward_2025/
```

### 3.4 Expected Outputs

```
results/mlb_walkforward_2025/
  daily_predictions.csv        # Every prediction made
  daily_grades.csv             # Graded results
  retrain_log.csv              # When retrains happened, gates passed/failed
  signal_performance.csv       # Per-signal HR by period
  edge_calibration.csv         # HR by edge bucket
  model_drift_timeline.csv     # Rolling HR over time
  monthly_summary.md           # Human-readable summary
```

### 3.5 Drift Analysis Questions

From Session 48 findings, Jul-Aug 2025 showed model drift:
- Was it market efficiency improving? (bookmaker lines got better)
- Was it seasonal pattern? (fatigue, humidity, lineup changes)
- Would retraining on June data have caught it?
- Did any signals predict the drift before it happened?

---

## Phase 4: Community Intelligence (Reddit + Forums)

**Timeline:** Week 2-3 (Mar 13-24)
**Why:** Same approach as NBA — see what sharp bettors and analysts are discussing.

### 4.1 Reddit Scraping

| Subreddit | Content | Use |
|-----------|---------|-----|
| **r/sportsbook** | Daily MLB picks, sharp money discussion | Consensus angles, contrarian signals |
| **r/baseball** | Game analysis, pitcher discussion | Injury/form context not in stats |
| **r/fantasybaseball** | Streaming pitcher recommendations | Community expectations |
| **r/sportsbetting** | Betting strategy discussion | Market sentiment |

### 4.2 What to Extract

1. **Pitcher mentions + sentiment** — "Cole is dealing", "Glasnow's velocity is down"
2. **Matchup angles** — "Cubs are striking out at 30% this week"
3. **Weather/park discussion** — "Colorado is brutal for Ks in summer"
4. **Sharp money signals** — "Line moved from 6.5 to 5.5, RLM"
5. **Injury context** — "He was tipping pitches", "Coming back from blister"
6. **Umpire mentions** — "Angel Hernandez has a huge zone"

### 4.3 Scraper Architecture

```python
# scrapers/external/reddit_mlb.py
# Follow NBA pattern from scrapers/external/

class RedditMLBScraper:
    subreddits = ['sportsbook', 'baseball', 'fantasybaseball']

    def scrape(self, date):
        # Use Reddit API (PRAW) or Pushshift
        # Extract: post_id, title, body, score, comments, date
        # NLP: extract pitcher names, sentiment, key phrases
        # Output: mlb_raw.reddit_mlb_discussion
```

### 4.4 Key Angles from MLB Betting Community

From general MLB betting knowledge, these are the angles sharp bettors look at:

| Angle | Description | Signal Potential |
|-------|-------------|-----------------|
| **Reverse Line Movement (RLM)** | Line moves opposite to public betting % | HIGH — sharp money indicator |
| **Umpire zones** | Some umps have 15%+ higher K rates | HIGH — directly predictive |
| **Catcher framing** | Elite framers add 1-2 K/game | MEDIUM — subtle but real |
| **Pitch count management** | Teams limit young pitchers to 80-90 pitches | HIGH — caps K upside |
| **Bullpen state** | Tired bullpen = longer leash for starter | MEDIUM — more innings = more Ks |
| **Day game after night** | Fatigue factor | MEDIUM — well-known edge |
| **Altitude** | Coors Field depresses K rates | HIGH — park factor |
| **Humidity** | Humid air = less ball movement = fewer Ks | MEDIUM — weather feature |
| **Breaking ball + cold** | Cold weather reduces pitch movement | HIGH — interaction effect |

---

## Phase 5: Pre-Season Launch Checklist

**Timeline:** Mar 24-27 (3 days before opening day)

### 5.1 Infrastructure Enablement

- [ ] Deploy MLB prediction worker with V1.6 model
- [ ] Resume all 20+ scheduler jobs (`gcloud scheduler jobs resume mlb-*`)
- [ ] Verify scraper credentials (ODDS_API_KEY, proxies)
- [ ] Run E2E pipeline test (`bin/testing/mlb/replay_mlb_pipeline.py`)
- [ ] Verify GCS bucket permissions for exports
- [ ] Confirm BigQuery quotas for MLB datasets
- [ ] Test Slack notification channels

### 5.2 Data Pipeline Verification

- [ ] MLB Stats API schedule scraper returns 2026 games
- [ ] Odds API returns pitcher strikeout props for opening day
- [ ] Weather scraper returns data for opening day venues
- [ ] Umpire stats scraper has 2026 assignments
- [ ] BettingPros live scraper fetches current props

### 5.3 Model Verification

- [ ] V1.6 model loads and produces predictions
- [ ] Predictions written to `mlb_predictions.pitcher_strikeouts`
- [ ] Grading processor runs on completed games
- [ ] Accuracy tracked in `mlb_predictions.prediction_accuracy`
- [ ] Model performance daily table populated

### 5.4 Monitoring

- [ ] Deployment drift checker includes MLB services
- [ ] Pipeline canary queries cover MLB tables
- [ ] Slack alerts configured for MLB prediction failures
- [ ] Dashboard supports `?sport=mlb`

---

## Phase 6: In-Season Operations

**Timeline:** Apr 2026 - Sep 2026

### 6.1 Daily Workflow

```
10:00 AM ET  - Schedule scraper: games + probable pitchers
10:30 AM ET  - Props scraper: strikeout lines from Odds API
11:00 AM ET  - Lineups scraper: confirmed lineups
11:30 AM ET  - Feature store build: compute features for today's pitchers
12:00 PM ET  - Predictions: run all model systems
12:30 PM ET  - Best bets: signal evaluation + filtering
 1:00 PM ET  - Export: publish picks to GCS API
 Next day    - Grading: grade yesterday's predictions
 Next day    - Model health: update performance daily
```

### 6.2 Weekly Tasks

- Review model performance (HR by system, by direction)
- Check signal health (any signals decaying?)
- Review edge calibration (is edge threshold still correct?)
- Check Reddit/community for emerging angles
- Evaluate retrain decision (decay state machine)

### 6.3 Monthly Tasks

- Full model retrain evaluation
- Signal promotion/demotion decisions
- Feature importance analysis
- Walk-forward accuracy report
- Update strategy based on market efficiency trends

### 6.4 Known Seasonal Patterns to Watch

| Period | Pattern | Action |
|--------|---------|--------|
| **Opening week** (Mar 27-Apr 3) | Bootstrap period, limited data | Reduce confidence, skip low-data pitchers |
| **April** | Cold weather, low K rates | Weight weather features higher |
| **May-June** | Model sweet spot | Trust model, standard operations |
| **All-Star Break** (Jul 14-17) | No games, roster changes | Pause predictions, prepare for 2nd half |
| **July-August** | Historical drift period | Monitor aggressively, retrain proactively |
| **September** | Call-ups, expanded rosters | New pitchers lack data, filter aggressively |

---

## Architecture Diagram

```
Phase 1: Scrapers
  MLB Stats API ─────┐
  Odds API ──────────┤
  Statcast/pybaseball┤──→ GCS JSON ──→ Phase 2: Raw Processing ──→ mlb_raw.*
  Weather/Umpire ────┤
  Reddit/Community ──┘

Phase 3: Analytics
  mlb_raw.* ──→ pitcher_game_summary (85 cols)
              ──→ batter_game_summary (64 cols)

Phase 4: Precompute
  analytics ──→ pitcher_ml_features (50+ features)
             ──→ feature quality scoring
             ──→ zero-tolerance defaults check

Phase 5: Predictions
  features ──→ CatBoost V1 (MAE) ───┐
           ──→ CatBoost V1 (Q43) ───┤
           ──→ CatBoost V1 (Q57) ───┤──→ Cross-Model Scorer
           ──→ XGBoost V1.6 ────────┤
           ──→ Moving Average ───────┘
                        │
                        ▼
              Signal Evaluation (14+ signals)
                        │
                        ▼
              Negative Filters (10+ filters)
                        │
                        ▼
              Best Bets Selection + Pick Angles
                        │
                        ▼
Phase 6: Publishing
              GCS JSON API ──→ playerprops.io/mlb
              prediction_accuracy ──→ grading
              model_performance_daily ──→ monitoring
```

---

## New BigQuery Tables Summary

| Dataset | Table | Purpose |
|---------|-------|---------|
| `mlb_raw` | `mlbapi_pitcher_stats` | MLB Stats API pitcher stats (replaces BDL) |
| `mlb_raw` | `mlbapi_batter_stats` | MLB Stats API batter stats (replaces BDL) |
| `mlb_raw` | `mlbapi_injuries` | MLB Stats API injuries (replaces BDL) |
| `mlb_raw` | `pybaseball_statcast` | Statcast pitch-level aggregates |
| `mlb_raw` | `pybaseball_fangraphs` | FanGraphs season/split stats |
| `mlb_raw` | `reddit_mlb_discussion` | Reddit community angles |
| `mlb_predictions` | `prediction_accuracy` | Graded predictions (NBA parity) |
| `mlb_predictions` | `model_registry` | Model governance tracking |
| `mlb_predictions` | `model_performance_daily` | Daily model health + decay state |
| `mlb_predictions` | `signal_health_daily` | Signal regime tracking |
| `mlb_predictions` | `signal_best_bets_picks` | Filtered best bets with signals |
| `mlb_predictions` | `best_bets_filter_audit` | Filter audit trail |
| `mlb_predictions` | `ml_feature_store_experiment` | A/B test features |

---

## Key Decisions Needed

| Decision | Options | Recommendation |
|----------|---------|----------------|
| **Training window** | 42d vs 56d | Test both in walk-forward; MLB pitchers start every 5 days so 56d = ~11 starts |
| **Edge threshold** | 0.5K vs 1.0K vs 1.5K | Start at 1.0K, calibrate from walk-forward |
| **Retrain cadence** | Every 14d vs 28d vs decay-triggered | Decay-triggered with 28d max gap |
| **Feature count** | Keep 35 vs expand to 50+ | Expand to ~50 with Statcast + weather; but test in walk-forward first |
| **Model type** | Keep XGBoost vs switch to CatBoost | Train both, keep best as champion |
| **Signal rescue** | Port from NBA or skip | Skip initially, add after 30 days of signal data |
| **UNDER ranking** | Edge-based vs signal-based | Signal-based (same lesson as NBA — UNDER edge is flat) |

---

## Risk Register

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| **Market efficiency improved** (Jul-Aug 2025 finding) | Models plateau at 55% | HIGH | Focus on leading indicators (SwStr%, velocity) that market underprices |
| **BDL API goes down permanently** | No pitcher stats | HIGH | MLB Stats API replacement is primary plan |
| **pybaseball rate limited** | No Statcast features | MEDIUM | Cache aggressively, fallback to daily batch |
| **Model drift mid-season** | Losing money | HIGH | Decay state machine + automatic retrain triggers |
| **Insufficient signal data** | Can't evaluate signals | MEDIUM | Start shadow signals immediately, accept 30-day blind period |
| **Reddit API changes** | No community data | LOW | Multiple subreddits + fallback to web scraping |
| **All-Star Break disruption** | Model confused | MEDIUM | Pause predictions Jul 14-17, retrain on return |

---

## Sprint Plan

### Sprint 1: Data Foundation (Mar 6-12)
- [ ] Build MLB Stats API pitcher/batter stats scrapers (replace BDL)
- [ ] Add `pybaseball` to requirements, build Statcast scraper
- [ ] Build Reddit MLB scraper
- [ ] Create new BigQuery tables (prediction_accuracy, model_registry, etc.)
- [ ] Validate data quality: MLB Stats API vs BDL for 100 historical games

### Sprint 2: Model & Signal Architecture (Mar 13-19)
- [ ] Port `quick_retrain.py` for MLB (CatBoost + governance gates)
- [ ] Build MLB signal system (14 initial signals)
- [ ] Build best bets pipeline (exporter + filters)
- [ ] Create MLB feature contract (50 features)
- [ ] Train initial CatBoost model on 2024-2025 data

### Sprint 3: Walk-Forward Simulation (Mar 20-26)
- [ ] Build walk-forward simulation script
- [ ] Run full 2025 season simulation
- [ ] Analyze: optimal training window, retrain cadence, edge calibration
- [ ] Analyze: signal effectiveness, drift patterns
- [ ] Determine launch parameters from simulation results

### Sprint 4: Launch Week (Mar 27 - Apr 3)
- [ ] Deploy all MLB services
- [ ] Resume scheduler jobs
- [ ] Run E2E test on opening day
- [ ] Monitor first week of predictions
- [ ] Daily review of prediction quality

### Sprint 5+: In-Season Optimization (Apr 4+)
- [ ] Evaluate first 2 weeks of live performance
- [ ] Promote/demote signals based on live data
- [ ] First retrain decision based on live performance
- [ ] Add community angles from Reddit scraping

---

## Success Criteria

| Metric | Target | Measurement |
|--------|--------|-------------|
| **Season HR** | >= 60% | prediction_accuracy at edge 1.0+ |
| **Best Bets HR** | >= 65% | signal_best_bets after all filters |
| **Coverage** | >= 70% of games with starting pitchers | Daily prediction count vs schedule |
| **Grading coverage** | >= 90% of predictions graded | graded / total predictions |
| **Model uptime** | >= 95% | Predictions generated on 95%+ of game days |
| **Retrain success** | All retrains pass governance | model_registry gate results |
| **No silent failures** | Zero undetected outages | Monitoring alerts + daily checks |

---

## Related Documents

- `docs/06-reference/MLB-PLATFORM.md` — Current platform reference
- `docs/08-projects/current/mlb-pitcher-strikeouts/PROJECT-ROADMAP.md` — Original roadmap
- `docs/08-projects/current/mlb-pitcher-strikeouts/CURRENT-STATUS.md` — Pre-plan status
- `docs/08-projects/current/mlb-pitcher-strikeouts/FEATURE-ENGINEERING-STRATEGY.md` — Feature ideas
- `docs/08-projects/current/mlb-pitcher-strikeouts/MODEL-DRIFT-ANALYSIS-JUL-AUG-2025.md` — Drift analysis

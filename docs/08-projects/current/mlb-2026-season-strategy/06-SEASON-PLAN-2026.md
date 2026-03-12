# MLB 2026 Season Plan

*Created: Session 447 (2026-03-08)*

## System State at Season Start

*Updated Session 468 (2026-03-11)*

| Component | Status | Details |
|-----------|--------|---------|
| Model | CatBoost V2 Regressor, **36 features**, L2=10+D4 | 63.4% HR 4-season replay. Retrain before Mar 27. |
| **Multi-model fleet** | LightGBM V1 + XGBoost V1 ready | Opt-in via `MLB_ACTIVE_SYSTEMS`. Same 36-feature contract. |
| Blacklist | 23 pitchers | Session 469: -5 (new teams + tiny sample elite). Review: `bin/mlb/review_blacklist.py` |
| Signals | **20 active + 30 shadow + 6 filters + 2 obs = 58 total** | Sessions 460-468 |
| Combo signals | 3 new shadow (S465) | day_game+high_csw (73.0%), day_game+elite_peripherals (72.0%), csw+era+k9 (70.6%) |
| Rescue | opponent_k_prone only | ballpark_k_boost removed (41.2%) |
| Ultra tier | edge 0.5 + home + proj agrees + not rescued | Redesigned S455 |
| **Umpire tiebreaker** | Ranking uses umpire signal to break edge ties | S468: no RSC inflation, +0.01 bonus |
| Umpire pipeline | BQ tables + scraper + supplemental loader | Ready, PAUSED |
| Weather pipeline | BQ tables + scraper + supplemental loader | Ready, PAUSED |
| Catcher framing | BQ table + scraper + processor + supplemental | Ready (S465), PAUSED |
| Game context | Moneyline + game total via supplemental | Wired S460 |
| Away edge | 1.25 K (validated S465: 1.0/1.25/1.5 all similar) | |
| Dynamic blacklist | NOT deploying (only 3 suppressed in replay) | S465. Manual review via `review_blacklist.py` |
| RSC gate | Keep at 2 (RSC=2 = 75.9% HR in 2025) | S465 finding |
| **Dockerfile** | Fixed: `COPY ml/` added (was missing — /best-bets would 500) | S468 CRITICAL fix |
| **BQ tables** | All 4 training + 3 output tables verified OK | S468 verification |
| 24 schedulers | ALL PAUSED | Resume Mar 24 |
| 2026 schedule | Not loaded | First scrape after resume |

## Expected Performance (4-Season Replay, L2=10+D4)

| Metric | 4-Season Total | 2025 Only |
|--------|---------------|-----------|
| BB HR | 63.4% | 65.9% |
| BB Record | 1538-916 | 548-283 |
| Ultra HR | 69.6% | 69.6% |
| P&L | +470.7u | +249u |
| ROI | 12.8% | 20.0% |
| Picks/day | ~5 | ~5 |
| Profitable seasons | 4/4 | — |

## Timeline

### Week -2: Pre-Season Prep (Mar 8-17)
- [x] BQ tables for umpire/weather created
- [x] Supplemental loader built + tested (19 tests)
- [x] /best-bets endpoint added to worker
- [x] Blacklist expanded 23 → 28
- [x] ballpark_k_boost removed from rescue
- [x] swstr_surge demoted to shadow
- [x] **Ballpark factors loaded** — 2025+2026 seasons (30 teams each) in `mlb_reference.ballpark_factors`
- [x] **Statcast backfill running** — 2024-03-28 to 2025-06-30 (was only Jul-Sep 2025, now full coverage)
- [x] **Feature store audit completed** (Session 448) — all 36 features traced to data sources
- [x] **Dockerfile fixed** (Session 468) — `COPY ml/` was missing, /best-bets endpoint would crash
- [x] **Multi-model fleet** (Session 468) — LightGBM V1 + XGBoost V1 predictors + training scripts
- [x] **Umpire tiebreaker** (Session 468) — ranking breaks ties via umpire signal (no RSC inflation)
- [x] **Training SQL cleanup** (Session 468) — 5 dead features removed, contract 40→36
- [x] **Replay sync** (Session 468) — MAX_PICKS_PER_DAY 3→5 matches production
- [x] **Blacklist review script** (Session 468) — `bin/mlb/review_blacklist.py`
- [x] **BQ verification** (Session 468) — all training + output tables confirmed healthy
- [ ] **TODO: Backfill 2025 umpire assignments from MLB API** (historical data for signal validation)

### Week -1: Model Training (Mar 18-23)
```bash
# 1. Train final model
PYTHONPATH=. python scripts/mlb/training/train_regressor_v2.py \
    --training-end 2026-03-20 --window 120

# 2. Upload to GCS
gsutil cp models/mlb/catboost_mlb_v2_regressor_*.cbm \
    gs://nba-props-platform-ml-models/mlb/

# 3. Push code (auto-deploys NBA, not MLB)
git push origin main

# 4. Manual MLB worker deploy
gcloud builds submit --config cloudbuild-mlb-worker.yaml
gcloud run services update-traffic mlb-prediction-worker \
    --region=us-west2 --to-latest

# 5. Set env vars (ALWAYS use --update-env-vars, NEVER --set-env-vars)
gcloud run services update mlb-prediction-worker \
    --region=us-west2 \
    --update-env-vars="\
MLB_ACTIVE_SYSTEMS=catboost_v2_regressor,\
MLB_CATBOOST_V2_MODEL_PATH=gs://nba-props-platform-ml-models/mlb/catboost_mlb_v2_regressor_YYYYMMDD.cbm,\
MLB_EDGE_FLOOR=0.75,\
MLB_AWAY_EDGE_FLOOR=1.25,\
MLB_BLOCK_AWAY_RESCUE=true,\
MLB_MAX_EDGE=2.0,\
MLB_MAX_PROB_OVER=0.85,\
MLB_MAX_PICKS_PER_DAY=5,\
MLB_UNDER_ENABLED=false"
```

### Day 0: Resume (Mar 24)
```bash
./bin/mlb-season-resume.sh
```
- Unpauses all 24 MLB scheduler jobs
- Schedule scraper fires first, populates 2026 calendar
- Umpire assignment scraper starts daily at 11:30 AM ET
- Weather scraper starts daily
- Props scraper starts at 10:30 AM / 12:30 PM ET

### Opening Day (Mar 27)
- Verify predictions generating for both v1 and v2
- Check /best-bets endpoint manually
- Verify ultra tags in BQ
- Monitor filter audit (whole_line_over, pitcher_blacklist should fire)

### Week 1 (Mar 27 - Apr 2)
- [ ] Predictions generating daily
- [ ] Best bets publishing 3-5 picks/day (MAX_PICKS=5)
- [ ] Ultra picks appearing (expect ~0.4/day)
- [ ] Umpire data flowing to BQ (umpire_k_friendly fires as tiebreaker)
- [ ] Weather data flowing to BQ (verify weather_cold_under logs in shadow)
- [ ] Algorithm version = `mlb_v8_s456_v3final_away_5picks`

### 3-Week Checkpoint (Apr 14)
- [ ] Force retrain with first 2 weeks of in-season data
- [ ] If multi-model: compare CatBoost vs LightGBM vs XGBoost live HR
- [ ] Review blacklist: `PYTHONPATH=. python bin/mlb/review_blacklist.py --since 2026-03-27`
- [ ] Check umpire_k_friendly tiebreaker: any edge in pick selection?
- [ ] Check weather_cold_under signal: accumulating data?

### 6-Week Review (May 5)
- [ ] **UNDER enablement decision** — if OVER HR >= 58%, enable UNDER
- [ ] Review rescue picks — is opponent_k_prone still net-positive?
- [ ] Signal promotion decisions:
  - weather_cold_under: promote if HR >= 60% at N >= 30
  - line_movement_over: promote if HR >= 60% at N >= 30
  - ace_pitcher_over: promote if HR >= 60% at N >= 30
- [ ] Blacklist review: add any new <45% HR pitchers at N >= 10
- [ ] Mid-season replay with 2026 in-season data

### Monthly Retrain Cadence
- Every 14 days (matches replay's 13 retrains over 181 game days)
- Training window: 120 days
- After retrain: verify MAE, compare edges, spot-check blacklisted pitchers

## Data Gaps & Backfill Needs

### Complete — No Backfill Needed
- `mlb_raw.bp_pitcher_props`: 25,404 rows (2022-04 → 2025-09)
- `mlb_raw.oddsa_pitcher_props`: 60,589 rows (2024-04 → 2025-09)
- `mlb_analytics.pitcher_game_summary`: 10,166 rows (2024-03 → 2025-09)
- `mlb_analytics.batter_game_summary`: 97,679 rows (2024-03 → 2025-09)
- `mlb_analytics.pitcher_rolling_statcast`: 39,918 rows (2024-03 → 2025-10)
- `mlb_raw.fangraphs_pitcher_season_stats`: 1,704 rows (2024-2025, 99.6% coverage)
- `mlb_raw.mlb_schedule`: 9,881 rows (2024-03 → 2025-09)
- `mlb_raw.mlbapi_batter_stats`: 87,147 rows (2024-03 → 2025-09)
- `mlb_predictions.pitcher_strikeouts`: 16,666 rows (2024-04 → 2025-09)
- `mlb_reference.ballpark_factors`: **LOADED** 2025+2026 (30 teams each) — Session 448

### Backfilled (Session 448)
- `mlb_raw.statcast_pitcher_daily`: **WAS** Jul-Sep 2025 only (9,629 rows). **NOW** backfilling 2024-03-28 → 2025-06-30 to fill Apr-Jun 2025 and all 2024 gaps. Fills features f50-f53 (swstr_pct_last_3, fb_velocity_last_3, swstr_trend, velocity_change). Previous training coverage was 91.3% — will be ~98%+.

### Known Empty — Not Needed for Training
- `mlb_raw.oddsa_game_lines`: **0 rows** — scraper never ran. Game totals/moneylines already in `pitcher_game_summary` via odds data. Training SQL doesn't use this table directly.
- `mlb_raw.mlbapi_pitcher_stats`: **0 rows** — pitcher stats come from `mlb_raw.mlb_pitcher_stats` (via game feed scraper). Not a gap.
- `mlb_raw.bdl_player_versus`: **0 rows** — BDL retired. `vs_opponent_k_per_9` computed from game history in PGS instead (46% coverage, improves during season).
- `mlb_precompute.pitcher_ml_features`: **0 rows** — Phase 4 feature store never populated. Training/prediction bypass it (query BQ directly). Not blocking.

### Dead Data Sources (BDL Retired)
- `bdl_pitcher_splits` (972 rows): Retired. PGS computes home/away K splits from actual game data.
- `bdl_pitcher_stats` (20 rows): Effectively dead. Replaced by `mlb_raw.mlb_pitcher_stats` (game feed).
- `_get_pitcher_splits()` in Phase 4 processor returns `{}`. Features f11/f13 always 0.0 in Phase 4 but PGS has real values.
- `_get_batter_splits()` queries nonexistent `bdl_batter_splits` table.
- `_get_pitcher_handedness()` queries `bdl_pitchers` — may need MLB API replacement.

### Needs Population at Season Start
- `mlb_raw.mlb_umpire_assignments`: **EMPTY** — scraper will start populating Mar 24+
- `mlb_raw.mlb_umpire_stats`: **EMPTY** — scraper will populate with 2026 season stats
- `mlb_raw.mlb_weather`: **EMPTY** — scraper will start populating Mar 24+
- `mlb_raw.mlb_schedule` 2026: **EMPTY** — schedule scraper populates on resume

### Optional Backfill (Nice-to-Have)
- **2025 umpire assignments backfill**: Would let us validate umpire_k_friendly signal against 2025 replay data. Requires running the umpire scraper for historical dates.
- **2025 weather backfill**: Would let us validate weather_cold_under signal. Lower priority — cold games are Apr/Sep/Oct only.

## Feature Coverage Audit (Session 448)

Training SQL joins 4 tables: `bp_pitcher_props` + `pitcher_game_summary` + `statcast_rolling` + `fangraphs`. Coverage rates on 5,695 training rows:

| Feature Group | Source | Coverage | Notes |
|---------------|--------|----------|-------|
| Rolling K stats (f00-f04) | pitcher_game_summary | 100% | Core — always present |
| Season stats (f05-f09) | pitcher_game_summary | 100% | |
| Game context (f10, f25) | pitcher_game_summary | 100% | is_home, is_day_game |
| Opponent K rate (f15) | pitcher_game_summary | 100% | Rolling 15g from batter stats |
| Ballpark K factor (f16) | pitcher_game_summary | 100% | Computed from venue history |
| Statcast (f19, f19b) | fangraphs season stats | 99.6% | SwStr%, CSW% |
| Workload (f20-f23) | pitcher_game_summary | 100% | |
| Line-relative (f30, f32) | bp_pitcher_props | 100% | K avg vs line, line level |
| Projections (f40-f44) | bp_pitcher_props | 100% | BP projection, implied prob |
| **Statcast rolling (f50-f53)** | **pitcher_rolling_statcast** | **91.3% → ~98%+** | **Backfill in progress** |
| Vs opponent (f65-f66) | pitcher_game_summary | 46.3% | Improves during season |
| Deep workload (f68) | pitcher_game_summary | 100% | K per pitch |
| FanGraphs advanced (f70-f73) | fangraphs_pitcher_season_stats | 99.6% | o_swing, z_contact, FIP, GB% |

### Backup Scraper Assessment

| Data Source | Backup? | Risk |
|-------------|---------|------|
| BettingPros Props (training anchor) | Odds API | LOW |
| Odds API Props (K lines) | BettingPros | LOW |
| Statcast (pybaseball) | None | MEDIUM — MLB API could work |
| FanGraphs | None | LOW — season-level, updates rarely |
| MLB Schedule | MLB Stats API (primary) | LOW |

### Potential New Features for Testing

| Feature | Source | Why | Effort | Priority |
|---------|--------|-----|--------|----------|
| Catcher framing score | Baseball Savant | Elite catchers add ~0.5 K/game. Shadow signal exists but no data. | Medium | HIGH |
| Spin rate trends | pybaseball (already have) | Spin drops correlate with K% drops. Derive from existing Statcast. | Low | MEDIUM |
| Lineup batting order weight | MLB API (already have) | Top-order batters K less. Weight bottom-up by position. | Low | LOW |
| Batter platoon K-rate | Derive from batter_game_summary | Replace dead BDL splits with actual game-derived vs LHP/RHP. | Low | MEDIUM |

## Key Decision Points

| Date | Decision | Criteria |
|------|----------|----------|
| Apr 14 | First retrain | Automatic — 14d cadence |
| May 1 | UNDER enablement | OVER HR >= 58% live |
| May 5 | Signal promotions | HR >= 60% at N >= 30 |
| Jun 1 | Blacklist review | Add <45% HR at N >= 10 |
| Jul 15 | ASB prep | Model holds through schedule changes? |
| Sep 1 | Playoff strategy | Different edge floor for September? |

## Dead Ends — Do NOT Revisit

See `docs/08-projects/current/mlb-2026-season-strategy/05-DEAD-ENDS.md`

Key: composite scoring, ensemble models, DOW filters, derived features, hyperparameter tuning, static opponent/venue filters, seasonal phases, swstr_surge rescue, ultra at 1.0 edge.
